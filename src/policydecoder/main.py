"""Entry point for Policy Decoder.

Connects email + Telegram, wires the extractor and analyzer, starts listening.

Usage:
    python -m policydecoder.main
    # or
    policydecoder
"""

from datetime import datetime, timezone

from caspian_sdk import CommClient
from openai import OpenAI

from policydecoder.analyzer import PolicyAnalyzer
from policydecoder.case_manager import case_manager
from policydecoder.config import get_config
from policydecoder.extractor import PolicyExtractor
from policydecoder.handler import handle


def run() -> None:
    config = get_config()

    client = CommClient(
        api_key=config.caspian_api_key,
        base_url=config.caspian_base_url,
    )

    email_conn = client.connect_email(username=config.agent_username)
    telegram_conn = client.connect_telegram(bot_token=config.telegram_bot_token)

    print("Policy Decoder ONLINE")
    print(f"  Email:    {email_conn['address']}")
    print(f"  Telegram: @{telegram_conn['address']}")
    print(f"  LLM:      {config.llm_model}")
    print(f"  Vision:   {config.vision_model}")
    print(f"  Started:  {datetime.now(timezone.utc).isoformat()[:19]}Z")
    print()

    llm = OpenAI(
        api_key=config.openai_api_key,
        base_url=config.openai_base_url,
    )
    extractor = PolicyExtractor(llm)
    analyzer = PolicyAnalyzer(llm)

    from policydecoder.store import Persistence

    store = Persistence()
    case_manager.load_all_from(store)
    print(f"  Persistence: {store.db_path}")
    print()

    @client.on_message
    def on_message(message):
        handle(client, message, extractor, analyzer)

    client.listen(ack="Policy Decoder is analyzing your message...")


if __name__ == "__main__":
    run()
