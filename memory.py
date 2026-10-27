import os
import json

MEMORY_FILE = "agent_memory.json"
CATEGORIES = ("definitions", "preferences")


def load_memory() -> dict:
    mem = {c: {} for c in CATEGORIES}
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                mem.update(json.load(f))
        except (json.JSONDecodeError, OSError) as e:
            print(f"⚠️ Could not read {MEMORY_FILE}: {e}")
    return mem


def save_memory(data: dict) -> None:
    tmp = MEMORY_FILE + ".tmp"              # write to temp file first so a crash can't corrupt memory
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.replace(tmp, MEMORY_FILE)


def remember(category: str, key: str, value: str) -> str:
    """Saves a definition or preference. Unknown categories fall back to 'definitions'."""
    category = category if category in CATEGORIES else "definitions"
    mem = load_memory()
    mem[category][key.strip().lower()] = value.strip()
    save_memory(mem)
    return f"Remembered: '{key}' in {category}."


def forget(key: str) -> str:
    """Removes a saved entry from any category."""
    key = key.strip().lower()
    mem = load_memory()
    removed = False
    for c in CATEGORIES:
        if mem[c].pop(key, None) is not None:
            removed = True
    if removed:
        save_memory(mem)
        return f"Forgot '{key}'."
    return f"Nothing saved under '{key}'."


def format_memory_for_prompt() -> str:
    mem = load_memory()
    titles = {"definitions": "Domain Definitions", "preferences": "User Preferences"}
    lines = []
    for c in CATEGORIES:
        if mem[c]:
            lines.append(f"{titles[c]}:")
            lines += [f"- '{k}': {v}" for k, v in mem[c].items()]
    return "\n".join(lines) or "None."


def auto_extract_and_save(user_msg: str, assistant_msg: str, client) -> None:
    """Silently saves any reusable definitions/preferences the user stated this turn."""
    prompt = f"""You are a memory manager for a data analysis agent.
From the conversation turn, extract EVERY reusable domain definition, column meaning,
custom metric, or user preference (or anything the user explicitly asked to remember).
Ignore normal questions like 'what is the mean age?'.

Categories: "definitions" or "preferences" only.

Examples:
- "Active users means logins in last 30 days > 0" -> {{"category": "definitions", "key": "active users", "value": "logins_last_30d > 0"}}
- "Always round currency to 2 decimals" -> {{"category": "preferences", "key": "currency_rounding", "value": "2 decimals"}}

User: {user_msg}
Assistant: {assistant_msg}

Return RAW JSON only: {{"items": [ ... ]}}  (use an empty list if nothing qualifies)"""
    try:
        resp = client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": prompt}],
            response_format={"type": "json_object"},
            temperature=0.0,
        )
        items = json.loads(resp.choices[0].message.content).get("items", [])
        for it in items:
            key, val = it.get("key"), it.get("value")
            if key and val:
                remember(it.get("category", "definitions"), key, val)
                print(f"\n🧠 [Memory updated]: '{key}' -> {val}")
    except Exception as e:
        print(f"\n⚠️ Memory extraction failed: {e}")   # visible, but never crashes the chat