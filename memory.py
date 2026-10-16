import os
import json

MEMORY_FILE = "agent_memory.json"

def load_memory() -> dict:
    """Loads saved definitions and preferences from disk."""
    if os.path.exists(MEMORY_FILE):
        try:
            with open(MEMORY_FILE, "r", encoding="utf-8") as f:
                return json.load(f)
        except Exception:
            pass
    return {"definitions": {}, "preferences": {}}

def save_memory(data: dict):
    """Saves memory back to disk."""
    with open(MEMORY_FILE, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2)

def remember(category: str, key: str, value: str) -> str:
    """
    Saves a definition or preference.
    """
    mem = load_memory()
    if category not in mem:
        mem[category] = {}
    mem[category][key.strip().lower()] = value.strip()
    save_memory(mem)
    return f"Remembered: '{key}' in {category}."

def format_memory_for_prompt() -> str:
    """Formats saved memory to be injected into the system prompt."""
    mem = load_memory()
    if not mem.get("definitions") and not mem.get("preferences"):
        return "None."
    
    lines = []
    if mem.get("definitions"):
        lines.append("Domain Definitions:")
        for k, v in mem["definitions"].items():
            lines.append(f"- '{k}': {v}")
    if mem.get("preferences"):
        lines.append("User Preferences:")
        for k, v in mem["preferences"].items():
            lines.append(f"- '{k}': {v}")
    return "\n".join(lines)

def auto_extract_and_save(user_msg: str, assistant_msg: str, client) -> None:
    """
    Silently extracts business rules, definitions, or preferences or anything that is told by the user to remember
    from the conversation turn and saves them to agent_memory.json.
    """
    extraction_prompt = f"""You are a memory manager for a data analysis agent.
Analyze this conversation turn and determine if the user established any reusable domain definition, column meaning, custom metric filter, or preference.

Examples of things to save:
- "Active users means logins in the last 30 days > 0" -> category: "definitions", key: "active users", value: "logins_last_30d > 0"
- "Churned means status = 'cancelled'" -> category: "definitions", key: "churned", value: "status == 'cancelled'"
- "Always round currency to 2 decimals" -> category: "preferences", key: "currency_rounding", value: "2 decimals"

Conversation turn:
User: {user_msg}
Assistant: {assistant_msg}

Instructions:
If a reusable rule/definition was mentioned, return JSON:
{{"found": true, "category": "definitions", "key": "exact term", "value": "concise rule"}}
If NO rules/definitions were established (just normal questions like 'what is the mean age?'), return:
{{"found": false}}
Return RAW JSON ONLY.
"""
    try:
        response = client.chat.completions.create(
            model="gpt-4.1",
            messages=[{"role": "user", "content": extraction_prompt}],
            response_format={"type": "json_object"},
            temperature=0.0
        )
        data = json.loads(response.choices[0].message.content)
        if data.get("found"):
            cat = data.get("category", "definitions")
            key = data.get("key")
            val = data.get("value")
            if key and val:
                remember(cat, key, val)
                print(f"\n🧠 [Persistent Memory Updated]: Remembered '{key}' -> {val}")
    except Exception:
        # Memory extraction should fail silently and never crash the main chat
        pass