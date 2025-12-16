import os
import re
import time
import logging
from typing import Iterator
from dataclasses import dataclass

try:
    from google import genai
except Exception:
    genai = None

# Optional .env support for GEMINI_API_KEY and GEMINI_MODEL
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    # dotenv not installed; rely on environment variables
    pass

GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-2.0-flash-lite")

@dataclass
class LLMClient:
    api_key: str = None
    model: str = GEMINI_MODEL
    dev: bool = False
    max_retries: int = 3

    def __post_init__(self):
        # Determine dev mode: explicit flag, env var, or missing API key
        env_dev = os.getenv("USE_DEV_LLM", "").lower() in ("1", "true", "yes")
        # Prefer instance-supplied api_key, then environment variables
        env_api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.api_key = self.api_key or env_api_key
        # Allow overriding model via environment
        self.model = os.getenv("GEMINI_MODEL", self.model)
        self.dev = bool(self.dev) or env_dev or (self.api_key is None)

        if self.dev:
            # In dev mode we do not require the google-genai SDK; provide a mock client behavior
            self.client = None
            return

        if not genai:
            raise RuntimeError("google-genai SDK not installed. pip install google-genai or enable dev mode")

        try:
            # Prefer explicit api_key to avoid relying on environment variables
            self.client = genai.Client(api_key=self.api_key) if hasattr(genai, "Client") else None
        except TypeError:
            # If the package API does not accept api_key param, fall back to setting env
            os.environ.setdefault("GOOGLE_API_KEY", self.api_key)
            self.client = genai.Client() if hasattr(genai, "Client") else None

    def generate(self, prompt: str, max_output_tokens: int = 512) -> str:
        if self.dev:
            # Simple deterministic mock response for development/testing
            return f"[DEV] Mock answer for prompt: {prompt[:200]}"

        if self.client:
            client = self.client
            attempt = 0
            last_exc = None
            while attempt < self.max_retries:
                try:
                    # Use `contents` and `config` per google-genai SDK
                    resp = client.models.generate_content(
                        model=self.model,
                        contents=prompt,
                        config={"max_output_tokens": max_output_tokens},
                    )
                    text = ""
                    if hasattr(resp, "text"):
                        text = resp.text
                    elif isinstance(resp, dict):
                        # Try common shapes from genai responses
                        cand = resp.get("candidates") or resp.get("candidate")
                        if isinstance(cand, list) and cand:
                            first = cand[0] if isinstance(cand[0], dict) else None
                            if first:
                                text = first.get("content") or first.get("text") or ""
                        elif isinstance(cand, dict):
                            text = cand.get("content") or cand.get("text") or ""
                        else:
                            # Some responses provide 'output' or 'content'
                            text = resp.get("output") or resp.get("content") or ""
                    else:
                        text = str(resp)
                    return text
                except Exception as e:
                    last_exc = e
                    msg = str(e)
                    # Detect rate limit / quota errors (RESOURCE_EXHAUSTED / 429)
                    if "RESOURCE_EXHAUSTED" in msg or "429" in msg or "quota exceeded" in msg.lower():
                        secs = self._extract_retry_seconds(msg)
                        wait = secs if secs is not None else min(2 ** attempt, 60)
                        logging.warning("Rate limited by model API; retrying after %s seconds (attempt %s)", wait, attempt + 1)
                        time.sleep(wait)
                        attempt += 1
                        continue
                    # non-retryable or unknown error: bubble up
                    raise
            # if we exit loop without returning, raise last exception with context
            raise RuntimeError(f"Model request failed after {self.max_retries} attempts: {last_exc}")
        else:
            raise RuntimeError("GenAI client not available")

    def stream_generate(self, prompt: str, max_output_tokens: int = 512) -> Iterator[str]:
        if not genai:
            if self.dev:
                # yield mock streaming content in dev mode
                full = f"[DEV] Mock streaming answer for prompt: {prompt[:200]}"
                for i in range(0, len(full), 40):
                    yield full[i : i + 40]
                return
            yield "[ERROR] google-genai SDK not installed"
            return
        try:
            client = self.client
            # Use streaming endpoint with `contents` and `config`
            stream = client.models.generate_content_stream(
                model=self.model,
                contents=prompt,
                config={"max_output_tokens": max_output_tokens},
            )
            for event in stream:
                chunk_text = None
                if hasattr(event, "text"):
                    chunk_text = event.text
                elif isinstance(event, dict):
                    if "text" in event:
                        chunk_text = event["text"]
                    else:
                        cand = event.get("candidate") or event.get("candidates") or event.get("candidatesDelta")
                        if isinstance(cand, dict):
                            chunk_text = cand.get("content") or cand.get("text")
                        elif isinstance(cand, list) and cand:
                            first = cand[0]
                            if isinstance(first, dict):
                                chunk_text = first.get("content") or first.get("text")
                            else:
                                chunk_text = str(first)
                        else:
                            # Try nested 'parts' structure
                            parts = event.get("parts") or (event.get("candidate") or {}).get("parts")
                            if isinstance(parts, list) and parts:
                                # join any text parts
                                texts = [p.get("text") for p in parts if isinstance(p, dict) and p.get("text")]
                                if texts:
                                    chunk_text = "".join(texts)
                if chunk_text:
                    yield chunk_text
        except Exception as e:
            msg = str(e)
            if "RESOURCE_EXHAUSTED" in msg or "429" in msg or "quota exceeded" in msg.lower():
                secs = self._extract_retry_seconds(msg)
                if secs:
                    yield f"[ERROR] Rate limited by model API. Retry after {secs} seconds"
                else:
                    yield f"[ERROR] Rate limited by model API. Please retry later"
                return
            try:
                full = self.generate(prompt, max_output_tokens=max_output_tokens)
                yield full
            except Exception as e2:
                yield f"[ERROR] {str(e)} / {str(e2)}"

    def _extract_retry_seconds(self, msg: str) -> float | None:
        # Try a few regex patterns to extract a retry delay
        # pattern: 'retry in 53.46271898s' or 'retryDelay': '53s' or 'retryDelay": "53s"'
        m = re.search(r'retry\s*(?:in)?\s*(\d+(?:\.\d+)?)s', msg, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
        m = re.search(r'retryDelay[^\d]*(\d+(?:\.\d+)?)s', msg, flags=re.IGNORECASE)
        if m:
            try:
                return float(m.group(1))
            except Exception:
                return None
        return None
