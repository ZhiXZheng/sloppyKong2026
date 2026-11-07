"""Explicit, single-request live check; never executed by automated tests."""

import argparse
import json
import time

from schema import AIRescueRequest, EntityReference, EntityType, Observation, RescueTeamState
from .ai_cache import canonical_prompt
from .ai_client import ClaudeProvider, ModelDecision
from .beliefs import BeliefStore
from .runtime import Runtime


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Make one paid Claude request using .env API_KEY")
    parser.add_argument("--timeout", type=float, default=3.0,
                        help="Standalone diagnostic timeout (up to 30 s); controllers still use 3 s")
    args = parser.parse_args()
    if not args.live:
        parser.error("Pass --live to make the single paid request")
    if not 0 < args.timeout <= 30:
        parser.error("timeout must be between 0 and 30 seconds")
    runtime = Runtime("live-smoke")
    beliefs = BeliefStore("smoke-team")
    beliefs.observe(Observation(observer_id="smoke-team",
        entity=EntityReference(entity_type=EntityType.CIVILIAN_GROUP, entity_id="smoke-group"),
        position={"x": 1, "y": 0}, observed_status="available", details={"size": 1},
        observed_at=runtime.timestamp(0), observed_tick=0, entity_revision=0))
    state = RescueTeamState(team_id="smoke-team", position={"x": 0, "y": 0}, neighbourhood_id="west")
    request = AIRescueRequest(seed=42, beliefs=beliefs.snapshot(0), decision_context_version=1)
    provider = ClaudeProvider(max_requests=1)
    prompt = canonical_prompt(request, state, ["smoke-group"], provider.model, provider.max_tokens)
    started = time.monotonic()
    try:
        content = ModelDecision.model_validate_json(provider.decide(prompt, args.timeout))
        if content.recommended_target_id != "smoke-group":
            raise ValueError("Smoke check returned an ineligible target")
    except Exception as exc:
        # Only the adapter's sanitized error text is safe to display.
        message = str(exc) if isinstance(exc, RuntimeError) else "Response validation failed"
        print(json.dumps(dict(ok=False, error=message, requests=provider.calls,
                              usage=provider.usage, elapsed_seconds=round(time.monotonic() - started, 3))))
        return 1
    elapsed = time.monotonic() - started
    print(json.dumps(dict(ok=True, model=provider.model, target=content.recommended_target_id,
                          requests=provider.calls, usage=provider.usage,
                          within_deadline=elapsed < 3, elapsed_seconds=round(elapsed, 3))))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
