"""Automatic, user editable long term memory with relevance selection."""

import json
import logging
import re

import storage

KINDS = {"definition", "preference", "profile", "project"}


def load_memory():
    return storage.list_memories()


def remember(category, key, value, scope=""):
    if category not in KINDS:
        raise ValueError("Unsupported memory category")
    return storage.upsert_memory(category, key, value, scope)


def relevant_memories(question, client, dataset_names=(), limit=8):
    """Let a small model select only memories useful to this question."""
    items = load_memory()
    if not items:
        return []
    question_lower = question.lower()
    mentioned = [name for name in dataset_names if name.lower() in question_lower]
    candidates = [m for m in items if not m["scope"] or not mentioned or m["scope"] in mentioned]
    if not candidates:
        return []
    selection = [{"id": m["id"], "category": m["category"], "key": m["key"], "value": m["value"], "scope": m["scope"]} for m in candidates]
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini", temperature=0, response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": "Select only saved user memories that directly help answer the current question. A memory may be useful by meaning even without exact word overlap. Do not select unrelated facts. Return JSON {\"ids\": [ids]} with at most 8 IDs."},
                {"role": "user", "content": json.dumps({"question": question, "memories": selection})},
            ],
        )
        ids = set(json.loads(response.choices[0].message.content).get("ids", []))
        return [m for m in candidates if m["id"] in ids][:limit]
    except Exception:
        words = set(re.findall(r"[a-z0-9]+", question_lower))
        ranked = sorted(candidates, key=lambda m: len(words & set(re.findall(r"[a-z0-9]+", m["key"] + " " + m["value"]))), reverse=True)
        return [m for m in ranked if words & set(re.findall(r"[a-z0-9]+", m["key"] + " " + m["value"]))][:limit]


def format_memory_for_prompt(question="", client=None, dataset_names=()):
    items = relevant_memories(question, client, dataset_names) if client else load_memory()
    if not items:
        return "None relevant."
    return "\n".join(f"- [{m['category']}{': ' + m['scope'] if m['scope'] else ''}] {m['key']}: {m['value']}" for m in items)


def auto_extract_and_save(history, client, dataset_names=()):
    """Extract multiple durable facts from user context, including implicit facts and corrections."""
    existing = load_memory()
    try:
        response = client.chat.completions.create(
            model="gpt-4.1-mini", temperature=0, response_format={"type": "json_object"},
            messages=[
                {"role": "system", "content": (
                    "You manage long term memory for a data analysis assistant. Read the conversation context, especially the latest user message. "
                    "Keep stable, reusable facts learned from the user: definitions, column meanings, named filters, preferences, personal/project context. "
                    "The user need not say 'remember'. Save multiple facts when appropriate. Update corrected or conflicting facts. "
                    "Never save raw datasets, temporary requests, ordinary questions, assistant guesses, secrets, passwords, or API keys. "
                    "Return JSON {\"changes\":[{\"action\":\"upsert\"|\"delete\",\"id\":\"existing memory id if correcting or deleting, otherwise empty\",\"category\":\"definition\"|\"preference\"|\"profile\"|\"project\",\"key\":\"short canonical name\",\"value\":\"concise fact\",\"scope\":\"dataset name or empty string\"}]}. "
                    "When a new user fact corrects an existing memory, use its id so the stale entry is replaced. Return an empty changes array when nothing is worth remembering."
                )},
                {"role": "user", "content": json.dumps({"recent_conversation": history[-16:], "existing_memories": existing, "datasets": list(dataset_names)}, default=str)},
            ],
        )
        changes = json.loads(response.choices[0].message.content).get("changes", [])
    except Exception:
        logging.exception("Memory extraction failed")
        return []
    saved = []
    for change in changes[:12]:
        category = str(change.get("category", "")).lower()
        key = str(change.get("key", "")).strip()
        value = str(change.get("value", "")).strip()
        scope = str(change.get("scope", "")).strip().lower()
        if category not in KINDS or (not key and change.get("action") != "delete") or len(key) > 120 or len(value) > 600 or (scope and scope not in dataset_names):
            continue
        match = next((m for m in existing if m["id"] == change.get("id")), None)
        if change.get("action") == "delete":
            match = match or next((m for m in existing if (m["category"], m["key"], m["scope"]) == (category, key.lower(), scope)), None)
            if match:
                storage.delete_memory(match["id"])
        elif change.get("action") == "upsert" and value:
            try:
                if match:
                    storage.update_memory(match["id"], category, key, value, scope)
                    saved.append(next(m for m in storage.list_memories() if m["id"] == match["id"]))
                else:
                    saved.append(remember(category, key, value, scope))
            except (ValueError, StopIteration):
                logging.exception("Could not save extracted memory")
    return saved
