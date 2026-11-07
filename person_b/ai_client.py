"""Bounded nonblocking requests; Claude HTTP adapter requires no extra SDK."""

import json
import os
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from threading import BoundedSemaphore, Lock
from typing import Protocol
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from pydantic import BaseModel, ConfigDict, Field
from schema import AIRescueRecommendation, ActionType
from .ai_cache import DecisionCache, SYSTEM_PROMPT


class ModelDecision(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    recommended_target_id: str | None
    explanation: str = Field(max_length=1000)
    missing_information: list[str] = Field(max_length=12)
    confidence: float = Field(ge=0, le=1)


class Provider(Protocol):
    model: str
    max_tokens: int

    def decide(self, prompt: str, timeout: float) -> str | dict: ...


def load_api_key(env_path=None):
    """Read only the named key; never log or interpolate credentials into commands."""
    key = os.environ.get("API_KEY") or os.environ.get("ANTHROPIC_API_KEY")
    if key:
        return key
    path = Path(env_path) if env_path else Path(__file__).resolve().parents[1] / ".env"
    if path.is_file():
        for line in path.read_text(encoding="utf-8-sig").splitlines():
            name, sep, value = line.strip().removeprefix("export ").partition("=")
            if sep and name.strip() in ("API_KEY", "ANTHROPIC_API_KEY"):
                value = value.strip()
                if value[:1] in ("'", '"'):
                    quote = value[0]
                    value = value[1:].split(quote, 1)[0]
                else:
                    value = value.split(" #", 1)[0].strip()
                if value:
                    return value
    raise ValueError("Set API_KEY in the repository .env or ANTHROPIC_API_KEY in the environment")


class ClaudeProvider:
    """One HTTP attempt per decision; fixed official endpoint, bounded output."""

    def __init__(self, api_key=None, model=None, max_tokens=256, max_requests=100,
                 max_prompt_chars=24000):
        if not 64 <= max_tokens <= 1024 or max_requests < 1:
            raise ValueError("invalid token or request limit")
        self._api_key = api_key or load_api_key()
        self.model = model or os.environ.get("FLOODNET_CLAUDE_MODEL", "claude-haiku-4-5-20251001")
        self.max_tokens = max_tokens
        self.max_requests = max_requests
        self.max_prompt_chars = max_prompt_chars
        self.calls = 0
        self.usage = {"input_tokens": 0, "output_tokens": 0}
        self._lock = Lock()

    def decide(self, prompt, timeout):
        # Keep provider schema simple; apply stricter bounds locally with Pydantic.
        output_schema = dict(type="object", additionalProperties=False,
            required=["recommended_target_id", "explanation", "missing_information", "confidence"],
            properties=dict(recommended_target_id={"type": ["string", "null"]},
                explanation={"type": "string"}, missing_information={"type": "array", "items": {"type": "string"}},
                confidence={"type": "number"}))
        return self.generate(prompt, timeout, output_schema, SYSTEM_PROMPT)

    def generate(self, prompt, timeout, output_schema, system):
        if len(prompt) > self.max_prompt_chars:
            raise ValueError("Local prompt exceeds configured input limit")
        with self._lock:
            if self.calls >= self.max_requests:
                raise RuntimeError("Claude request limit reached")
            self.calls += 1
        body = dict(model=self.model, max_tokens=self.max_tokens, temperature=0,
                    system=system, messages=[dict(role="user", content=prompt)],
                    output_config={"format": {"type": "json_schema", "schema": output_schema}})
        request = Request("https://api.anthropic.com/v1/messages",
            data=json.dumps(body).encode(), method="POST",
            headers={"x-api-key": self._api_key, "anthropic-version": "2023-06-01",
                     "content-type": "application/json"})
        try:
            # Controllers always pass <=3 s. The standalone smoke CLI may use
            # a longer diagnostic timeout for first-use schema compilation.
            with urlopen(request, timeout=min(timeout, 30.0)) as response:
                result = json.load(response)
        except HTTPError as exc:
            raise RuntimeError(f"Claude HTTP {exc.code}") from None
        except (URLError, TimeoutError, OSError):
            raise RuntimeError("Claude connection failed or timed out") from None
        with self._lock:
            for name in self.usage:
                self.usage[name] += result.get("usage", {}).get(name, 0)
        if result.get("stop_reason") != "end_turn":
            raise RuntimeError("Claude response incomplete or refused")
        return "".join(block["text"] for block in result.get("content", []) if block.get("type") == "text")


@dataclass
class Completed:
    content: ModelDecision | None
    finished_at: float
    reason: str


@dataclass
class Pending:
    request: object
    prompt: str
    deadline: float
    future: object


class AIService:
    """Share one instance across teams to bound total outstanding network work."""

    def __init__(self, provider, cache=None, max_workers=2, clock=time.monotonic):
        self.provider = provider
        self.cache = cache if cache is not None else DecisionCache()
        self.clock = clock
        self.pool = ThreadPoolExecutor(max_workers=max_workers, thread_name_prefix="floodnet-ai")
        self.slots = BoundedSemaphore(max_workers)
        self.pending = {}
        self.last_reason = {}
        self.closed = False

    def submit(self, request, prompt, now):
        team = request.beliefs.team_id
        if self.closed or team in self.pending or not self.slots.acquire(blocking=False):
            return False
        request = request.model_copy(deep=True)
        try:
            future = self.pool.submit(self._run, request, prompt)
        except RuntimeError:
            self.slots.release()
            return False
        future.add_done_callback(lambda _: self.slots.release())
        self.pending[team] = Pending(request, prompt, now + request.timeout_seconds, future)
        self.last_reason[team] = "AI pending"
        return True

    def _run(self, request, prompt):
        try:
            content = self.cache.get(request.seed, prompt)
            source = "AI cache" if content is not None else "AI reply"
            if content is None:
                content = self.provider.decide(prompt, request.timeout_seconds)
            parsed = (ModelDecision.model_validate_json(content) if isinstance(content, str)
                      else ModelDecision.model_validate(content))
            self.cache.put(request.seed, prompt, parsed.model_dump())
            return Completed(parsed, self.clock(), source)
        except Exception:
            # No provider bodies, prompts, headers or credentials in public errors.
            return Completed(None, self.clock(), "AI error or invalid JSON")

    def invalidate(self, team, reason="AI context changed"):
        pending = self.pending.pop(team, None)
        if pending:
            pending.future.cancel()
        self.last_reason[team] = reason

    def poll(self, team, context, belief_version, available, now, generated_at):
        pending = self.pending.get(team)
        if pending is None:
            return None
        request = pending.request
        if (not available or context != request.decision_context_version or
                belief_version != request.beliefs.belief_version):
            self.invalidate(team, "AI stale context")
            return None
        if not pending.future.done():
            if now >= pending.deadline:
                self.invalidate(team, "AI timeout; rules")
            return None
        completed = pending.future.result()  # already done: never blocks
        del self.pending[team]
        self.last_reason[team] = completed.reason
        if completed.finished_at >= pending.deadline:
            self.last_reason[team] = "AI timeout; rules"
            return None
        if completed.content is None:
            return None
        content = completed.content
        return AIRescueRecommendation(team_id=team, request_id=request.request_id,
            decision_context_version=context, based_on_belief_version=belief_version,
            recommended_target_id=content.recommended_target_id,
            recommended_action=ActionType.MOVE if content.recommended_target_id else ActionType.WAIT,
            explanation=content.explanation, missing_information=content.missing_information,
            confidence=content.confidence, generated_at=generated_at)

    def close(self, wait=False):
        self.closed = True
        for team in list(self.pending):
            self.invalidate(team, "AI service closed")
        self.pool.shutdown(wait=wait, cancel_futures=True)
