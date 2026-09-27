from __future__ import annotations

import unittest

from opspilot.core import OpsPilotError, fail, new_state, next_action, rollback, transition


class CoreTests(unittest.TestCase):
    def test_happy_path(self):
        state = new_state(
            project_id="devcontrol",
            release="v1.2.3",
            revision="abc",
            last_known_good="v1.2.2",
        )
        transition(state, "validate")
        transition(state, "deploy-staging")
        transition(state, "smoke")
        transition(state, "candidate")
        transition(state, "deploy-canary", confirmation="canary:v1.2.3")
        transition(state, "canary-health")
        transition(state, "promote", confirmation="production:v1.2.3")
        transition(state, "stabilize")
        self.assertEqual(state["state"], "STABLE")
        self.assertIsNone(next_action(state))

    def test_out_of_order_transition_fails_closed(self):
        state = new_state(project_id="x", release="v1")
        with self.assertRaisesRegex(OpsPilotError, "requires state VALIDATED"):
            transition(state, "deploy-staging")
        self.assertEqual(state["state"], "PLANNED")

    def test_canary_and_production_are_release_bound(self):
        state = new_state(project_id="x", release="v2", last_known_good="v1")
        transition(state, "validate")
        transition(state, "deploy-staging")
        transition(state, "smoke")
        transition(state, "candidate")
        with self.assertRaisesRegex(OpsPilotError, "canary:v2"):
            transition(state, "deploy-canary")
        transition(state, "deploy-canary", confirmation="canary:v2")
        transition(state, "canary-health")
        with self.assertRaisesRegex(OpsPilotError, "production:v2"):
            transition(state, "promote", confirmation="production:wrong")

    def test_failure_and_rollback_are_audited(self):
        state = new_state(project_id="x", release="v2", last_known_good="v1")
        transition(state, "validate")
        fail(state, "deploy-staging", {"reason": "probe_failed"})
        self.assertEqual(state["state"], "FAILED")
        with self.assertRaisesRegex(OpsPilotError, "rollback:v1"):
            rollback(state, confirmation="rollback:wrong")
        rollback(state, confirmation="rollback:v1")
        self.assertEqual(state["state"], "ROLLED_BACK")
        self.assertEqual(state["rollback_release"], "v1")
        self.assertEqual(state["history"][-1]["action"], "rollback")

    def test_environment_is_part_of_state_identity(self):
        state = new_state(project_id="x", release="v1", environment="staging")
        self.assertEqual(state["environment"], "staging")


if __name__ == "__main__":
    unittest.main()
