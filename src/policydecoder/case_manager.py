"""Case state machine and in-memory storage.

Channel-agnostic. This module has zero awareness of email vs Telegram.
"""

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from enum import Enum
from typing import Any


class CaseState(Enum):
    IDLE = "IDLE"
    POLICY_RECEIVED = "POLICY_RECEIVED"
    ANALYZED = "ANALYZED"
    FREE_LOOK = "FREE_LOOK"
    CANCELLATION_DRAFTED = "CANCELLATION_DRAFTED"
    COMPLAINT = "COMPLAINT"
    COMPLAINT_SENT = "COMPLAINT_SENT"
    ESCALATION = "ESCALATION"
    OMBUDSMAN_DRAFTED = "OMBUDSMAN_DRAFTED"
    RESOLVED = "RESOLVED"


VALID_TRANSITIONS: dict[CaseState, set[CaseState]] = {
    CaseState.IDLE: {CaseState.POLICY_RECEIVED},
    CaseState.POLICY_RECEIVED: {CaseState.ANALYZED},
    CaseState.ANALYZED: {
        CaseState.FREE_LOOK,
        CaseState.COMPLAINT,
        CaseState.RESOLVED,
    },
    CaseState.FREE_LOOK: {CaseState.CANCELLATION_DRAFTED},
    CaseState.CANCELLATION_DRAFTED: {CaseState.RESOLVED},
    CaseState.COMPLAINT: {CaseState.COMPLAINT_SENT},
    CaseState.COMPLAINT_SENT: {CaseState.ESCALATION, CaseState.RESOLVED},
    CaseState.ESCALATION: {CaseState.OMBUDSMAN_DRAFTED},
    CaseState.OMBUDSMAN_DRAFTED: {CaseState.RESOLVED},
    CaseState.RESOLVED: set(),
}


@dataclass
class CaseAction:
    action: str
    timestamp: str
    result: str = ""
    deadline: str | None = None


@dataclass
class Case:
    case_id: str
    user_contact: str
    state: CaseState = CaseState.IDLE
    timestamp_started: str = field(
        default_factory=lambda: datetime.now(UTC).isoformat()
    )
    policy_data: dict = field(default_factory=dict)
    calculation_results: dict = field(default_factory=dict)
    analysis_result: dict = field(default_factory=dict)
    user_age: int | None = None
    actions_completed: list[CaseAction] = field(default_factory=list)
    pending_actions: list[CaseAction] = field(default_factory=list)
    message_count: int = 0


class CaseManager:
    """In-memory case store keyed on conversation_id."""

    def __init__(self):
        self._cases: dict[str, Case] = {}
        self._store = None

    def attach_store(self, store) -> None:
        self._store = store

    def load_all_from(self, store) -> None:
        for case in store.load_all():
            self._cases[case.case_id] = case
        self._store = store
        _log_action("system", "STORE_LOAD", f"{len(self._cases)} cases loaded")

    def _persist(self, case_id: str) -> None:
        if self._store is not None:
            case = self._cases.get(case_id)
            if case:
                try:
                    self._store.save(case)
                except Exception as e:
                    print(f"[CASE_MANAGER] Persist failed for {case_id}: {e}")

    def get(self, case_id: str) -> Case | None:
        return self._cases.get(case_id)

    def get_or_create(self, case_id: str, user_contact: str) -> Case:
        if case_id not in self._cases:
            self._cases[case_id] = Case(
                case_id=case_id,
                user_contact=user_contact,
            )
            self._persist(case_id)
        return self._cases[case_id]

    def advance_state(self, case_id: str, new_state: CaseState) -> Case:
        case = self._cases[case_id]
        if new_state not in VALID_TRANSITIONS.get(case.state, set()):
            raise ValueError(
                f"Invalid state transition: {case.state.value} → {new_state.value}"
            )
        old_state = case.state.value
        case.state = new_state
        self._persist(case_id)
        _log_action(case_id, "STATE_CHANGE", f"{old_state} → {new_state.value}")
        return case

    def update_case(self, case_id: str, **fields: Any) -> Case:
        case = self._cases[case_id]
        for key, value in fields.items():
            if hasattr(case, key):
                setattr(case, key, value)
        case.message_count += 1
        self._persist(case_id)
        _log_action(case_id, "CASE_UPDATE", str(fields))
        return case

    def add_action(self, case_id: str, action: str, deadline: str | None = None) -> None:
        case = self._cases[case_id]
        ts = datetime.now(UTC).isoformat()
        case.pending_actions.append(
            CaseAction(action=action, timestamp=ts, deadline=deadline)
        )
        self._persist(case_id)

    def complete_action(self, case_id: str, action_name: str, result: str = "") -> None:
        case = self._cases[case_id]
        for pending in list(case.pending_actions):
            if pending.action == action_name:
                case.pending_actions.remove(pending)
                pending.result = result
                case.actions_completed.append(pending)
                self._persist(case_id)
                _log_action(case_id, "ACTION_COMPLETED", f"{action_name}: {result}")
                return

    def get_timeline(self, case_id: str) -> str:
        case = self._cases[case_id]
        lines = [f"Case status: {case.state.value}"]
        lines.append(f"Started: {case.timestamp_started[:19]}")

        if case.policy_data.get("policy_name"):
            lines.append(f"Policy: {case.policy_data['policy_name']}")

        if case.calculation_results.get("xirr"):
            xirr_pct = case.calculation_results["xirr"] * 100
            lines.append(f"Policy XIRR: {xirr_pct:.1f}%")

        if case.analysis_result.get("is_likely_missold") is not None:
            verdict = "Yes" if case.analysis_result["is_likely_missold"] else "No"
            lines.append(f"Likely mis-sold: {verdict}")

        if case.actions_completed:
            lines.append("")
            lines.append("Completed:")
            for a in case.actions_completed:
                lines.append(f"  [done] {a.action}")

        if case.pending_actions:
            lines.append("")
            lines.append("Pending:")
            for a in case.pending_actions:
                lines.append(f"  [pending] {a.action}")

        return "\n".join(lines)

    def get_summary_for_llm(self, case_id: str) -> str:
        case = self._cases[case_id]
        return json.dumps(
            {
                "state": case.state.value,
                "policy": case.policy_data.get("policy_name"),
                "missold": case.analysis_result.get("is_likely_missold"),
                "completed": [a.action for a in case.actions_completed],
                "pending": [a.action for a in case.pending_actions],
            },
            ensure_ascii=False,
        )


case_manager = CaseManager()


def _log_action(case_id: str, action: str, detail: str) -> None:
    ts = datetime.now(UTC).isoformat()[:26]
    print(f"[{ts}] CASE:{case_id[:12]} ACTION:{action} {detail}")
