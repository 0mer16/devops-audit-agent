"""Small wrapper around the Gemini SDK.

The agent only needs one thing from the model: given a system prompt and the
conversation so far, return the next text reply. Keeping this interface tiny
makes it easy to swap providers and to use a fake model in the tests.
"""

import time

DEFAULT_MODEL = "gemini-flash-latest"


class LLMError(Exception):
    pass


class GeminiLLM:
    def __init__(self, api_key, model=None, temperature=0.1, timeout_s=120, max_retries=5):
        if not api_key:
            raise LLMError("GEMINI_API_KEY is not set")
        try:
            from google import genai
            from google.genai import types
        except ImportError as exc:
            raise LLMError("google-genai is not installed, run pip install -r requirements.txt") from exc
        self._types = types
        self.model = model or DEFAULT_MODEL
        self.temperature = temperature
        self.max_retries = max_retries
        self.client = genai.Client(
            api_key=api_key,
            http_options=types.HttpOptions(timeout=timeout_s * 1000),
        )

    def complete(self, system, messages):
        """messages: list of {"role": "user"|"model", "text": str}. Returns reply text."""
        types = self._types
        # Gemini returned MALFORMED_FUNCTION_CALL when earlier JSON replies were sent back as
        # "model" turns, so the history is sent as one plain transcript instead.
        contents = "\n\n".join(
            ("YOUR PREVIOUS REPLY:\n" + m["text"]) if m["role"] == "model" else m["text"]
            for m in messages
        )
        json_mode = True
        delay = 5
        for attempt in range(1, self.max_retries + 1):
            config = types.GenerateContentConfig(
                system_instruction=system,
                temperature=self.temperature,
                response_mime_type="application/json" if json_mode else None,
            )
            try:
                resp = self.client.models.generate_content(model=self.model, contents=contents, config=config)
                text = resp.text
                if not text:
                    # some models return MALFORMED_RESPONSE in JSON mode; the loop can parse
                    # plain text replies too, so retry without forcing JSON
                    json_mode = False
                    raise LLMError("empty response from model")
                return text
            except Exception as exc:
                msg = str(exc)
                retryable = any(code in msg for code in ("429", "500", "502", "503", "504",
                                                         "RESOURCE_EXHAUSTED", "UNAVAILABLE",
                                                         "DEADLINE", "timed out", "empty response"))
                if not retryable or attempt == self.max_retries:
                    # never echo the key; SDK errors don't contain it but be careful anyway
                    raise LLMError(f"Gemini request failed: {msg[:300]}") from exc
                time.sleep(delay)
                delay = min(delay * 2, 60)
        raise LLMError("Gemini request failed")
