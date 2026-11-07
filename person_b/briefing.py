"""On-demand team-local briefings; never feed summaries back into belief stores."""

import json
from concurrent.futures import ThreadPoolExecutor

from pydantic import BaseModel, ConfigDict, Field
from schema import EntityType, SituationBrief


# Validate optional AI summary text separately from operational rescue decisions.
class BriefContent(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)
    summary: str = Field(min_length=1, max_length=2000)
    warnings: list[str]


# Summarize only the supplied snapshot and explicitly report stale or missing information.
def local_brief(snapshot, timestamp, stale_after=5):
    stale = [f"{o.entity.entity_id}: {snapshot.world_tick - o.observed_tick} ticks old"
             for o in snapshot.observations if snapshot.world_tick - o.observed_tick > stale_after]
    civilians = [o for o in snapshot.observations if o.entity.entity_type == EntityType.CIVILIAN_GROUP]
    unknown = [f"{o.entity.entity_id}: size or location unknown" for o in civilians
               if o.position is None or "size" not in o.details]
    return SituationBrief(generated_for_tick=snapshot.world_tick,
        summary=f"{snapshot.team_id} local view: {len(civilians)} known civilian groups; "
                f"{len(stale)} stale observations. Information outside this view is unknown.",
        warnings=["Team-local briefing; not global world truth"],
        stale_information=stale, unknown_information=unknown,
        generated_at=timestamp(snapshot.world_tick))


class BriefingService:
    """One optional background summary at a time, with a rules-based fallback."""

    # Allow one optional background briefing without changing the belief store.
    def __init__(self, provider=None):
        self.provider = provider
        self.pool = ThreadPoolExecutor(max_workers=1, thread_name_prefix="floodnet-brief")
        self.future = None

    # Copy the snapshot and prepare a deterministic fallback before optional model summarization.
    def submit(self, snapshot, timestamp, ai_available=False):
        if self.future is not None and not self.future.done():
            return False
        snapshot = snapshot.model_copy(deep=True)
        fallback = local_brief(snapshot, timestamp)
        self.future = self.pool.submit(self._build, fallback, snapshot, ai_available)
        return True

    # Use AI only when available; retain the local summary on any provider or validation failure.
    def _build(self, fallback, snapshot, available):
        if not self.provider or not available:
            return fallback
        schema = {"type": "object", "additionalProperties": False,
                  "properties": {"summary": {"type": "string"}, "warnings": {
                      "type": "array", "items": {"type": "string"}}},
                  "required": ["summary", "warnings"]}
        try:
            # Remove random IDs and wall timestamps from the optional model input.
            view = [{"entity": o.entity.model_dump(mode="json"), "status": o.observed_status,
                     "age_ticks": snapshot.world_tick - o.observed_tick} for o in snapshot.observations]
            raw = self.provider.generate(json.dumps(view), 3.0, schema,
                "Summarize only this team's local observations. Highlight uncertainty. "
                "Do not invent facts or issue actions. Keep the summary to two sentences.")
            content = BriefContent.model_validate_json(raw)
            return fallback.model_copy(update={"summary": content.summary,
                                               "warnings": fallback.warnings + content.warnings})
        except Exception:
            return fallback

    # Return a finished briefing without blocking a simulation tick.
    def poll(self):
        if self.future is None or not self.future.done():
            return None
        result, self.future = self.future.result(), None
        return result

    # Shut down the optional summary worker without waiting on network completion.
    def close(self):
        self.pool.shutdown(wait=False, cancel_futures=True)
