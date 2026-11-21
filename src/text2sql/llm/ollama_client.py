"""Ollama local LLM adapter — calls the Ollama REST API (runs entirely on your machine)."""
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass

import requests

logger = logging.getLogger(__name__)

OLLAMA_BASE_URL = "http://localhost:11434"

# Recommended local models for SQL generation, ordered best→smallest.
# Pull with:  ollama pull <model_name>
OLLAMA_MODELS = [
    "qwen2.5-coder:7b",        # Best SQL quality, ~4.5 GB RAM
    "llama3.2:3b",             # Fast & small, ~2 GB RAM
    "phi3:mini",               # Very lightweight, ~2.3 GB RAM
    "codellama:7b",            # Code-focused, ~3.8 GB RAM
    "mistral:7b",              # General purpose, ~4.1 GB RAM
]


@dataclass(slots=True)
class LLMOutput:
    sql: str
    explanation: str = ""
    assumptions: list[str] | None = None
    notes: list[str] | None = None


def _is_ollama_running() -> bool:
    """Return True if the Ollama server is reachable."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=3)
        return r.ok
    except Exception:
        return False


def _list_pulled_models() -> list[str]:
    """Return the model names currently pulled in Ollama."""
    try:
        r = requests.get(f"{OLLAMA_BASE_URL}/api/tags", timeout=5)
        if r.ok:
            return [m["name"] for m in r.json().get("models", [])]
    except Exception:
        pass
    return []


class OllamaSQLGenerator:
    """Generates SQL using a locally-running Ollama model (100% offline after setup)."""

    def __init__(self, model: str | None = None, base_url: str | None = None):
        self.base_url = (base_url or OLLAMA_BASE_URL).rstrip("/")
        if not _is_ollama_running():
            raise RuntimeError(
                "Ollama is not running. Start it with:  ollama serve\n"
                "If not installed, download from https://ollama.ai"
            )

        pulled = _list_pulled_models()
        if not pulled:
            raise RuntimeError(
                "No models are pulled yet. Run:  ollama pull qwen2.5-coder:7b\n"
                "Or for a smaller model:         ollama pull llama3.2:3b"
            )

        # Use the requested model if pulled; otherwise auto-select the first available
        if model and any(model in p for p in pulled):
            self.model = model
        elif model:
            # Requested model not pulled — try to match a prefix
            matched = next((p for p in pulled if p.startswith(model.split(":")[0])), None)
            if matched:
                logger.warning("Requested model '%s' not found; using '%s' instead.", model, matched)
                self.model = matched
            else:
                raise RuntimeError(
                    f"Model '{model}' is not pulled. Available: {pulled}\n"
                    f"Pull it with:  ollama pull {model}"
                )
        else:
            # Auto-select: prefer recommended models in order
            self.model = next(
                (rec for rec in OLLAMA_MODELS if any(rec.split(":")[0] in p for p in pulled)),
                pulled[0],
            )
            logger.info("Auto-selected local model: %s", self.model)

    def generate(self, prompt: str, *, max_retries: int = 2) -> LLMOutput:
        last_exc: Exception | None = None

        for attempt in range(1, max_retries + 1):
            try:
                return self._call(self.model, prompt)
            except Exception as exc:
                last_exc = exc
                message = str(exc)
                if attempt < max_retries:
                    wait = 2.0 * attempt
                    logger.warning(
                        "Ollama attempt %d/%d failed: %s. Retrying in %.0fs...",
                        attempt, max_retries, message, wait,
                    )
                    time.sleep(wait)

        raise RuntimeError(
            f"Ollama request failed after {max_retries} attempts.\n"
            f"Model used: {self.model}\n"
            f"Last error: {last_exc}\n\n"
            "Make sure Ollama is running (ollama serve) and the model is pulled."
        )

    def _call(self, model_name: str, prompt: str) -> LLMOutput:
        """Call the Ollama /api/chat endpoint (OpenAI-compatible)."""
        payload = {
            "model": model_name,
            "messages": [
                {
                    "role": "system",
                    "content": (
                        "You are a senior database engineer. "
                        "Always respond with a single valid JSON object only — no markdown, "
                        "no extra text — in this exact schema:\n"
                        '{"sql": "...", "explanation": "...", "assumptions": [], "notes": []}'
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            "stream": False,
            "options": {
                "temperature": 0.1,
                "num_predict": 2048,
            },
        }

        resp = requests.post(
            f"{self.base_url}/api/chat",
            json=payload,
            timeout=120,  # local models can take a few seconds to generate
        )

        if not resp.ok:
            raise RuntimeError(f"Ollama HTTP {resp.status_code}: {resp.text[:300]}")

        content = resp.json().get("message", {}).get("content", "")
        if not content:
            raise RuntimeError("Ollama returned an empty response.")
        return _parse_output(content)


def _parse_output(response_text: str) -> LLMOutput:
    text = response_text.strip()
    # Strip markdown code fences if the model wrapped output
    text = re.sub(r"^```(?:json)?\s*|\s*```$", "", text, flags=re.IGNORECASE)
    payload = None
    try:
        payload = json.loads(text)
    except json.JSONDecodeError:
        start, end = text.find("{"), text.rfind("}")
        if start >= 0 and end > start:
            try:
                payload = json.loads(text[start : end + 1])
            except json.JSONDecodeError:
                payload = None

    if isinstance(payload, dict):
        sql = str(payload.get("sql", "")).strip()
        assumptions = payload.get("assumptions", [])
        notes = payload.get("notes", [])
        if not isinstance(assumptions, list):
            assumptions = [str(assumptions)]
        if not isinstance(notes, list):
            notes = [str(notes)]
        return LLMOutput(
            sql=sql,
            explanation=str(payload.get("explanation", "")).strip(),
            assumptions=[str(i) for i in assumptions],
            notes=[str(i) for i in notes],
        )

    # Fallback: extract bare SQL from code block
    code = re.search(r"```(?:sql)?\s*(.*?)```", text, re.IGNORECASE | re.DOTALL)
    sql = code.group(1).strip() if code else text
    return LLMOutput(sql=sql, explanation="SQL generated by local Ollama model.", assumptions=[], notes=[])

