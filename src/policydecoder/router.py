"""Document router — classifies a policy document before extraction.

A cheap/fast model reads the first page and labels the document:
HEALTH | LIFE | TERM | UNKNOWN. This prevents the vision model from being
asked to extract health fields from a ULIP (or vice versa), which is the
classic source of hallucinated extraction.

The LLM path is best-effort. If it fails, returns garbage, or is
low-confidence, a deterministic keyword scorer takes over. If even that
fails, we default to LIFE — the pre-existing single-path behavior — so the
router never breaks the existing flow.
"""

from typing import Any

from policydecoder.logging import get_logger
from policydecoder.opik_tracing import trace_llm
from policydecoder.prompts import DOCUMENT_ROUTER_PROMPT

logger = get_logger("policydecoder.router")

# Document type labels
HEALTH = "HEALTH"
LIFE = "LIFE"
TERM = "TERM"
UNKNOWN = "UNKNOWN"

DEFAULT_LABEL = LIFE
CONFIDENCE_THRESHOLD = 0.6

# Keyword scoring: (label, weight per keyword)
_KEYWORDS: dict[str, list[str]] = {
    HEALTH: [
        "room rent",
        "co-pay",
        "copay",
        "waiting period",
        "pre-existing",
        "preexisting",
        "sum insured",
        "exclusions",
        "day care",
        "daycare",
        "hospitalization",
        "hospitalisation",
        "network hospital",
        "cashless",
        "restoration",
        "sub-limit",
        "sublimit",
        "deductible",
    ],
    TERM: [
        "term insurance",
        "term plan",
        "death benefit",
        "sum assured",
        "payout on death",
        "life cover",
        "premium payment term",
    ],
    LIFE: [
        "surrender value",
        "benefit illustration",
        "maturity value",
        "maturity amount",
        "premium allocation charge",
        "fund value",
        "fund management charge",
        "endowment",
        "ulip",
        "money back",
        "whole life",
        "annuity",
        "pension plan",
        "lock-in",
        "lock in",
    ],
}

# Order matters: HEALTH and TERM first, LIFE last as the general fallback.
_LABEL_ORDER = [HEALTH, TERM, LIFE]


def heuristic_classify(text: str) -> str:
    """Deterministic keyword scoring. Returns HEALTH, TERM, LIFE, or UNKNOWN."""
    if not text:
        return UNKNOWN
    lowered = text.lower()
    scores: dict[str, int] = {}
    for label, keywords in _KEYWORDS.items():
        scores[label] = sum(1 for kw in keywords if kw in lowered)

    best_label = UNKNOWN
    best_score = 0
    for label in _LABEL_ORDER:
        if scores[label] > best_score:
            best_label = label
            best_score = scores[label]

    return best_label if best_score > 0 else UNKNOWN


def classify_document(
    llm_client,
    media_urls: list[str],
    *,
    model: str,
    fallback_text: str = "",
) -> tuple[str, float]:
    """Classify a policy document.

    Returns (label, confidence). label is one of HEALTH/LIFE/TERM/UNKNOWN.
    Falls back to heuristic scoring when the LLM path fails.
    """
    label, confidence = _llm_classify(llm_client, media_urls, model)
    if label != UNKNOWN and confidence >= CONFIDENCE_THRESHOLD:
        return label, confidence

    # Low confidence or LLM failure → deterministic scoring
    heuristic_label = heuristic_classify(fallback_text)
    if heuristic_label != UNKNOWN:
        return heuristic_label, 0.5
    return DEFAULT_LABEL, 0.0


def _llm_classify(llm_client, media_urls: list[str], model: str) -> tuple[str, float]:
    """Ask the cheap model to classify the first page. Best-effort."""
    try:
        response = llm_client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": DOCUMENT_ROUTER_PROMPT},
                        {
                            "type": "image_url",
                            "image_url": {"url": media_urls[0]},
                        },
                    ],
                }
            ],
            max_tokens=50,
            timeout=15,
        )
        content = response.choices[0].message.content or ""
        label, confidence = _parse_router_response(content)
        trace_llm(
            "router_classify",
            model=model,
            input_text=f"media={media_urls[0][:80]}",
            output_text=f"{label} ({confidence:.2f})",
            metadata={"media_url": media_urls[0][:80]},
        )
        return label, confidence
    except Exception as e:
        logger.warning("LLM classify failed: %s", e)
        return UNKNOWN, 0.0


def _parse_router_response(content: str) -> tuple[str, float]:
    """Tolerantly parse the router's JSON response."""
    import json

    text = content.strip()
    if not text:
        return UNKNOWN, 0.0
    # Strip markdown fences
    if text.startswith("```"):
        text = text.strip("`").strip()
        if text.startswith("json"):
            text = text[4:].strip()
    try:
        data: dict[str, Any] = json.loads(text)
    except json.JSONDecodeError:
        return UNKNOWN, 0.0

    label = str(data.get("document_type", UNKNOWN)).upper()
    if label not in (HEALTH, LIFE, TERM, UNKNOWN):
        label = UNKNOWN
    try:
        confidence = float(data.get("confidence", 0.0))
    except (TypeError, ValueError):
        confidence = 0.0
    return label, confidence
