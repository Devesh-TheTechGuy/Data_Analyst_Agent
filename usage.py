"""Token accounting from actual OpenAI API usage, including prompt cache reads."""

CONTEXT_WINDOW = 1_047_576  # GPT-4.1 published context window.


class UsageTracker:
    def __init__(self):
        self.input_tokens = 0
        self.output_tokens = 0
        self.cached_tokens = 0
        self.context_tokens = 0
        self.calls = 0

    def add(self, usage, context=False):
        if not usage:
            return
        if isinstance(usage, dict):
            prompt = usage.get("prompt_tokens") or 0
            completion = usage.get("completion_tokens") or 0
            details = usage.get("prompt_tokens_details") or {}
            cached = details.get("cached_tokens") or 0
        else:
            prompt = getattr(usage, "prompt_tokens", 0) or 0
            completion = getattr(usage, "completion_tokens", 0) or 0
            details = getattr(usage, "prompt_tokens_details", None)
            cached = getattr(details, "cached_tokens", 0) or 0
        self.input_tokens += prompt
        self.output_tokens += completion
        self.cached_tokens += cached
        self.calls += 1
        if context:
            self.context_tokens = prompt

    def snapshot(self):
        return {"model": "gpt-4.1", "input_tokens": self.input_tokens,
                "output_tokens": self.output_tokens, "cached_tokens": self.cached_tokens,
                "context_tokens": self.context_tokens, "context_window": CONTEXT_WINDOW,
                "calls": self.calls}
