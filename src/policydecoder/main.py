"""Entry point for Policy Decoder.

Connects email + Telegram, wires the extractor and analyzer, starts listening.

Usage:
    python -m policydecoder.main
    # or
    policydecoder
"""

from datetime import UTC, datetime
from pathlib import Path

from caspian_sdk import CommClient
from openai import OpenAI

from policydecoder.analyzer import PolicyAnalyzer
from policydecoder.case_manager import case_manager
from policydecoder.config import get_config
from policydecoder.extractor import PolicyExtractor
from policydecoder.handler import handle
from policydecoder.logging import configure_logging, get_logger

logger = get_logger("policydecoder.main")


def run() -> None:
    configure_logging()
    config = get_config()

    client = CommClient(
        api_key=config.caspian_api_key,
        base_url=config.caspian_base_url,
    )

    email_conn = client.connect_email(username=config.agent_username)
    telegram_conn = client.connect_telegram(bot_token=config.telegram_bot_token)

    logger.info("Policy Decoder ONLINE")
    logger.info("  Email:    %s", email_conn["address"])
    logger.info("  Telegram: @%s", telegram_conn["address"])
    logger.info("  LLM:      %s", config.llm_model)
    logger.info("  Vision:   %s", config.vision_model)
    logger.info("  Started:  %sZ", datetime.now(UTC).isoformat()[:19])
    logger.info("  Guardrails: %s", "enabled" if config.guardrails_enabled else "off")
    logger.info("  Opik:     %s", "enabled" if config.opik_enabled else "off")

    llm = OpenAI(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
    )
    extractor = PolicyExtractor(llm)
    analyzer = PolicyAnalyzer(llm)

    # Build the multi-agent pipeline (supervisor + specialists).
    from policydecoder.agents.extractor_agent import ExtractorAgent
    from policydecoder.agents.health_analyst import HealthAnalyst
    from policydecoder.agents.letter_drafter import LetterDrafter
    from policydecoder.agents.life_analyst import LifeAnalyst
    from policydecoder.agents.researcher_agent import ResearcherAgent
    from policydecoder.insurer_data import get_insurer_metrics
    from policydecoder.router import classify_document
    from policydecoder.supervisor import Supervisor

    async def _router_run(media_urls, input_path=None):
        if input_path:
            # Local file → classify via Docling markdown keywords
            from policydecoder.docling_parser import parse_document
            from policydecoder.router import heuristic_classify

            parsed = parse_document(Path(input_path))
            if parsed:
                label = heuristic_classify(parsed["markdown"])
                if label in ("HEALTH", "LIFE", "TERM"):
                    return label, 0.5
            return "LIFE", 0.0
        label, confidence = classify_document(
            llm, media_urls, model=config.vision_model, fallback_text=""
        )
        return label, confidence

    class RouterAgent:
        async def run(self, media_urls, input_path=None):
            return await _router_run(media_urls, input_path)

    supervisor = Supervisor(
        router=RouterAgent(),
        extractor=ExtractorAgent(extractor=extractor, llm_client=llm),
        researcher=ResearcherAgent(llm_client=llm),
        health_analyst=HealthAnalyst(
            llm_client=llm,
            analyzer=analyzer,
            benchmark_lookup=get_insurer_metrics,
        ),
        life_analyst=LifeAnalyst(llm_client=llm, analyzer=analyzer),
        letter_drafter=LetterDrafter(llm_client=llm, analyzer=analyzer),
    )

    from policydecoder.store import Persistence

    store = Persistence()
    case_manager.load_all_from(store)
    logger.info("  Persistence: %s", store.db_path)

    @client.on_message
    def on_message(message):
        handle(client, message, extractor, analyzer, supervisor=supervisor)

    client.listen(ack="Policy Decoder is analyzing your message...")


if __name__ == "__main__":
    run()
