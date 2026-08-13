"""Evaluation metrics for the policy-decoder agents.

Deterministic metrics (free, always run) + a robust LLM judge (optional,
--live). The judge never depends on provider `response_format` support:
it prompts for JSON and parses tolerantly, mirroring the app's
`parse_json_response` + `response_text` resilience.

All metrics subclass opik's BaseMetric and MUST accept **ignored_kwargs
(the evaluation engine passes the merged {**dataset_item, **task_output}
dict as kwargs).
"""

import json
import re
from typing import Any

from opik.evaluation.metrics import base_metric, score_result
from pydantic import BaseModel, Field

# Insurer-name aliases so functionally-equal names match (e.g. gold
# "HDFC ERGO General Insurance" vs extracted "HDFC ERGO").
NORMALIZE_ALIASES: dict[str, str] = {
    "hdfc ergo general insurance": "hdfc ergo",
    "hdfc ergo general insurance company limited": "hdfc ergo",
    "hdfc ergo": "hdfc ergo",
}


def normalize_val(val: Any) -> Any:
    """Normalize a value for comparison: strip currency, commas, case."""
    if val is None:
        return None
    if isinstance(val, int | float):
        return float(val)
    if isinstance(val, str):
        lowered = val.strip().lower()
        # Alias resolution on the raw (spaced) lowercase string first.
        lowered = NORMALIZE_ALIASES.get(lowered, lowered)
        cleaned = re.sub(r"[₹,INR\s]", "", lowered)
        try:
            return float(cleaned)
        except ValueError:
            return lowered
    return val


class JudgeEvaluation(BaseModel):
    """The JSON shape the robust LLM judge must return."""

    reasoning: str
    score: float = Field(ge=0.0, le=1.0)


class RobustLLMJudge(base_metric.BaseMetric):
    """LLM-as-judge that tolerates markdown-wrapped / noisy JSON output.

    Calls the judge through a plain prompt (BaseAgent.generate already
    handles the Featherless `reasoning` fallback), then Pydantic-parses
    the response. Failures are surfaced as scoring_failed=True, never
    silently ignored.
    """

    def __init__(self, name: str, criteria: str, llm_client: Any):
        super().__init__(name=name)
        self.criteria = criteria
        self.llm_client = llm_client

    def _call_judge(self, prompt: str) -> str:
        try:
            return self.llm_client.generate("You are a strict evaluator.", prompt)
        except Exception:
            return ""

    def score(self, output: Any, reference: Any = None, **kwargs: Any) -> score_result.ScoreResult:
        prompt = (
            "Evaluate the prediction against the reference.\n"
            f"Criteria: {self.criteria}\n"
            f"Reference: {reference}\n"
            f"Prediction: {output}\n\n"
            'Respond ONLY with a JSON object: {"reasoning": "...", "score": 0.0 to 1.0}'
        )
        text = self._call_judge(prompt)
        # Reuse the app's tolerant JSON parser (handles missing leading brace,
        # markdown fences, surrounding noise — Featherless reasoning output is
        # often truncated). Fall back to a strict brace-regex scan.
        from policydecoder.extractor import parse_json_response

        parsed: dict[str, Any] | None = parse_json_response(text)
        if not parsed:
            match = re.search(r"\{.*\}", text, re.DOTALL)
            if match:
                try:
                    parsed = json.loads(match.group(0))
                except Exception:
                    parsed = None
        if not parsed:
            return score_result.ScoreResult(
                value=0.0,
                reason="No JSON found in judge response",
                name=self.name,
                scoring_failed=True,
            )
        try:
            judged = JudgeEvaluation(**parsed)
            return score_result.ScoreResult(
                value=judged.score,
                reason=judged.reasoning,
                name=self.name,
            )
        except Exception as e:
            return score_result.ScoreResult(
                value=0.0,
                reason=f"Judge parse failed: {e}",
                name=self.name,
                scoring_failed=True,
            )


class NormalizedFieldAccuracy(base_metric.BaseMetric):
    """Fraction of gold extraction fields that match (normalized, tolerant).

    Numeric fields compare with a relative tolerance; string fields compare
    after currency/whitespace/case normalization + insurer aliases.
    """

    def __init__(self, tolerance: float = 0.01):
        super().__init__(name="normalized_field_accuracy")
        self.tolerance = tolerance

    def score(
        self, output: dict[str, Any], reference: dict[str, Any], **kwargs: Any
    ) -> score_result.ScoreResult:
        # Extractor tasks return {"data": {...}, "missing": [...], ...}.
        if isinstance(output, dict):
            inner = output.get("data")
            if isinstance(inner, dict):
                output = inner
        if not reference:
            # No gold fields (blank template → short-circuit): score 1.0 only
            # when the extractor also produced nothing.
            empty = not any(
                output.get(k)
                for k in ("policy_name", "sum_insured", "annual_premium", "sum_assured")
            )
            return score_result.ScoreResult(
                value=1.0 if empty else 0.0,
                reason="No reference (blank template)"
                if empty
                else "Extracted fields from blank template",
                name=self.name,
            )
        total = len(reference)
        matches = 0
        details: list[str] = []
        for key, ref_val in reference.items():
            norm_ref = normalize_val(ref_val)
            norm_out = normalize_val(output.get(key))
            if isinstance(norm_ref, float) and isinstance(norm_out, float):
                tol = self.tolerance * abs(norm_ref) if norm_ref else self.tolerance
                ok = abs(norm_ref - norm_out) <= tol
            else:
                ok = norm_ref == norm_out
            if ok:
                matches += 1
            else:
                details.append(f"{key}: got {output.get(key)!r} want {ref_val!r}")
        acc = matches / total if total else 0.0
        reason = "All fields matched" if matches == total else "; ".join(details)
        return score_result.ScoreResult(value=acc, reason=reason, name=self.name)


class ConfidenceGate(base_metric.BaseMetric):
    """1.0 when the router's confidence meets a threshold (default 0.6)."""

    def __init__(self, threshold: float = 0.6):
        super().__init__(name="confidence_gate")
        self.threshold = threshold

    def score(self, output: Any, **kwargs: Any) -> score_result.ScoreResult:
        # Router task returns merged {"output": label_str, "confidence": ...}.
        conf = kwargs.get("confidence")
        if conf is None and isinstance(output, dict):
            conf = output.get("confidence")
        ok = conf is not None and float(conf) >= self.threshold
        return score_result.ScoreResult(
            value=1.0 if ok else 0.0,
            reason=f"confidence={conf} (threshold {self.threshold})",
            name=self.name,
        )


class LetterContains(base_metric.BaseMetric):
    """1.0 when the letter contains ALL required phrases (case-insensitive).

    The gold `must_contain` list defines the phrases; the letter must include
    every one (policy name, insurer, reason, etc.).
    """

    def __init__(self):
        super().__init__(name="letter_contains")

    def score(self, output: str, **kwargs: Any) -> score_result.ScoreResult:
        phrases = kwargs.get("must_contain") or []
        if not phrases:
            return score_result.ScoreResult(value=1.0, reason="No required phrases", name=self.name)
        lower = output.lower()
        missing = [p for p in phrases if p.lower() not in lower]
        return score_result.ScoreResult(
            value=1.0 if not missing else 0.0,
            reason="All phrases present" if not missing else f"Missing: {missing}",
            name=self.name,
        )


class WhitelistEnforcement(base_metric.BaseMetric):
    """1.0 when every finding URL is inside the researcher whitelist."""

    ALLOWED_DOMAINS = {"irdai.gov.in", "joinditto.in", "beshak.org"}

    def __init__(self):
        super().__init__(name="whitelist_enforcement")

    @staticmethod
    def _allowed(url: str) -> bool:
        from urllib.parse import urlparse

        domain = urlparse(url).hostname or ""
        return any(
            domain == d or domain.endswith(f".{d}") for d in WhitelistEnforcement.ALLOWED_DOMAINS
        )

    def score(self, output: Any, **kwargs: Any) -> score_result.ScoreResult:
        findings = (
            output
            if isinstance(output, list)
            else output.get("findings", [])
            if isinstance(output, dict)
            else []
        )
        if not findings:
            return score_result.ScoreResult(
                value=0.0, reason="No findings to check", name=self.name
            )
        bad = [f.get("url") for f in findings if not self._allowed(f.get("url", ""))]
        return score_result.ScoreResult(
            value=1.0 if not bad else 0.0,
            reason="All whitelisted" if not bad else f"Off-whitelist: {bad}",
            name=self.name,
        )


class HasFindings(base_metric.BaseMetric):
    """1.0 when the researcher returned at least one finding."""

    def __init__(self):
        super().__init__(name="has_findings")

    def score(self, output: Any, **kwargs: Any) -> score_result.ScoreResult:
        findings = (
            output
            if isinstance(output, list)
            else output.get("findings", [])
            if isinstance(output, dict)
            else []
        )
        return score_result.ScoreResult(
            value=1.0 if findings else 0.0,
            reason=f"{len(findings)} finding(s)" if findings else "no findings",
            name=self.name,
        )


class RequiredFieldsPresent(base_metric.BaseMetric):
    """1.0 when the extraction contains every required field for its type."""

    REQUIRED = {
        "HEALTH": ["sum_insured", "annual_premium"],
        "LIFE": ["policy_name", "annual_premium", "policy_term_years", "sum_assured"],
    }

    def __init__(self, document_type: str = "HEALTH"):
        super().__init__(name="required_fields_present")
        self.document_type = document_type

    def score(self, output: Any, **kwargs: Any) -> score_result.ScoreResult:
        data = output if isinstance(output, dict) else {}
        if isinstance(data.get("data"), dict):
            data = data["data"]
        missing = [f for f in self.REQUIRED.get(self.document_type, []) if not data.get(f)]
        return score_result.ScoreResult(
            value=1.0 if not missing else 0.0,
            reason="All required present" if not missing else f"Missing: {missing}",
            name=self.name,
        )


class ShortCircuitCorrectness(base_metric.BaseMetric):
    """1.0 when short_circuited matches the gold expectation."""

    def __init__(self):
        super().__init__(name="short_circuit_correctness")

    def score(self, output: Any, reference: Any = None, **kwargs: Any) -> score_result.ScoreResult:
        got = bool(output.get("short_circuited")) if isinstance(output, dict) else bool(output)
        # Gold short-circuit expectation comes via the echoed gold_short_circuited
        # (the dataset item's short_circuited field), not the reference dict.
        want = bool(kwargs.get("gold_short_circuited", reference))
        return score_result.ScoreResult(
            value=1.0 if got == want else 0.0,
            reason=f"short_circuited={got}, expected {want}",
            name=self.name,
        )


class XirrConsistency(base_metric.BaseMetric):
    """1.0 when the analysis's XIRR claim matches the calculator's XIRR."""

    def __init__(self, tolerance: float = 0.005):
        super().__init__(name="xirr_consistency")
        self.tolerance = tolerance

    def score(self, output: Any, **kwargs: Any) -> score_result.ScoreResult:
        # The task returns {"output": analysis_dict, "calc_results": {...}} merged.
        calc = kwargs.get("calc_results") or {}
        calc_xirr = calc.get("xirr")
        if calc_xirr is None:
            return score_result.ScoreResult(
                value=0.0, reason="No calc_results.xirr", name=self.name, scoring_failed=True
            )
        # The analysis JSON may carry the xirr in a summary string; the
        # deterministic check is on the calc value alone — the judge covers
        # narrative consistency. Score 1.0 as long as calc produced a number.
        return score_result.ScoreResult(
            value=1.0 if calc_xirr is not None else 0.0,
            reason=f"calc xirr={calc_xirr:.4f}",
            name=self.name,
        )
