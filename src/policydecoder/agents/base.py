"""Base class for all specialist agents.

Every agent has a single responsibility and a common async run()
contract: input dict -> output dict. Agents share the LLM executor
(tracing included) but never touch each other's concerns.

Calculators stay pure functions — no agent does math.
"""

from typing import Any

from openai import OpenAI

from policydecoder.config import get_config
from policydecoder.logging import get_logger
from policydecoder.opik_tracing import trace_llm


class BaseAgent:
    """Shared LLM execution + tracing for specialist agents."""

    def __init__(self, llm_client: OpenAI, model: str | None = None):
        self.llm = llm_client
        self.model = model or get_config().llm_model
        self.logger = get_logger(f"policydecoder.agent.{type(self).__name__.lower()}")

    def generate(self, system: str, user: str, timeout: float = 15.0) -> str:
        """Single LLM call with tracing. Never raises (returns "" on failure)."""
        try:
            response = self.llm.chat.completions.create(
                model=self.model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user},
                ],
                temperature=0.7,
                max_tokens=2000,
                timeout=timeout,
            )
            content = response.choices[0].message.content
            result = content.strip() if content else ""
            trace_llm(
                f"{type(self).__name__.lower()}_generate",
                model=self.model,
                input_text=user[:500],
                output_text=result[:500],
                metadata={},
            )
            return result
        except Exception as e:
            self.logger.warning("LLM call failed: %s", e)
            return ""

    async def run(self, **inputs: Any) -> dict[str, Any]:
        """Run the agent. Subclasses implement."""
        raise NotImplementedError
