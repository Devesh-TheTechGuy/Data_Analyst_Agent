"""FastAPI entrypoint for local use and Vercel."""

import hashlib
import hmac
import json
import os
import queue
import threading
from pathlib import Path

from dotenv import load_dotenv
from fastapi import FastAPI, File, HTTPException, Request, Response, UploadFile
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent
load_dotenv(ROOT / ".env")

import core
import datasets
import memory
import storage
from tools import DATASET, SUPPORTED_EXTENSIONS

app = FastAPI(title="Glassboard Data Analyst")
app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")


def configured():
    missing = []
    if os.getenv("VERCEL"):
        if not storage.DATABASE_URL:
            missing.append("DATABASE_URL")
        if not os.getenv("APP_PASSWORD"):
            missing.append("APP_PASSWORD")
    return missing


def session_token():
    secret = os.getenv("SESSION_SECRET") or os.getenv("APP_PASSWORD", "local-only")
    payload = b"glassboard-session-v1:" + os.getenv("APP_PASSWORD", "").encode()
    return hmac.new(secret.encode(), payload, hashlib.sha256).hexdigest()


def is_authenticated(request):
    password = os.getenv("APP_PASSWORD")
    return not password or hmac.compare_digest(request.cookies.get("glassboard_session", ""), session_token())


@app.middleware("http")
async def guard(request: Request, call_next):
    if request.url.path.startswith("/api/") and request.url.path not in {"/api/status", "/api/auth/login"}:
        if configured():
            return JSONResponse({"detail": "Server setup required: " + ", ".join(configured())}, status_code=503)
        if not is_authenticated(request):
            return JSONResponse({"detail": "Sign in to continue"}, status_code=401)
    return await call_next(request)


@app.get("/")
def home():
    return FileResponse(ROOT / "static" / "index.html")


@app.get("/api/status")
def status(request: Request):
    return {"ready": not configured(), "missing": configured(), "authenticated": is_authenticated(request),
            "chat_ready": bool(os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API"))}


class LoginBody(BaseModel):
    password: str


@app.post("/api/auth/login")
def login(body: LoginBody, response: Response):
    expected = os.getenv("APP_PASSWORD")
    if configured() or not expected or not hmac.compare_digest(body.password, expected):
        raise HTTPException(401, "Incorrect password")
    response.set_cookie("glassboard_session", session_token(), httponly=True, secure=bool(os.getenv("VERCEL")), samesite="lax", max_age=60 * 60 * 24 * 30)
    return {"ok": True}


@app.post("/api/auth/logout")
def logout(response: Response):
    response.delete_cookie("glassboard_session")
    return {"ok": True}


@app.get("/api/datasets")
def list_datasets():
    return datasets.list_datasets()


@app.post("/api/datasets")
async def upload_dataset(file: UploadFile = File(...)):
    if Path(file.filename or "").suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, "Unsupported dataset format")
    limit = 4 * 1024 * 1024 if os.getenv("VERCEL") else 25 * 1024 * 1024
    content = await file.read(limit + 1)
    if len(content) > limit:
        raise HTTPException(413, f"This upload exceeds the {limit // (1024 * 1024)} MB limit")
    try:
        return datasets.upload(file.filename, content)
    except Exception as exc:
        raise HTTPException(400, f"Could not load dataset: {exc}") from exc


class UploadStart(BaseModel):
    filename: str
    size_bytes: int = Field(gt=0, le=50 * 1024 * 1024)


@app.post("/api/uploads/start")
def start_upload(body: UploadStart):
    if Path(body.filename).suffix.lower() not in SUPPORTED_EXTENSIONS:
        raise HTTPException(400, "Unsupported dataset format")
    return storage.create_upload_session(Path(body.filename).name, body.size_bytes)


@app.put("/api/uploads/{upload_id}/chunks/{seq}")
async def upload_chunk(upload_id: str, seq: int, request: Request):
    if seq < 0 or seq > 17:
        raise HTTPException(400, "Invalid chunk number")
    content = await request.body()
    if not content or len(content) > 3 * 1024 * 1024:
        raise HTTPException(413, "Chunk must be between 1 byte and 3 MB")
    if not storage.save_upload_chunk(upload_id, seq, content):
        raise HTTPException(404, "Upload session not found")
    return {"ok": True}


@app.post("/api/uploads/{upload_id}/complete")
def complete_upload(upload_id: str):
    session = storage.get_upload_session(upload_id)
    if not session:
        raise HTTPException(404, "Upload session not found")
    chunks = session["chunks"]
    if [chunk["seq"] for chunk in chunks] != list(range(len(chunks))):
        raise HTTPException(400, "Upload has missing chunks")
    content = b"".join(bytes(chunk["content"]) for chunk in chunks)
    if len(content) != session["size_bytes"]:
        raise HTTPException(400, "Uploaded file size does not match")
    try:
        item = datasets.upload(session["filename"], content)
    except Exception as exc:
        raise HTTPException(400, f"Could not load dataset: {exc}") from exc
    storage.delete_upload_session(upload_id)
    return item


@app.delete("/api/datasets/{upload_id}")
def delete_dataset(upload_id: str):
    if not datasets.delete(upload_id):
        raise HTTPException(404, "Upload not found")
    return {"ok": True}


@app.get("/api/chats")
def list_chats():
    return storage.list_chats()


class ChatBody(BaseModel):
    title: str = Field(default="New analysis", max_length=100)


@app.post("/api/chats")
def create_chat(body: ChatBody):
    return storage.create_chat(body.title.strip() or "New analysis")


@app.get("/api/chats/{chat_id}")
def get_chat(chat_id: str):
    chat = storage.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    return chat


@app.patch("/api/chats/{chat_id}")
def rename_chat(chat_id: str, body: ChatBody):
    if not storage.rename_chat(chat_id, body.title.strip() or "New analysis"):
        raise HTTPException(404, "Chat not found")
    return {"ok": True}


@app.delete("/api/chats/{chat_id}")
def delete_chat(chat_id: str):
    if not storage.delete_chat(chat_id):
        raise HTTPException(404, "Chat not found")
    return {"ok": True}


class MessageBody(BaseModel):
    content: str = Field(min_length=1, max_length=12000)


@app.post("/api/chats/{chat_id}/messages")
def send_message(chat_id: str, body: MessageBody):
    chat = storage.get_chat(chat_id)
    if not chat:
        raise HTTPException(404, "Chat not found")
    if not (os.getenv("OPENAI_API_KEY") or os.getenv("OPENAI_API")):
        raise HTTPException(503, "Set OPENAI_API_KEY to enable chat")
    previous = [{"role": m["role"], "content": m["content"]} for m in chat["messages"]]
    question = body.content.strip()
    storage.add_message(chat_id, "user", question)
    if chat["title"] == "New analysis":
        storage.rename_chat(chat_id, question.splitlines()[0][:70])
    events = queue.Queue()

    def worker():
        try:
            result = core.run_agent(question, previous, on_activity=lambda step: events.put(("activity", step)))
            answer = storage.add_message(chat_id, "assistant", result["answer"], result["activity"])
            events.put(("final", answer))
            history = previous + [{"role": "user", "content": question}, {"role": "assistant", "content": result["answer"]}]
            learned = memory.auto_extract_and_save(history, core.get_client(), list(DATASET))
            if learned:
                events.put(("memory", {"count": len(learned)}))
        except Exception as exc:
            events.put(("error", {"message": str(exc)}))
        finally:
            events.put(None)

    threading.Thread(target=worker, daemon=True).start()

    def stream():
        while True:
            event = events.get()
            if event is None:
                break
            kind, payload = event
            yield f"event: {kind}\ndata: {json.dumps(payload, default=str)}\n\n"

    return StreamingResponse(stream(), media_type="text/event-stream", headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})


@app.get("/api/memories")
def list_memories():
    return storage.list_memories()


class MemoryBody(BaseModel):
    category: str
    key: str = Field(min_length=1, max_length=120)
    value: str = Field(min_length=1, max_length=600)
    scope: str = ""


def validate_memory(body):
    if body.category not in memory.KINDS:
        raise HTTPException(400, "Invalid memory category")
    if body.scope:
        datasets.sync()
        if body.scope not in DATASET:
            raise HTTPException(400, "Unknown dataset scope")


@app.post("/api/memories")
def create_memory(body: MemoryBody):
    validate_memory(body)
    return memory.remember(body.category, body.key, body.value, body.scope)


@app.put("/api/memories/{memory_id}")
def update_memory(memory_id: str, body: MemoryBody):
    validate_memory(body)
    try:
        changed = storage.update_memory(memory_id, body.category, body.key, body.value, body.scope)
    except Exception as exc:
        raise HTTPException(409, str(exc)) from exc
    if not changed:
        raise HTTPException(404, "Memory not found")
    return {"ok": True}


@app.delete("/api/memories/{memory_id}")
def delete_memory(memory_id: str):
    if not storage.delete_memory(memory_id):
        raise HTTPException(404, "Memory not found")
    return {"ok": True}


@app.get("/api/charts/{chart_id}")
def get_chart(chart_id: str):
    content = storage.get_chart(chart_id)
    if content is None:
        raise HTTPException(404, "Chart not found")
    return Response(content, media_type="image/png")
