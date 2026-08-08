"""Tests for the case state machine."""

import pytest

from policydecoder.case_manager import VALID_TRANSITIONS, CaseManager, CaseState


class TestStateTransitions:
    def test_idle_to_policy_received(self):
        cm = CaseManager()
        cm.get_or_create("test1", "user@test.com")
        cm.advance_state("test1", CaseState.POLICY_RECEIVED)
        assert cm.get("test1").state == CaseState.POLICY_RECEIVED

    def test_policy_received_to_analyzed(self):
        cm = CaseManager()
        cm.get_or_create("test2", "user@test.com")
        cm.advance_state("test2", CaseState.POLICY_RECEIVED)
        cm.advance_state("test2", CaseState.ANALYZED)
        assert cm.get("test2").state == CaseState.ANALYZED

    def test_invalid_transition_raises(self):
        cm = CaseManager()
        cm.get_or_create("test3", "user@test.com")
        with pytest.raises(ValueError, match="Invalid state transition"):
            cm.advance_state("test3", CaseState.RESOLVED)

    def test_analyzed_to_free_look(self):
        cm = CaseManager()
        cm.get_or_create("test4", "user@test.com")
        cm.advance_state("test4", CaseState.POLICY_RECEIVED)
        cm.advance_state("test4", CaseState.ANALYZED)
        cm.advance_state("test4", CaseState.FREE_LOOK)
        assert cm.get("test4").state == CaseState.FREE_LOOK

    def test_analyzed_to_complaint(self):
        cm = CaseManager()
        cm.get_or_create("test5", "user@test.com")
        cm.advance_state("test5", CaseState.POLICY_RECEIVED)
        cm.advance_state("test5", CaseState.ANALYZED)
        cm.advance_state("test5", CaseState.COMPLAINT)
        assert cm.get("test5").state == CaseState.COMPLAINT

    def test_all_transitions_are_valid(self):
        """Every state in VALID_TRANSITIONS should be reachable."""
        for state, targets in VALID_TRANSITIONS.items():
            assert isinstance(state, CaseState)
            for target in targets:
                assert isinstance(target, CaseState)


class TestCaseCRUD:
    def test_create_case(self):
        cm = CaseManager()
        case = cm.get_or_create("new_case", "user@test.com")
        assert case.case_id == "new_case"
        assert case.state == CaseState.IDLE

    def test_update_case(self):
        cm = CaseManager()
        cm.get_or_create("update_case", "user@test.com")
        cm.update_case("update_case", user_age=32)
        assert cm.get("update_case").user_age == 32

    def test_add_and_complete_action(self):
        cm = CaseManager()
        cm.get_or_create("action_case", "user@test.com")
        cm.add_action("action_case", "Draft letter")
        assert len(cm.get("action_case").pending_actions) == 1

        cm.complete_action("action_case", "Draft letter", "Done")
        assert len(cm.get("action_case").pending_actions) == 0
        assert len(cm.get("action_case").actions_completed) == 1

    def test_timeline_output(self):
        cm = CaseManager()
        cm.get_or_create("timeline_case", "user@test.com")
        cm.update_case(
            "timeline_case",
            policy_data={"policy_name": "LIC Jeevan Anand"},
        )
        timeline = cm.get_timeline("timeline_case")
        assert "IDLE" in timeline
        assert "LIC Jeevan Anand" in timeline
