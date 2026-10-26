import io
import os
import sqlite3
from contextlib import closing
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

import pandas as pd
from fastapi.testclient import TestClient

import app
import core
import datasets
import memory
import storage
from tools import DATASET, _CON, _CON_LOCK, calculate, safe_sql_query
from usage import UsageTracker


class FakeClient:
    def __init__(self, responses):
        self.responses = iter(responses)
        self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

    def create(self, **kwargs):
        return SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=next(self.responses)))])


class WorkflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.old_root, self.old_dir, self.old_ready = storage.ROOT, datasets.DATA_DIR, storage._ready
        storage.ROOT = Path(self.tmp.name)
        storage._ready = False
        datasets.DATA_DIR = Path(self.tmp.name) / "data"
        datasets.DATA_DIR.mkdir()
        datasets._loaded.clear()
        datasets._errors.clear()
        with _CON_LOCK:
            for name in list(DATASET):
                DATASET.pop(name)
                try:
                    _CON.unregister(name)
                except Exception:
                    pass
        self.addCleanup(self.restore)

    def restore(self):
        storage.ROOT, datasets.DATA_DIR, storage._ready = self.old_root, self.old_dir, self.old_ready
        datasets._loaded.clear()
        datasets._errors.clear()

    def test_folder_discovery_refresh_and_upload_names(self):
        csv = datasets.DATA_DIR / "Quarterly Sales.csv"
        csv.write_text("region,revenue\nEast,10\nWest,20\n")
        excel = datasets.DATA_DIR / "Budget.xlsx"
        pd.DataFrame({"month": [1, 2], "value": [4, 8]}).to_excel(excel, index=False)
        found = datasets.sync()["datasets"]
        self.assertEqual({d["name"] for d in found}, {"quarterly_sales", "budget"})
        csv.write_text("region,revenue\nEast,10\nWest,20\nNorth,30\n")
        self.assertEqual(next(d["rows"] for d in datasets.sync()["datasets"] if d["name"] == "quarterly_sales"), 3)
        self.assertEqual(len(DATASET["quarterly_sales"]), 3)
        uploaded = datasets.upload("Quarterly Sales.csv", b"region,revenue\nSouth,40\n")
        self.assertEqual(uploaded["name"], "quarterly_sales_2")
        self.assertTrue(datasets.delete(uploaded["id"]))
        self.assertNotIn("quarterly_sales_2", DATASET)

    def test_memory_extracts_multiple_and_retrieves_only_relevant(self):
        client = FakeClient(['{"changes":[{"action":"upsert","category":"definition","key":"active customer","value":"order in past 30 days","scope":"sales"},{"action":"upsert","category":"preference","key":"currency","value":"show USD with 2 decimals","scope":""}]}'])
        saved = memory.auto_extract_and_save([{"role": "user", "content": "An active customer placed an order in the past 30 days. Show USD to 2 decimals."}], client, ["sales"])
        self.assertEqual(len(saved), 2)
        definition = next(m for m in storage.list_memories() if m["key"] == "active customer")
        selector = FakeClient(['{"ids":["' + definition["id"] + '"]}'])
        selected = memory.relevant_memories("Count active customers in sales", selector, ["sales"])
        self.assertEqual([m["key"] for m in selected], ["active customer"])
        correction = FakeClient(['{"changes":[{"action":"upsert","id":"' + definition["id"] + '","category":"definition","key":"active customer","value":"order in past 60 days","scope":"sales"}]}'])
        changed = memory.auto_extract_and_save([{"role":"user","content":"Correction: active means an order in 60 days."}], correction, ["sales"])
        self.assertEqual(changed[0]["id"], definition["id"])
        self.assertEqual(len(storage.list_memories()), 2)
        self.assertEqual(changed[0]["value"], "order in past 60 days")

    def test_agent_uses_tool_result_before_final_answer(self):
        class Message:
            def __init__(self, content=None, calls=None):
                self.content, self.tool_calls = content, calls
            def model_dump(self, exclude_none=True):
                data = {"role":"assistant", "content":self.content}
                if self.tool_calls:
                    data["tool_calls"] = [{"id": c.id, "type":"function", "function":{"name":c.function.name,"arguments":c.function.arguments}} for c in self.tool_calls]
                return data
        call = SimpleNamespace(id="call_1", function=SimpleNamespace(name="calculate", arguments='{"expression":"2+2"}'))
        replies = iter([Message(calls=[call]), Message(content="The answer is 4.")])
        sent = []
        def create(**kwargs):
            sent.append([dict(message) for message in kwargs["messages"]])
            n=len(sent)
            return SimpleNamespace(choices=[SimpleNamespace(message=next(replies))], usage=SimpleNamespace(prompt_tokens=1500+n*100, completion_tokens=20, prompt_tokens_details=SimpleNamespace(cached_tokens=1024 if n==2 else 0)))
        fake = SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create)))
        with patch.object(core, "get_client", return_value=fake), patch.object(core.datasets, "sync"), patch.object(core.memory, "format_memory_for_prompt", return_value="None relevant."):
            result = core.run_agent("What is 2+2?")
        self.assertEqual(result["answer"], "The answer is 4.")
        self.assertEqual(result["activity"][1]["result"], "4")
        self.assertEqual(sent[1][-1]["content"], "4")
        self.assertEqual(result["usage"]["input_tokens"], 3300)
        self.assertEqual(result["usage"]["cached_tokens"], 1024)
        self.assertEqual(result["usage"]["context_tokens"], 1700)

    def test_api_upload_memory_and_streamed_answer(self):
        with patch.dict(os.environ, {"APP_PASSWORD": "", "OPENAI_API_KEY": "test-only"}):
            client = TestClient(app.app)
            self.assertEqual(client.get("/").status_code, 200)
            response = client.post("/api/datasets", files={"file": ("test.csv", b"n\n1\n2\n", "text/csv")})
            self.assertEqual(response.status_code, 200)
            upload = response.json()
            self.assertEqual(upload["name"], "test")
            created = client.post("/api/memories", json={"category":"definition","key":"test metric","value":"n > 1","scope":"test"})
            self.assertEqual(created.status_code, 200)
            memory_id = created.json()["id"]
            self.assertEqual(client.put(f"/api/memories/{memory_id}", json={"category":"definition","key":"test metric","value":"n >= 1","scope":"test"}).status_code, 200)
            self.assertEqual(client.get("/api/memories").json()[0]["value"], "n >= 1")
            chat_id = client.post("/api/chats", json={"title":"New analysis"}).json()["id"]
            step = {"label":"Calculating","tool":"calculate","arguments":{},"result":"2","error":False}
            def fake_run(question, history, on_activity, **kwargs):
                self.assertEqual(kwargs["api_key"], "sk-test-key")
                on_activity(step)
                kwargs["usage_tracker"].add({"prompt_tokens":1000,"completion_tokens":30,"prompt_tokens_details":{"cached_tokens":128}}, context=True)
                kwargs["on_usage"](kwargs["usage_tracker"].snapshot())
                return {"answer":"There are 2 rows.", "activity":[step], "usage":kwargs["usage_tracker"].snapshot()}
            with patch.object(app.core, "run_agent", side_effect=fake_run), patch.object(app.memory, "auto_extract_and_save", return_value=[]):
                response = client.post(f"/api/chats/{chat_id}/messages", json={"content":"Count rows"}, headers={"X-OpenAI-API-Key":"sk-test-key"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("event: activity", response.text)
            self.assertIn("event: usage", response.text)
            self.assertIn("event: final", response.text)
            messages = client.get(f"/api/chats/{chat_id}").json()["messages"]
            self.assertEqual(len(messages), 2)
            self.assertEqual(messages[1]["usage"]["cached_tokens"], 128)
            self.assertEqual(client.delete(f"/api/memories/{memory_id}").status_code, 200)
            self.assertEqual(client.delete(f"/api/datasets/{upload['id']}").status_code, 200)
            payload = b"amount\n100\n200\n"
            session = client.post("/api/uploads/start", json={"filename":"large.csv","size_bytes":len(payload)}).json()
            self.assertEqual(client.put(f"/api/uploads/{session['id']}/chunks/0", content=payload[:7]).status_code, 200)
            self.assertEqual(client.put(f"/api/uploads/{session['id']}/chunks/1", content=payload[7:]).status_code, 200)
            completed = client.post(f"/api/uploads/{session['id']}/complete")
            self.assertEqual(completed.status_code, 200)
            self.assertEqual(completed.json()["rows"], 2)

    def test_password_protects_workspace(self):
        with patch.dict(os.environ, {"APP_PASSWORD":"test-password", "SESSION_SECRET":"test-secret"}):
            client = TestClient(app.app)
            self.assertFalse(client.get("/api/status").json()["authenticated"])
            self.assertEqual(client.get("/api/status").headers["cache-control"], "private, no-store")
            self.assertEqual(client.get("/api/chats").status_code, 401)
            self.assertEqual(client.get("/api/chats").headers["cache-control"], "private, no-store")
            self.assertEqual(client.post("/api/auth/login", json={"password":"wrong"}).status_code, 401)
            self.assertEqual(client.post("/api/auth/login", json={"password":"test-password"}).status_code, 200)
            self.assertEqual(client.get("/api/chats").status_code, 200)

    def test_chat_errors_do_not_expose_provider_details(self):
        with patch.dict(os.environ, {"APP_PASSWORD": "", "OPENAI_API_KEY": "owner-test-secret"}):
            client = TestClient(app.app)
            chat_id = client.post("/api/chats", json={"title": "New analysis"}).json()["id"]
            with patch.object(app.core, "run_agent", side_effect=RuntimeError("sk-private-example-key")):
                response = client.post(f"/api/chats/{chat_id}/messages", json={"content": "Analyze"})
            self.assertEqual(response.status_code, 200)
            self.assertIn("event: error", response.text)
            self.assertNotIn("sk-private-example-key", response.text)

    def test_render_requires_persistent_storage_and_cookie_secret(self):
        with patch.dict(os.environ, {"RENDER":"true", "APP_PASSWORD":""}):
            with patch.object(app.storage, "DATABASE_URL", None):
                client = TestClient(app.app)
                status = client.get("/api/status").json()
                self.assertEqual(status["missing"], ["DATABASE_URL", "SESSION_SECRET or APP_PASSWORD"])
                self.assertEqual(client.get("/api/chats").status_code, 503)
        with patch.dict(os.environ, {"RENDER":"true", "APP_PASSWORD":"test-password"}):
            with patch.object(app.storage, "DATABASE_URL", "postgresql://test-host/database"):
                client = TestClient(app.app)
                self.assertEqual(app.configured(), [])
                response = client.get("/")
                self.assertEqual(response.status_code, 200)
                self.assertIn("secure", response.headers["set-cookie"].lower())

    def test_public_guests_have_separate_chats_uploads_and_memories(self):
        with patch.dict(os.environ, {"PUBLIC_ACCESS":"true", "APP_PASSWORD":"cookie-secret", "OPENAI_API_KEY":"test-only"}):
            first, second = TestClient(app.app), TestClient(app.app)
            self.assertTrue(first.get("/api/status").json()["authenticated"])
            self.assertTrue(second.get("/api/status").json()["authenticated"])
            uploaded = first.post("/api/datasets", files={"file": ("private.csv", b"value\n17\n", "text/csv")}).json()
            self.assertEqual(uploaded["name"], "private")
            self.assertNotIn("private", [d["name"] for d in second.get("/api/datasets").json()["datasets"]])
            self.assertEqual(second.delete(f"/api/datasets/{uploaded['id']}").status_code, 404)
            other_upload = second.post("/api/datasets", files={"file": ("private.csv", b"value\n25\n", "text/csv")}).json()
            self.assertEqual(other_upload["name"], "private")
            own_chat = first.post("/api/chats", json={"title":"My analysis"}).json()["id"]
            self.assertEqual(second.get(f"/api/chats/{own_chat}").status_code, 404)
            self.assertEqual(second.delete(f"/api/chats/{own_chat}").status_code, 404)
            self.assertNotIn(own_chat, [c["id"] for c in second.get("/api/chats").json()])
            memory_id = first.post("/api/memories", json={"category":"preference", "key":"currency", "value":"INR"}).json()["id"]
            self.assertEqual(second.get("/api/memories").json(), [])
            self.assertEqual(second.delete(f"/api/memories/{memory_id}").status_code, 404)
            session = first.post("/api/uploads/start", json={"filename":"more.csv", "size_bytes":8}).json()["id"]
            self.assertEqual(second.put(f"/api/uploads/{session}/chunks/0", content=b"x\n1\n").status_code, 404)

            def own_query(*args, **kwargs):
                datasets.sync()
                return {"answer": safe_sql_query("SELECT value FROM private"), "activity": [], "usage": {}}
            with patch.object(app.core, "run_agent", side_effect=own_query), patch.object(app.memory, "auto_extract_and_save", return_value=[]):
                first_result = first.post(f"/api/chats/{own_chat}/messages", json={"content":"Query"}, headers={"X-OpenAI-API-Key":"sk-test"})
                self.assertEqual(first_result.status_code, 200)
                self.assertIn("17", first.get(f"/api/chats/{own_chat}").json()["messages"][-1]["content"])
                second_chat = second.post("/api/chats", json={"title":"Mine"}).json()["id"]
                second_result = second.post(f"/api/chats/{second_chat}/messages", json={"content":"Query"}, headers={"X-OpenAI-API-Key":"sk-test"})
                self.assertEqual(second_result.status_code, 200)
                self.assertIn("25", second.get(f"/api/chats/{second_chat}").json()["messages"][-1]["content"])

    def test_existing_database_migrates_to_private_guest_rows(self):
        with closing(sqlite3.connect(storage.ROOT / "app_state.sqlite3")) as con, con:
            con.execute("CREATE TABLE chats (id TEXT PRIMARY KEY, title TEXT NOT NULL, created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            con.execute("INSERT INTO chats VALUES ('old-chat', 'Before guests', 'now', 'now')")
            con.execute("CREATE TABLE memories (id TEXT PRIMARY KEY, category TEXT NOT NULL, key TEXT NOT NULL, value TEXT NOT NULL, scope TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL, updated_at TEXT NOT NULL)")
            con.execute("CREATE UNIQUE INDEX memories_key_idx ON memories(category, key, scope)")
            con.execute("CREATE TABLE datasets (id TEXT PRIMARY KEY, name TEXT UNIQUE NOT NULL, filename TEXT NOT NULL, content BLOB NOT NULL, created_at TEXT NOT NULL)")
            con.execute("INSERT INTO datasets VALUES ('old-file', 'sample', 'sample.csv', ?, 'now')", (b"n\n1\n",))
        storage.init()
        self.assertEqual(storage.list_chats()[0]["id"], "old-chat")
        self.assertEqual(storage.list_uploads()[0]["name"], "sample")
        token = storage.set_owner("guest-a")
        try:
            self.assertEqual(storage.list_chats(), [])
            self.assertEqual(storage.list_uploads(), [])
            storage.upsert_memory("preference", "currency", "INR")
            storage.save_upload("sample", "sample.csv", b"n\n2\n")
        finally:
            storage.reset_owner(token)
        token = storage.set_owner("guest-b")
        try:
            storage.upsert_memory("preference", "currency", "USD")
            storage.save_upload("sample", "sample.csv", b"n\n3\n")
            self.assertEqual(storage.list_memories()[0]["value"], "USD")
            self.assertEqual(storage.list_uploads()[0]["name"], "sample")
        finally:
            storage.reset_owner(token)

    def test_workspace_key_has_ten_prompts_per_browser(self):
        with patch.dict(os.environ, {"APP_PASSWORD":"", "OPENAI_API_KEY":"owner-test-secret"}):
            client = TestClient(app.app)
            status = client.get("/api/status")
            self.assertEqual(status.json()["workspace_quota"]["remaining"], 10)
            self.assertNotIn("owner-test-secret", status.text)
            chat_id = client.post("/api/chats", json={"title":"New analysis"}).json()["id"]
            result = {"answer":"Two rows.", "activity":[], "usage":{}}
            with patch.object(app.core, "run_agent", return_value=result), patch.object(app.memory, "auto_extract_and_save", return_value=[]):
                for remaining in range(9, -1, -1):
                    response = client.post(f"/api/chats/{chat_id}/messages", json={"content":"Count rows"})
                    self.assertEqual(response.status_code, 200)
                    self.assertEqual(response.headers["X-Workspace-Prompts-Remaining"], str(remaining))
                blocked = client.post(f"/api/chats/{chat_id}/messages", json={"content":"One more"})
                self.assertEqual(blocked.status_code, 429)
                self.assertEqual(client.get("/api/status").json()["workspace_quota"]["remaining"], 0)
                personal = client.post(f"/api/chats/{chat_id}/messages", json={"content":"Using my key"},
                                       headers={"X-OpenAI-API-Key":"sk-personal-test"})
                self.assertEqual(personal.status_code, 200)
                self.assertNotIn("X-Workspace-Prompts-Remaining", personal.headers)
            another_browser = TestClient(app.app)
            self.assertEqual(another_browser.get("/api/status").json()["workspace_quota"]["remaining"], 10)

    def test_math_and_sql_are_restricted(self):
        self.assertEqual(calculate("sqrt(144) + 2"), "14.0")
        self.assertIn("Only arithmetic", calculate("().__class__"))
        self.assertIn("file system operations are disabled", safe_sql_query("SELECT * FROM read_csv_auto('secret.csv')").lower())

    def test_usage_tracker_reports_cache_and_context(self):
        tracker=UsageTracker()
        tracker.add({"prompt_tokens":2400,"completion_tokens":100,"prompt_tokens_details":{"cached_tokens":1024}}, context=True)
        tracker.add({"prompt_tokens":200,"completion_tokens":20,"prompt_tokens_details":{"cached_tokens":0}})
        self.assertEqual(tracker.snapshot()["input_tokens"],2600)
        self.assertEqual(tracker.snapshot()["context_tokens"],2400)
        self.assertEqual(tracker.snapshot()["cached_tokens"],1024)


if __name__ == "__main__":
    unittest.main()
