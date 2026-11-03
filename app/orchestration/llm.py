import json

import httpx


class LocalSummary:
    """Optional prose only: no tools, credentials, prompts from users or permissions."""
    def __init__(self, settings):
        self.settings = settings
        self.available = False

    async def summarize(self, counts):
        if not self.settings.ollama_enabled:
            return {"used": False, "reason": "Ollama disabled"}
        safe = {key: int(counts.get(key, 0)) for key in ("Completed", "Waiting", "Error", "Cancelled")}
        try:
            async with httpx.AsyncClient(base_url=self.settings.ollama_url, timeout=30,
                                         trust_env=False, follow_redirects=False) as client:
                async with client.stream("POST", "/api/chat", json={
                    "model": self.settings.ollama_model, "stream": False, "keep_alive": "2m",
                    "options": {"num_ctx": 2048, "num_predict": 180, "temperature": 0},
                    "messages": [{"role": "system", "content": "Summarize task counts in Vietnamese. State that execution is disabled. Do not recommend trades. You have no tools."},
                                 {"role": "user", "content": json.dumps(safe)}]}) as response:
                    response.raise_for_status()
                    chunks, size = [], 0
                    async for chunk in response.aiter_bytes():
                        size += len(chunk)
                        if size > 32_768:
                            raise ValueError("Oversized local model response")
                        chunks.append(chunk)
                content = json.loads(b"".join(chunks))["message"]["content"]
                if not isinstance(content, str):
                    raise ValueError("Invalid local model response")
            self.available = True
            return {"used": True, "text": content[:2000], "advisory_only": True}
        except (httpx.HTTPError, ValueError, KeyError, TypeError):
            self.available = False
            return {"used": False, "reason": "Local model unavailable; deterministic summary retained"}
