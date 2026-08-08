"""SQLite persistence for cases."""

import json
import sqlite3
from pathlib import Path

from policydecoder.case_manager import Case, CaseAction, CaseState


class Persistence:
    def __init__(self, db_path: str | None = None):
        self.db_path = db_path or str(Path(__file__).resolve().parent / "policydecoder.db")
        self._conn = sqlite3.connect(self.db_path)
        self._conn.row_factory = sqlite3.Row
        self._init_schema()

    def _init_schema(self) -> None:
        self._conn.execute(
            """
            CREATE TABLE IF NOT EXISTS cases (
                case_id TEXT PRIMARY KEY,
                user_contact TEXT NOT NULL,
                state TEXT NOT NULL,
                timestamp_started TEXT NOT NULL,
                policy_data TEXT NOT NULL DEFAULT '{}',
                calculation_results TEXT NOT NULL DEFAULT '{}',
                analysis_result TEXT NOT NULL DEFAULT '{}',
                user_age INTEGER,
                actions_completed TEXT NOT NULL DEFAULT '[]',
                pending_actions TEXT NOT NULL DEFAULT '[]',
                message_count INTEGER NOT NULL DEFAULT 0
            )
            """
        )
        self._conn.commit()

    def save(self, case: Case) -> None:
        self._conn.execute(
            """
            INSERT INTO cases (
                case_id, user_contact, state, timestamp_started,
                policy_data, calculation_results, analysis_result,
                user_age, actions_completed, pending_actions, message_count
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(case_id) DO UPDATE SET
                user_contact=excluded.user_contact,
                state=excluded.state,
                timestamp_started=excluded.timestamp_started,
                policy_data=excluded.policy_data,
                calculation_results=excluded.calculation_results,
                analysis_result=excluded.analysis_result,
                user_age=excluded.user_age,
                actions_completed=excluded.actions_completed,
                pending_actions=excluded.pending_actions,
                message_count=excluded.message_count
            """,
            (
                case.case_id,
                case.user_contact,
                case.state.value,
                case.timestamp_started,
                json.dumps(case.policy_data),
                json.dumps(case.calculation_results),
                json.dumps(case.analysis_result),
                case.user_age,
                json.dumps([a.__dict__ for a in case.actions_completed]),
                json.dumps([a.__dict__ for a in case.pending_actions]),
                case.message_count,
            ),
        )
        self._conn.commit()

    def load(self, case_id: str) -> Case | None:
        row = self._conn.execute("SELECT * FROM cases WHERE case_id = ?", (case_id,)).fetchone()
        return self._row_to_case(row) if row else None

    def load_all(self) -> list[Case]:
        rows = self._conn.execute("SELECT * FROM cases").fetchall()
        return [self._row_to_case(r) for r in rows]

    def close(self) -> None:
        self._conn.close()

    @staticmethod
    def _row_to_case(row: sqlite3.Row) -> Case:
        return Case(
            case_id=row["case_id"],
            user_contact=row["user_contact"],
            state=CaseState(row["state"]),
            timestamp_started=row["timestamp_started"],
            policy_data=json.loads(row["policy_data"] or "{}"),
            calculation_results=json.loads(row["calculation_results"] or "{}"),
            analysis_result=json.loads(row["analysis_result"] or "{}"),
            user_age=row["user_age"],
            actions_completed=[
                CaseAction(**a) for a in json.loads(row["actions_completed"] or "[]")
            ],
            pending_actions=[CaseAction(**a) for a in json.loads(row["pending_actions"] or "[]")],
            message_count=row["message_count"],
        )
