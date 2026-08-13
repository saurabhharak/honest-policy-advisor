"""CLI entry point for the eval harness.

Usage:
    uv run python -m policydecoder.evals.run_all --agent router --live
    uv run python -m policydecoder.evals.run_all --all --live
    uv run python -m policydecoder.evals.run_all --all        # deterministic-only

--live enables the LLM judge + Opik experiments. Without it (or when
Opik is unreachable) the harness runs deterministic metrics locally.
"""

import argparse
import sys
from typing import Any

from opik.evaluation.metrics import Equals

from policydecoder.agents.base import BaseAgent
from policydecoder.evals.config import (
    DEFAULT_NB_SAMPLES,
    DEFAULT_TASK_THREADS,
    get_judge_model,
    get_opik_client,
)
from policydecoder.evals.data import gold_rows
from policydecoder.evals.metrics import (
    ConfidenceGate,
    HasFindings,
    LetterContains,
    NormalizedFieldAccuracy,
    RequiredFieldsPresent,
    RobustLLMJudge,
    ShortCircuitCorrectness,
    WhitelistEnforcement,
    XirrConsistency,
)
from policydecoder.evals.tasks import TASK_BUILDERS
from policydecoder.logging import configure_logging

AGENTS = list(TASK_BUILDERS.keys())

# (metric, judge?) builders per agent.
AGENT_METRICS = {
    "router": lambda: [Equals(name="label_equals"), ConfidenceGate()],
    "extractor": lambda: [
        NormalizedFieldAccuracy(),
        ShortCircuitCorrectness(),
        RequiredFieldsPresent(),
    ],
    "researcher": lambda: [WhitelistEnforcement(), HasFindings()],
    "health_analyst": lambda: [Equals(name="verdict_equals")],
    "life_analyst": lambda: [Equals(name="missold_equals"), XirrConsistency()],
    "letter_drafter": lambda: [LetterContains()],
}

JUDGE_CRITERIA = {
    "health_analyst": "The narrative must support the computed verdict and flag only data-backed concerns. Penalize hallucinated numbers or claims not in the reference.",
    "life_analyst": "The narrative must correctly interpret the pre-computed XIRR and mis-selling indicators. Penalize contradictions of the reference math.",
    "letter_drafter": "The letter must be a formal, professional complaint/free-look letter naming the policy, insurer, and reason. Penalize vague or incomplete letters.",
}


def _make_judge(openai_client, agent: str) -> RobustLLMJudge | None:
    criteria = JUDGE_CRITERIA.get(agent)
    if not criteria:
        return None
    judge_llm = BaseAgent(llm_client=openai_client, model=get_judge_model())
    return RobustLLMJudge(name=f"{agent}_judge", criteria=criteria, llm_client=judge_llm)


def _build_llm() -> Any:
    """The OpenAI-compatible client (agents + judge build on it)."""
    from openai import OpenAI

    from policydecoder.config import get_config

    config = get_config()
    return OpenAI(api_key=config.openai_api_key, base_url=config.openai_base_url)


def run_agent(agent: str, llm_client, live: bool, nb_samples: int | None) -> None:
    """Run one agent's evaluation (local deterministic, or live via Opik)."""
    from policydecoder.evals import datasets

    rows = gold_rows(agent)
    if not rows:
        print(f"[{agent}] no gold rows; skipping")
        return

    task_builder = TASK_BUILDERS[agent]
    task = task_builder(llm_client)

    metrics = AGENT_METRICS[agent]()
    if live:
        judge = _make_judge(llm_client, agent)
        if judge:
            metrics.append(judge)

    if not live:
        # Offline: run deterministic metrics directly over the rows.
        print(f"\n=== {agent} (deterministic-only) — {len(rows)} rows ===")
        _run_local(agent, rows, task, metrics)
        return

    client = get_opik_client()
    if client is None:
        print(f"[{agent}] Opik unavailable; falling back to deterministic-only")
        print(f"\n=== {agent} (deterministic-only) — {len(rows)} rows ===")
        _run_local(agent, rows, task, metrics)
        return

    from opik.evaluation import evaluate

    # Seed the dataset (clear + insert) so evaluate() reads the current gold.
    datasets.seed_dataset(client, agent, rows)
    dataset = datasets.get_or_create_dataset(client, agent)
    print(f"\n=== {agent} (live) — dataset={dataset.name} rows={len(rows)} ===")
    result = evaluate(
        dataset=dataset,
        task=task,
        scoring_metrics=metrics,
        experiment_config={"agent": agent, "judge_model": get_judge_model()},
        experiment_name_prefix=f"agent-{agent}",
        nb_samples=nb_samples,
        task_threads=DEFAULT_TASK_THREADS,
        verbose=1,
    )
    print(f"[{agent}] experiment: {result.experiment_url}")
    # TestResult: {test_case, score_results, ...}; each ScoreResult has
    # name/value/reason.
    for tr in getattr(result, "test_results", []) or []:
        for sr in getattr(tr, "score_results", []) or []:
            print(f"  {sr.name}: {sr.value:.3f} — {sr.reason or ''}")


def _run_local(agent: str, rows: list[dict], task, metrics) -> None:
    """Deterministic-only scoring without Opik (uses the same metric objects)."""
    for i, item in enumerate(rows):
        out = task(item)
        # Build the merged kwargs the way Opik would.
        merged = {**item, **out}
        scores = []
        for m in metrics:
            try:
                res = m.score(**merged)
                scores.append(res)
            except Exception as e:
                print(f"  metric {m.name} failed: {e}")
        for res in scores:
            print(f"  [{i}] {res.name}: {res.value:.2f} — {res.reason or ''}")
    print()


def main() -> None:
    import io
    from typing import cast

    cast(io.TextIOWrapper, sys.stdout).reconfigure(encoding="utf-8", errors="replace")
    configure_logging()
    parser = argparse.ArgumentParser(description="Evaluate policy-decoder agents.")
    parser.add_argument("--agent", choices=AGENTS, help="Agent to evaluate")
    parser.add_argument("--all", action="store_true", help="Evaluate all agents")
    parser.add_argument("--live", action="store_true", help="Enable LLM judge + Opik experiments")
    parser.add_argument("--nb-samples", type=int, default=DEFAULT_NB_SAMPLES, help="Rows per agent")
    args = parser.parse_args()

    llm_client = _build_llm()
    agents = AGENTS if args.all else [args.agent] if args.agent else []
    if not agents:
        parser.error("specify --agent X or --all")

    for agent in agents:
        run_agent(agent, llm_client, live=args.live, nb_samples=args.nb_samples)


if __name__ == "__main__":
    main()
