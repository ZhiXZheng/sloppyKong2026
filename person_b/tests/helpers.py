# Deterministic protocol fixtures and a fake model adapter; these helpers never make paid API calls.
from schema import EntityReference, EntityType, Observation, RescueTeamState
from person_b.runtime import Runtime


def observation(group="g", tick=0, revision=0, x=1, y=0, kind=EntityType.CIVILIAN_GROUP,
                status="available", details=None, observer="sensor"):
    runtime = Runtime(f"fixture/{group}/{tick}/{revision}/{observer}")
    return Observation(observation_id=runtime.new_id("observation"), observer_id=observer,
        entity=EntityReference(entity_type=kind, entity_id=group),
        position={"x": x, "y": y}, observed_status=status,
        observed_tick=tick, entity_revision=revision, observed_at=runtime.timestamp(tick),
        details={"size": 1} if details is None else details)


def state(team="a", x=0, y=0, **kwargs):
    return RescueTeamState(team_id=team, position={"x": x, "y": y}, capacity=3,
                           neighbourhood_id="west", **kwargs)


class FakeProvider:
    model = "fake"
    max_tokens = 256

    def __init__(self, target="g", response=None):
        self.target = target
        self.response = response
        self.calls = 0
        self.prompts = []

    def decide(self, prompt, timeout):
        self.calls += 1
        self.prompts.append(prompt)
        return self.response if self.response is not None else {
            "recommended_target_id": self.target, "explanation": "Closest locally known group",
            "missing_information": [], "confidence": 0.8}
