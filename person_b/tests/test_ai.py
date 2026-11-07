import json
import tempfile
import unittest
from pathlib import Path
from threading import Event
from unittest.mock import patch

from schema import AIRescueRequest, ActionResult, EntityType
from person_b.ai_cache import DecisionCache, canonical_prompt
from person_b.ai_client import AIService, ClaudeProvider, ModelDecision, load_api_key
from person_b.briefing import BriefingService, local_brief
from person_b.controller import AISettings, RescueController
from person_b.runtime import Runtime
from person_b.tests.helpers import FakeProvider, observation, state


class AIServiceTests(unittest.TestCase):
    def setUp(self):
        self.services = []

    def tearDown(self):
        for service in self.services:
            service.close(wait=True)
            service.cache.close()

    def service(self, provider=None, **kwargs):
        service = AIService(provider or FakeProvider(), **kwargs)
        self.services.append(service)
        return service

    def request(self, request_id=None, context=1):
        c = RescueController("a")
        c.observe([observation()])
        return AIRescueRequest(request_id=request_id or Runtime().new_id("request"), seed=42,
            beliefs=c.beliefs.snapshot(0), decision_context_version=context,
            requested_at=Runtime().timestamp(0))

    def finish(self, service, team="a"):
        # Test-only wait for a deterministic fake provider; production only polls.
        service.pending[team].future.result(timeout=2)

    def poll(self, service, request, now=0):
        return service.poll("a", request.decision_context_version, request.beliefs.belief_version,
                            True, now, Runtime().timestamp(0))

    def test_reply_metadata_and_cache_rebound(self):
        provider = FakeProvider()
        service = self.service(provider, clock=lambda: 0)
        first = self.request()
        service.submit(first, "canonical", 0)
        self.finish(service)
        reply = self.poll(service, first)
        self.assertEqual(reply.request_id, first.request_id)
        second = self.request(request_id=Runtime("second").new_id("request"), context=2)
        service.submit(second, "canonical", 0)
        self.finish(service)
        reply = self.poll(service, second)
        self.assertEqual(reply.request_id, second.request_id)
        self.assertEqual(reply.decision_context_version, 2)
        self.assertEqual(provider.calls, 1)

    def test_malformed_or_failed_provider_falls_back(self):
        for raw in ("not json", '{"recommended_target_id":"g"}',
                    dict(recommended_target_id="g", explanation="x", missing_information=[], confidence=2)):
            with self.subTest(raw=raw):
                service = self.service(FakeProvider(response=raw), clock=lambda: 0)
                request = self.request()
                service.submit(request, "prompt", 0)
                self.finish(service)
                self.assertIsNone(self.poll(service, request))
                self.assertIn("error", service.last_reason["a"])

    def test_timeout_does_not_block_and_work_stays_bounded(self):
        entered, release = Event(), Event()
        class Slow(FakeProvider):
            def decide(self, prompt, timeout):
                entered.set()
                release.wait(2)
                return super().decide(prompt, timeout)
        clock = [0]
        service = self.service(Slow(), max_workers=1, clock=lambda: clock[0])
        request = self.request()
        try:
            self.assertTrue(service.submit(request, "prompt", 0))
            self.assertTrue(entered.wait(1))
            clock[0] = 4
            self.assertIsNone(self.poll(service, request, now=4))
            self.assertNotIn("a", service.pending)
            self.assertFalse(service.submit(request, "another", 4))
        finally:
            release.set()

    def test_late_completed_reply_rejected_even_when_future_done(self):
        service = self.service(clock=lambda: 4)
        request = self.request()
        service.submit(request, "prompt", 0)
        self.finish(service)
        self.assertIsNone(self.poll(service, request, now=4))

    def test_changed_belief_context_or_connectivity_rejects_reply(self):
        for context, version, available in ((2, 2, True), (1, 99, True), (1, 2, False)):
            service = self.service(clock=lambda: 0)
            service.submit(self.request(), "prompt", 0)
            self.finish(service)
            self.assertIsNone(service.poll("a", context, version, available, 0, Runtime().timestamp(0)))

    def test_prompt_stability_and_no_hidden_entities(self):
        a, b = self.request(), self.request(context=5)
        a.current_target_id = b.current_target_id = "g"
        prompt_a = canonical_prompt(a, state(), ["g"], "fake", 256)
        prompt_b = canonical_prompt(b, state(), ["g"], "fake", 256)
        self.assertEqual(prompt_a, prompt_b)
        payload = json.loads(prompt_a)
        self.assertEqual([o["entity"]["entity_id"] for o in payload["observations"]], ["g"])
        self.assertNotIn("request_id", prompt_a)
        self.assertNotIn("observed_at", prompt_a)

    def test_controller_no_calls_while_disabled_or_isolated(self):
        for enabled, connected in ((False, True), (True, False)):
            provider = FakeProvider()
            service = self.service(provider)
            controller = RescueController("a", ai_service=service, settings=AISettings(enabled))
            controller.observe([observation()])
            decision = controller.step(state(), connected, 0, 0)
            self.assertFalse(decision.ui["ai_pending"])
            self.assertEqual(provider.calls, 0)

    def test_controller_rejects_ineligible_model_target(self):
        for target in ("unknown", "terminal", "oversized", "other-claimed"):
            with self.subTest(target=target):
                service = self.service(FakeProvider(target), clock=lambda: 0)
                c = RescueController("a", ai_service=service)
                c.observe([observation(), observation("terminal", status="rescued"),
                           observation("oversized", details={"size": 10}),
                           observation("other-claimed", status="claimed")])
                decision = c.step(state(), True, 0, 0)
                self.finish(service)
                c.apply_result(ActionResult(action_id=decision.action.action_id, team_id="a",
                                            status="completed", applied_at_tick=0))
                decision = c.step(state(x=1), True, 1, 0)
                self.assertEqual(c.target, "g")
                self.assertIn("rejected", decision.action.explanation)

    def test_controller_disconnect_reconnect_invalidates_reply(self):
        service = self.service(clock=lambda: 0)
        c = RescueController("a", ai_service=service)
        c.observe([observation()])
        c.step(state(), True, 0, 0)
        self.finish(service)
        context = c.context_version
        c.step(state(), False, 1, 0)
        self.assertNotIn("a", service.pending)
        self.assertGreater(c.context_version, context)
        c.step(state(), True, 2, 0)
        self.assertNotIn("a", service.pending)  # action still awaiting its result

    def test_ai_can_change_target_and_release_previous_claim(self):
        service = self.service(FakeProvider("far"), clock=lambda: 0)
        c = RescueController("a", ai_service=service)
        c.observe([observation(), observation("far", x=3)])
        first = c.step(state(), True, 0, 0)
        self.finish(service)
        c.apply_result(ActionResult(action_id=first.action.action_id, team_id="a",
                                   status="completed", applied_at_tick=0))
        decision = c.step(state(x=1), True, 1, 0)
        self.assertEqual(c.target, "far")
        self.assertIsNone(c.beliefs.own_active_claim("g"))
        self.assertIsNotNone(c.beliefs.own_active_claim("far"))
        self.assertTrue(decision.action.explanation.startswith("AI:"))

    def test_provider_exception_is_sanitized(self):
        class Broken(FakeProvider):
            def decide(self, prompt, timeout):
                raise RuntimeError("secret-api-key")
        service = self.service(Broken(), clock=lambda: 0)
        request = self.request()
        service.submit(request, "prompt", 0)
        self.finish(service)
        self.assertIsNone(self.poll(service, request))
        self.assertNotIn("secret", service.last_reason["a"])

    def test_global_switch_invalidates_finished_cached_result(self):
        service = self.service(clock=lambda: 0)
        settings = AISettings(True)
        c = RescueController("a", ai_service=service, settings=settings)
        c.observe([observation()])
        first = c.step(state(), True, 0, 0)
        self.finish(service)
        settings.enabled = False
        c.apply_result(ActionResult(action_id=first.action.action_id, team_id="a",
                                   status="completed", applied_at_tick=0))
        decision = c.step(state(x=1), True, 1, 0)
        self.assertFalse(decision.ui["ai_available"])
        self.assertFalse(decision.ui["ai_pending"])
        self.assertIn("AI off", decision.action.explanation)

    def test_deadline_polled_while_world_action_outstanding(self):
        service = self.service(clock=lambda: 4)
        c = RescueController("a", ai_service=service)
        c.observe([observation()])
        c.step(state(), True, 0, 0)
        self.finish(service)
        decision = c.step(state(), True, 1, 4)
        self.assertFalse(decision.ui["ai_pending"])
        self.assertEqual(decision.action.action_type.value, "wait")
        self.assertIn("timeout", decision.ui["ai_status"])

    def test_no_request_storm_without_new_events(self):
        service = self.service(clock=lambda: 0)
        c = RescueController("a", ai_service=service)
        c.observe([observation(x=10)])
        for tick in range(5):
            decision = c.step(state(x=tick), True, tick, 0)
            if "a" in service.pending:
                self.finish(service)
            c.apply_result(ActionResult(action_id=decision.action.action_id, team_id="a",
                                        status="completed", applied_at_tick=tick))
        self.assertEqual(service.provider.calls, 1)


class AdapterTests(unittest.TestCase):
    def test_cache_persistence_bounds_and_seed_separation(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "decisions.sqlite3"
            cache = DecisionCache(path, max_entries=1)
            cache.put(1, "a", {"value": 1})
            cache.put(1, "b", {"value": 2})
            self.assertIsNone(cache.get(1, "a"))
            self.assertIsNone(cache.get(2, "b"))
            cache.close()
            cache = DecisionCache(path)
            self.assertEqual(cache.get(1, "b"), {"value": 2})
            cache.close()

    def test_key_load_is_explicit_and_not_logged(self):
        with tempfile.TemporaryDirectory() as directory, patch.dict("os.environ", {}, clear=True):
            path = Path(directory) / ".env"
            path.write_text('API_KEY="test-secret" # comment\nOTHER=ignore\n')
            self.assertEqual(load_api_key(path), "test-secret")

    def test_http_request_contract_and_usage(self):
        class Response:
            def __enter__(self):
                return self
            def __exit__(self, *args):
                pass
            def read(self):
                return json.dumps(dict(stop_reason="end_turn", content=[dict(type="text", text=json.dumps(
                    FakeProvider().decide("", 3)))], usage=dict(input_tokens=10, output_tokens=20))).encode()
        provider = ClaudeProvider(api_key="test-secret", max_requests=1)
        with patch("person_b.ai_client.urlopen", return_value=Response()) as http:
            parsed = ModelDecision.model_validate_json(provider.decide("local only", 3))
            request = http.call_args.args[0]
            self.assertEqual(request.full_url, "https://api.anthropic.com/v1/messages")
            self.assertEqual(json.loads(request.data)["output_config"]["format"]["type"], "json_schema")
            self.assertEqual(parsed.recommended_target_id, "g")
            self.assertEqual(provider.usage["output_tokens"], 20)
            with self.assertRaises(RuntimeError):
                provider.decide("again", 3)
            self.assertEqual(http.call_count, 1)

    def test_local_and_background_briefing(self):
        c = RescueController("a")
        c.observe([observation(details={})])
        snapshot = c.beliefs.snapshot(9)
        brief = local_brief(snapshot, Runtime().timestamp)
        self.assertEqual(len(brief.stale_information), 1)
        self.assertEqual(len(brief.unknown_information), 1)
        service = BriefingService()
        try:
            self.assertTrue(service.submit(snapshot, Runtime().timestamp))
            service.future.result(timeout=1)
            self.assertEqual(service.poll(), brief)
        finally:
            service.close()

    def test_ai_brief_keeps_provenance_warnings_and_staleness(self):
        class BriefProvider:
            def generate(self, prompt, timeout, schema, system):
                return json.dumps({"summary": "One group reported; information is stale.", "warnings": ["Check radio"]})
        c = RescueController("a")
        c.observe([observation()])
        snapshot = c.beliefs.snapshot(9)
        service = BriefingService(BriefProvider())
        try:
            service.submit(snapshot, Runtime().timestamp, ai_available=True)
            service.future.result(timeout=1)
            brief = service.poll()
            self.assertIn("stale", brief.summary)
            self.assertEqual(len(brief.stale_information), 1)
            self.assertIn("Team-local briefing; not global world truth", brief.warnings)
            self.assertEqual(c.beliefs.snapshot(9), snapshot)
        finally:
            service.close()

    def test_input_limit_prevents_paid_call(self):
        provider = ClaudeProvider(api_key="test-key", max_prompt_chars=3)
        with patch("person_b.ai_client.urlopen") as http, self.assertRaises(ValueError):
            provider.decide("too long", 3)
        self.assertEqual(provider.calls, 0)
        http.assert_not_called()


if __name__ == "__main__":
    unittest.main()
