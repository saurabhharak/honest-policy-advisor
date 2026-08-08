"""Tests for the insurer metrics data loader."""

from policydecoder.insurer_data import get_insurer_metrics, load_insurer_metrics


class TestLoadInsurerMetrics:
    def test_returns_non_empty(self):
        data = load_insurer_metrics()
        assert len(data) > 10

    def test_every_row_has_source_and_vintage(self):
        for metrics in load_insurer_metrics().values():
            assert metrics.get("source_url"), f"{metrics['name']} missing source_url"
            assert metrics.get("as_of"), f"{metrics['name']} missing as_of"

    def test_known_insurers_present(self):
        data = load_insurer_metrics()
        names = " | ".join(m["name"].lower() for m in data.values())
        assert "hdfc ergo" in names
        assert "star health" in names
        assert "care health" in names


class TestGetInsurerMetrics:
    def test_exact_match(self):
        metrics = get_insurer_metrics("HDFC Ergo General Insurance")
        assert metrics is not None
        assert metrics["name"] == "HDFC Ergo General Insurance"

    def test_fuzzy_match_common_short_name(self):
        metrics = get_insurer_metrics("star health")
        assert metrics is not None
        assert "star" in metrics["name"].lower()

    def test_fuzzy_match_care(self):
        metrics = get_insurer_metrics("Care Health")
        assert metrics is not None

    def test_unknown_returns_none(self):
        assert get_insurer_metrics("Fake Insurance Co") is None
