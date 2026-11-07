"""Export actual demo frames into a standalone, offline animated grid replay."""

import json
from pathlib import Path

from .console import event_text
from .demo import run_comparison


# Build replay frames from actual comparison outcomes rather than synthesizing rescue positions.
def replay_data(seed=42, ticks=30):
    runs = []
    for enabled in (True, False):
        result = run_comparison(enabled, seed, ticks)
        frames = [dict(tick=-1, radio_connected=True, rescued=0, total=result["total"],
                       world=result["initial_world"], team_views={}, events=[])]
        for record in result["tick_events"]:
            frames.append({key: record[key] for key in
                           ("tick", "radio_connected", "rescued", "total", "world", "team_views")} | {
                "events": [event_text(e) for e in record["events"]
                           if not (e["type"] == "message" and e["message_type"] == "world.observation")]})
        runs.append(dict(drone_on=enabled, rescued=result["rescued"], total=result["total"], frames=frames))
    return dict(seed=seed, runs=runs)


# Embed escaped replay JSON into the standalone HTML template and write the output artifact.
def create_replay(seed=42, ticks=30, output=None):
    if ticks < 1:
        raise ValueError("ticks must be positive")
    directory = Path(__file__).resolve().parent
    path = Path(output) if output else directory / "output" / "grid-demo.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = json.dumps(replay_data(seed, ticks), separators=(",", ":"), allow_nan=False)
    payload = payload.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")
    template = (directory / "grid_replay.html").read_text(encoding="utf-8")
    path.write_text(template.replace("__REPLAY_DATA__", payload), encoding="utf-8")
    return path.resolve()


if __name__ == "__main__":
    print(create_replay())
