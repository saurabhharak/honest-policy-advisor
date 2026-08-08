"""Tests for the policy extractor."""

from policydecoder.extractor import PolicyExtractor, parse_json_response


class TestParseJsonResponse:
    def test_clean_json(self):
        result = parse_json_response('{"policy_name": "LIC Jeevan Anand"}')
        assert result["policy_name"] == "LIC Jeevan Anand"

    def test_fenced_json(self):
        result = parse_json_response('```json\n{"policy_name": "HDFC Click 2 Invest"}\n```')
        assert result["policy_name"] == "HDFC Click 2 Invest"

    def test_empty_string(self):
        assert parse_json_response("") == {}

    def test_none_input(self):
        assert parse_json_response(None) == {}

    def test_prose_around_json(self):
        result = parse_json_response('Here is the result: {"annual_premium": 50000} end')
        assert result["annual_premium"] == 50000


class TestValidateExtraction:
    def test_complete_data(self):
        extractor = PolicyExtractor.__new__(PolicyExtractor)
        data = {
            "policy_name": "LIC Jeevan Anand",
            "annual_premium": 50000,
            "policy_term_years": 15,
            "sum_assured": 1000000,
        }
        assert extractor.validate_extraction(data) == []

    def test_missing_fields(self):
        extractor = PolicyExtractor.__new__(PolicyExtractor)
        data = {"policy_name": "LIC Jeevan Anand"}
        missing = extractor.validate_extraction(data)
        assert "annual_premium" in missing
        assert "policy_term_years" in missing
        assert "sum_assured" in missing

    def test_empty_data(self):
        extractor = PolicyExtractor.__new__(PolicyExtractor)
        missing = extractor.validate_extraction({})
        assert len(missing) == 4
