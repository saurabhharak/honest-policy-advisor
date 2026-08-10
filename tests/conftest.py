"""Test doubles. No real LLM, no real channels, no real timers."""

from unittest.mock import MagicMock, patch

import pytest

from policydecoder import guardrails, opik_tracing
from policydecoder.case_manager import case_manager


@pytest.fixture(autouse=True)
def test_env(monkeypatch):
    """Provide the env vars Config requires so tests run without a .env.

    CI has no secrets. Config._require() raises without these, and several
    agents call get_config() at construction. Dummy values are fine — tests
    never make real network calls (LLM/vision are mocked).
    """
    for key, value in {
        "CASPIAN_API_KEY": "test-caspian-key",
        "TELEGRAM_BOT_TOKEN": "test-telegram-token",
        "OPENAI_API_KEY": "test-openai-key",
        "OPENAI_BASE_URL": "https://api.openai.com/v1",
    }.items():
        monkeypatch.setenv(key, value)
    # Reset the cached Config so it is rebuilt from the dummy env vars.
    import policydecoder.config as config_module

    config_module._config = None
    yield


@pytest.fixture(autouse=True)
def reset_case_manager():
    """Reset the singleton case manager before each test."""
    case_manager._cases.clear()
    case_manager._store = None
    yield
    case_manager._cases.clear()
    case_manager._store = None


@pytest.fixture(autouse=True)
def guardrails_off():
    """Force guardrails off for every test by default.

    Rails make real LLM calls and depend on GUARDRAILS_ENABLED in the
    developer's .env. Tests must never hit the real endpoint unless they
    explicitly patch guardrails.is_enabled (or mock _get_rails).
    """
    with patch.object(guardrails, "is_enabled", return_value=False):
        yield


@pytest.fixture(autouse=True)
def opik_off():
    """Force Opik tracing off for every test by default.

    Tracing makes network calls to the configured Opik instance. Tests
    must never send traces unless they explicitly patch is_enabled or
    mock the client.
    """
    opik_tracing._CURRENT_TRACE_ID = None
    with patch.object(opik_tracing, "is_enabled", return_value=False):
        yield
    opik_tracing._CURRENT_TRACE_ID = None


class FakeMessage:
    """Mimics the Caspian SDK Message object."""

    def __init__(self, text="", conversation_id="test_conv", sender=None, media=None):
        self.text = text
        self.conversation_id = conversation_id
        self.sender = sender or {"address": "test@example.com"}
        self.media = media or []
        self.replies = []
        self.typing_calls = 0

    def reply(self, text):
        self.replies.append(text)

    def typing(self):
        self.typing_calls += 1


class FakeExtractor:
    """Returns canned extraction results. No real vision model."""

    def __init__(self, canned_data=None, health_data=None):
        if canned_data is not None:
            self.canned_data = canned_data
        else:
            self.canned_data = {
                "policy_name": "LIC Jeevan Anand",
                "policy_type": "endowment",
                "insurer": "LIC",
                "annual_premium": 50000,
                "premium_term_years": 15,
                "policy_term_years": 15,
                "sum_assured": 1000000,
                "maturity_value_at_8pct": 1120000,
                "maturity_value_at_4pct": 780000,
                "free_look_period_days": 15,
            }
        if health_data is not None:
            self.health_data = health_data
        else:
            self.health_data = {
                "policy_name": "Care Supreme",
                "insurer": "HDFC Ergo General Insurance",
                "plan_type": "individual",
                "sum_insured": 1500000,
                "annual_premium": 18000,
                "room_rent_cap": "no cap",
                "co_pay_pct": 10,
                "waiting_periods": {
                    "accident_days": 30,
                    "pre_existing_years": 3,
                    "specific_disease_years": 2,
                },
                "sub_limits": [],
                "exclusions": [],
                "restoration": "unlimited",
                "network_hospitals_count": 13000,
            }
        # For the router: expose an llm that raises (falls back to heuristic)
        self.llm = MagicMock()
        self.llm.chat.completions.create.side_effect = Exception("no llm in tests")
        self.vision_model = "fake-vision"

    def extract_from_image(self, url):
        return self.canned_data

    def extract_from_images(self, urls):
        return self.canned_data

    def extract_health(self, urls):
        return self.health_data

    def extract_life(self, urls):
        return self.canned_data

    def validate_extraction(self, data):
        required = ["policy_name", "annual_premium", "policy_term_years", "sum_assured"]
        return [f for f in required if not data.get(f)]


class FakeAnalyzer:
    """Returns canned analysis results. No real LLM."""

    def __init__(self, canned_analysis=None, health_analysis=None):
        self.canned_analysis = canned_analysis or {
            "is_likely_missold": True,
            "misselling_reasons": [
                "Endowment plan sold as investment",
                "XIRR below 5%",
            ],
            "recommended_action": "surrender_and_complaint",
            "escalation_path": "insurer_complaint",
            "summary": "This endowment plan returns 3.8% while a term+SIP would return 11%.",
            "key_findings": [
                "XIRR of 3.8% is below savings account rates",
                "Premium allocation charge of 4.2% in year 1",
            ],
        }
        self.health_analysis = health_analysis or {
            "verdict": "GOOD",
            "summary": "This health policy has strong terms and a solid insurer track record.",
            "key_findings": ["No room rent cap", "Unlimited restoration"],
            "red_flags": [],
            "recommended_action": "keep_policy",
            "honest_reassurance": "The room rent is uncapped and the insurer settles claims well.",
        }

    def classify_intent(self, message_text, case_state, case_summary):
        if "policy" in message_text.lower() or "insurance" in message_text.lower():
            return {"intent": "NEW_POLICY", "confidence": 0.95, "extracted_info": {}}
        if message_text.strip().isdigit():
            return {
                "intent": "INFO_RESPONSE",
                "confidence": 0.9,
                "extracted_info": {"user_age": message_text.strip()},
            }
        if "confirm" in message_text.lower() or "yes" in message_text.lower():
            return {"intent": "CONFIRM_ACTION", "confidence": 0.9, "extracted_info": {}}
        if "status" in message_text.lower():
            return {"intent": "STATUS_CHECK", "confidence": 0.95, "extracted_info": {}}
        return {"intent": "UNKNOWN", "confidence": 0.3, "extracted_info": {}}

    def analyze_policy(self, **kwargs):
        return self.canned_analysis

    def analyze_health_policy(self, **kwargs):
        return self.health_analysis

    def draft_free_look_letter(self, **kwargs):
        return "Dear Sir/Madam,\n\nI wish to cancel my policy under the free-look period..."

    def draft_complaint_letter(self, **kwargs):
        return "Dear Grievance Officer,\n\nI am writing to complain about a mis-sold policy..."

    def draft_ombudsman_letter(self, **kwargs):
        return "To the Insurance Ombudsman,\n\nI am filing a complaint against..."

    def draft_status_response(self, **kwargs):
        return "Your case is being processed."
