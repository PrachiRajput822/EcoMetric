"""Gemma 4 planners: hosted through the Gemini API, or local through Ollama for offline use."""

from __future__ import annotations

import json
import time
from typing import Any

import httpx

from ..config import Settings
from ..data.store import Dataset
from ..tools.registry import build_tool_specs
from .base import PlannedCall, PlannerError, build_system_prompt, parse_text_call


class GeminiPlanner:
    """Gemma 4 (default gemma-4-26b-a4b-it) through the Gemini API with native function calling."""

    name = "gemini"

    def __init__(self, settings: Settings, client: Any = None):
        self.settings = settings
        self.model = settings.gemini_model
        self._client = client

    def available(self) -> bool:
        return bool(self.settings.gemini_api_key) or self._client is not None

    def _get_client(self) -> Any:
        if self._client is None:
            from google import genai
            from google.genai import types

            self._client = genai.Client(api_key=self.settings.gemini_api_key,
                                        http_options=types.HttpOptions(timeout=int(self.settings.llm_timeout * 1000)))
        return self._client

    def _generate(self, contents: str, system: str | None, tools: list[dict] | None) -> Any:
        from google.genai import types

        cfg: dict[str, Any] = {"temperature": 0.0}
        if tools:
            cfg["tools"] = [types.Tool(function_declarations=[
                types.FunctionDeclaration(name=t["name"], description=t["description"], parameters_json_schema=t["parameters"])
                for t in tools])]
            cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
        client = self._get_client()
        try:
            return client.models.generate_content(
                model=self.model, contents=contents,
                config=types.GenerateContentConfig(system_instruction=system, **cfg) if system else types.GenerateContentConfig(**cfg))
        except Exception as exc:
            # Some hosted models reject system instructions; fold them into the prompt and retry once.
            if system and "instruction" in str(exc).lower():
                return client.models.generate_content(
                    model=self.model, contents=f"{system}\n\nQuestion: {contents}", config=types.GenerateContentConfig(**cfg))
            raise

    def plan(self, question: str, ds: Dataset) -> PlannedCall:
        t0 = time.perf_counter()
        try:
            resp = self._generate(question, build_system_prompt(ds.profile), build_tool_specs(ds.profile))
        except Exception as exc:
            raise PlannerError(f"Gemini API request failed: {type(exc).__name__}") from exc
        ms = int((time.perf_counter() - t0) * 1000)
        calls = getattr(resp, "function_calls", None) or []
        if calls:
            fc = calls[0]
            return PlannedCall(tool=fc.name, args=dict(fc.args or {}), planner=self.name, model=self.model, latency_ms=ms)
        text = getattr(resp, "text", "") or ""
        parsed = parse_text_call(text)
        if parsed:
            return PlannedCall(tool=parsed[0], args=parsed[1], planner=self.name, model=self.model, raw=text[:500], latency_ms=ms)
        raise PlannerError("The model did not choose an analysis tool.")

    def narrate(self, prompt: str) -> str:
        try:
            resp = self._generate(prompt, None, None)
        except Exception as exc:
            raise PlannerError(f"Gemini API request failed: {type(exc).__name__}") from exc
        return (getattr(resp, "text", "") or "").strip()


class OllamaPlanner:
    """Gemma 4 E2B (default gemma4:e2b) running locally through Ollama. No data leaves the machine."""

    name = "ollama"
    _availability: tuple[float, bool] = (0.0, False)

    def __init__(self, settings: Settings, transport: httpx.BaseTransport | None = None):
        self.settings = settings
        self.model = settings.ollama_model
        self._transport = transport

    def _client(self, timeout: float) -> httpx.Client:
        return httpx.Client(base_url=self.settings.ollama_url, timeout=timeout, transport=self._transport)

    def available(self) -> bool:
        checked_at, ok = OllamaPlanner._availability
        if time.time() - checked_at < 30 and self._transport is None:
            return ok
        try:
            with self._client(1.5) as c:
                tags = c.get("/api/tags").json().get("models", [])
            base = self.model.split(":")[0]
            ok = any(str(m.get("name", "")).startswith(base) for m in tags)
        except Exception:
            ok = False
        if self._transport is None:
            OllamaPlanner._availability = (time.time(), ok)
        return ok

    def _chat(self, messages: list[dict], tools: list[dict] | None) -> dict[str, Any]:
        payload: dict[str, Any] = {"model": self.model, "messages": messages, "stream": False, "options": {"temperature": 0}}
        if tools:
            payload["tools"] = [{"type": "function", "function": t} for t in tools]
        try:
            with self._client(self.settings.llm_timeout) as c:
                r = c.post("/api/chat", json=payload)
                r.raise_for_status()
                return r.json().get("message", {}) or {}
        except Exception as exc:
            raise PlannerError(f"Ollama request failed: {type(exc).__name__}") from exc

    def plan(self, question: str, ds: Dataset) -> PlannedCall:
        t0 = time.perf_counter()
        msg = self._chat([{"role": "system", "content": build_system_prompt(ds.profile)},
                          {"role": "user", "content": question}], build_tool_specs(ds.profile))
        ms = int((time.perf_counter() - t0) * 1000)
        for call in msg.get("tool_calls") or []:
            fn = call.get("function", {})
            args = fn.get("arguments", {})
            if isinstance(args, str):
                try:
                    args = json.loads(args)
                except json.JSONDecodeError:
                    continue
            if fn.get("name"):
                return PlannedCall(tool=fn["name"], args=args or {}, planner=self.name, model=self.model, latency_ms=ms)
        parsed = parse_text_call(msg.get("content", ""))
        if parsed:
            return PlannedCall(tool=parsed[0], args=parsed[1], planner=self.name, model=self.model,
                               raw=msg.get("content", "")[:500], latency_ms=ms)
        raise PlannerError("The model did not choose an analysis tool.")

    def narrate(self, prompt: str) -> str:
        return (self._chat([{"role": "user", "content": prompt}], None).get("content") or "").strip()
