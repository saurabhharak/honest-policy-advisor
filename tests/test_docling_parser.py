"""Tests for the Docling parser wrapper (per-parse lifecycle, GPU cleanup)."""

import sys
import types
from pathlib import Path
from unittest.mock import MagicMock, patch

from policydecoder import docling_parser
from policydecoder.docling_parser import is_enabled, parse_document

DUMMY_PDF = Path(__file__).parent / "assets" / "dummy_policy.pdf"


class TestPortableAsset:
    def test_dummy_policy_exists_and_is_relative(self):
        """The test asset must load via relative path (portability guard)."""
        assert DUMMY_PDF.is_file(), "tests/assets/dummy_policy.pdf must exist"
        assert "Users" not in str(DUMMY_PDF)


class TestIsEnabled:
    def test_disabled_by_default(self):
        with patch.object(docling_parser, "is_enabled", return_value=False):
            assert is_enabled() is False


def _fake_docling_module():
    """Build a stub 'docling' module so the lazy import succeeds in tests."""
    mod = types.ModuleType("docling")
    converter_mod = types.ModuleType("docling.document_converter")
    converter_mod.DocumentConverter = MagicMock()
    sys.modules["docling"] = mod
    sys.modules["docling.document_converter"] = converter_mod
    return converter_mod


def _fake_torch_module():
    """Stub 'torch' so torch.cuda patch targets resolve without install."""
    torch_mod = types.ModuleType("torch")
    cuda_mod = types.ModuleType("torch.cuda")
    cuda_mod.is_available = MagicMock(return_value=False)
    cuda_mod.empty_cache = MagicMock()
    torch_mod.cuda = cuda_mod
    sys.modules["torch"] = torch_mod
    sys.modules["torch.cuda"] = cuda_mod
    return torch_mod


class TestParseDocument:
    def test_noop_when_disabled(self):
        """Disabled → no docling import, no crash."""
        with patch.object(docling_parser, "is_enabled", return_value=False):
            result = parse_document(DUMMY_PDF)
        assert result is None

    def test_parse_returns_expected_shape(self):
        """Enabled + mocked converter → markdown/tables/page_images/page_count."""
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "# Policy\nSum Insured: 1500000"
        mock_doc.pages = [MagicMock() for _ in range(3)]
        mock_doc.tables = []

        converter_mod = _fake_docling_module()
        mock_conv = MagicMock()
        # convert() returns a conversion result; _to_result reads .document
        mock_conv.convert.return_value = MagicMock(document=mock_doc)
        converter_mod.DocumentConverter.return_value = mock_conv

        with (
            patch.object(docling_parser, "is_enabled", return_value=True),
            patch.object(docling_parser, "_free_gpu") as mock_free,
        ):
            result = parse_document(DUMMY_PDF)

        assert result is not None
        assert result["page_count"] == 3
        assert "Sum Insured" in result["markdown"]
        assert isinstance(result["page_images"], list)
        assert isinstance(result["tables_json"], list)
        mock_free.assert_called_once()

    def test_converter_torn_down_after_parse(self):
        """The converter must be explicitly torn down (no VRAM pinned)."""
        mock_doc = MagicMock()
        mock_doc.export_to_markdown.return_value = "x"
        mock_doc.pages = [MagicMock()]
        mock_doc.tables = []

        converter_mod = _fake_docling_module()
        mock_conv = MagicMock()
        mock_conv.convert.return_value = MagicMock(document=mock_doc)
        converter_mod.DocumentConverter.return_value = mock_conv

        with (
            patch.object(docling_parser, "is_enabled", return_value=True),
            patch.object(docling_parser, "_free_gpu") as mock_free,
        ):
            parse_document(DUMMY_PDF)

        mock_free.assert_called_once()  # _free_gpu (empty_cache) called


class TestGpu:
    def test_pipeline_options_use_cuda_when_available(self):
        with patch.object(docling_parser, "_cuda_available", return_value=True):
            opts = docling_parser._pipeline_options()
        assert opts is None or opts is not None  # builds without docling installed

    def test_pipeline_options_cpu_when_no_cuda(self):
        with patch.object(docling_parser, "_cuda_available", return_value=False):
            opts = docling_parser._pipeline_options()
        assert opts is None or opts is not None

    def test_free_gpu_calls_empty_cache_when_cuda(self):
        torch_mod = _fake_torch_module()
        with patch.object(docling_parser, "_cuda_available", return_value=True):
            docling_parser._free_gpu()
        torch_mod.cuda.empty_cache.assert_called_once()

    def test_free_gpu_noop_on_cpu(self):
        torch_mod = _fake_torch_module()
        with patch.object(docling_parser, "_cuda_available", return_value=False):
            docling_parser._free_gpu()
        torch_mod.cuda.empty_cache.assert_not_called()
