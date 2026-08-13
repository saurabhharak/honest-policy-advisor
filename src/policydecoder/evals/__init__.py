"""Opik evaluation harness for the policy-decoder agents.

Each agent is evaluated against a labeled gold dataset via Opik's
evaluate(): a sync task wrapper (asyncio.run inside a fresh loop per
thread), deterministic metrics (always, free), and a robust LLM judge
(optional, --live). See the plan at ~/.commandcode/plans/opik-agent-evals.md.
"""
