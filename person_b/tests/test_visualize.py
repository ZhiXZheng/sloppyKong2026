# Regress replay exports against actual fixture movement and rescued-person counts.
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

from person_b.demo import courier_state, run_comparison
from person_b.visualize import create_replay, replay_data


class ReplayTests(unittest.TestCase):
    def test_world_frames_track_load_and_delivered_people(self):
        result = run_comparison()
        self.assertEqual(len(result["tick_events"]), 30)
        self.assertEqual(result["initial_world"]["rescue_teams"][0]["position"], {"x": 0, "y": 0})
        for frame in result["tick_events"]:
            world = frame["world"]
            delivered = sum(g["size"] for g in world["civilian_groups"] if g["status"] == "delivered")
            self.assertEqual(delivered, frame["rescued"])
            for group in world["civilian_groups"]:
                if group["status"] == "picked_up":
                    team = next(t for t in world["rescue_teams"] if t["team_id"] == group["picked_up_by_team_id"])
                    self.assertIn(group["group_id"], team["carried_group_ids"])

    def test_courier_moves_one_cell_per_tick_and_arrives_at_delivery(self):
        self.assertEqual(courier_state(1, True).position.model_dump(), {"x": 4, "y": 4})
        for tick in range(2, 10):
            previous, current = courier_state(tick - 1, True), courier_state(tick, True)
            self.assertEqual(abs(current.position.x - previous.position.x) +
                             abs(current.position.y - previous.position.y), 1)
        self.assertEqual(courier_state(9, True).position.model_dump(), {"x": 0, "y": 0})
        self.assertFalse(courier_state(9, False).enabled)

    def test_replay_uses_same_actual_results_for_both_runs(self):
        data = replay_data()
        self.assertEqual([r["rescued"] for r in data["runs"]], [3, 2])
        self.assertTrue(all(len(run["frames"]) == 31 for run in data["runs"]))
        self.assertEqual(data["runs"][0]["frames"][0]["tick"], -1)
        self.assertTrue(any("Delivered 1 observation" in event
                            for event in data["runs"][0]["frames"][10]["events"]))

    def test_export_and_playback_controls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = create_replay(output=Path(directory) / "replay.html")
            html = path.read_text(encoding="utf-8")
            self.assertNotIn("__REPLAY_DATA__", html)
            self.assertNotIn("api.anthropic.com", html)
            self.assertIn('id="grid"', html)
            node = shutil.which("node")
            if node:
                result = subprocess.run([node, str(Path(__file__).with_name("check_replay.cjs")), str(path)],
                                        capture_output=True, text=True, timeout=10)
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)


if __name__ == "__main__":
    unittest.main()
