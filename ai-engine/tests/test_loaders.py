"""File loaders: plain text, markdown, docling path, unstructured fallback, S3, errors."""
from unittest.mock import MagicMock, patch

import pytest
from langchain_core.documents import Document

from app.config import settings
from app.ingestion.loaders import SUPPORTED_EXTENSIONS, load_requirement_doc


def test_supported_extensions_include_common_types():
    for ext in (".pdf", ".docx", ".txt", ".md", ".csv", ".html"):
        assert ext in SUPPORTED_EXTENSIONS


def test_load_requirement_doc_plain_text(tmp_path):
    f = tmp_path / "test.txt"
    f.write_text("hello world")
    docs = load_requirement_doc(str(f), "proj-1", "requirement")
    assert len(docs) == 1
    assert docs[0].page_content == "hello world"
    assert docs[0].metadata["project_id"] == "proj-1"
    assert docs[0].metadata["doc_type"] == "requirement"
    assert docs[0].metadata["source"] == str(f)


def test_load_requirement_doc_markdown(tmp_path):
    f = tmp_path / "test.md"
    f.write_text("# Title\n\ncontent here")
    docs = load_requirement_doc(str(f), "proj-2")
    assert len(docs) == 1
    assert "# Title" in docs[0].page_content
    assert docs[0].metadata["project_id"] == "proj-2"


def test_load_requirement_doc_unsupported_type_raises(tmp_path):
    f = tmp_path / "test.xyz"
    f.write_text("content")
    with pytest.raises(ValueError, match="Unsupported file type"):
        load_requirement_doc(str(f), "proj-1")


def test_docling_enabled_uses_docling_parser(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DOCLING_ENABLED", True)
    f = tmp_path / "test.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    mock_doc = Document(page_content="parsed content", metadata={})
    with patch("app.ingestion.loaders._load_with_docling", return_value=[mock_doc]) as mock_dl, \
         patch("app.ingestion.loaders._load_with_unstructured") as mock_unstructured:
        docs = load_requirement_doc(str(f), "proj-1")

    mock_dl.assert_called_once()
    mock_unstructured.assert_not_called()
    assert docs[0].page_content == "parsed content"


def test_docling_failure_falls_back_to_unstructured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DOCLING_ENABLED", True)
    f = tmp_path / "test.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    mock_doc = Document(page_content="unstructured content", metadata={})
    with patch("app.ingestion.loaders._load_with_docling", side_effect=Exception("docling failed")), \
         patch("app.ingestion.loaders._load_with_unstructured", return_value=[mock_doc]) as mock_unstructured:
        docs = load_requirement_doc(str(f), "proj-1")

    mock_unstructured.assert_called_once()
    assert docs[0].page_content == "unstructured content"


def test_docling_disabled_uses_unstructured(monkeypatch, tmp_path):
    monkeypatch.setattr(settings, "DOCLING_ENABLED", False)
    f = tmp_path / "test.pdf"
    f.write_bytes(b"%PDF-1.4 fake")

    mock_doc = Document(page_content="unstructured content", metadata={})
    with patch("app.ingestion.loaders._load_with_unstructured", return_value=[mock_doc]) as mock_unstructured:
        docs = load_requirement_doc(str(f), "proj-1")

    mock_unstructured.assert_called_once()
    assert docs[0].page_content == "unstructured content"


def test_empty_extraction_raises_for_non_pdf(tmp_path):
    f = tmp_path / "test.docx"
    f.write_bytes(b"fake")

    with patch("app.ingestion.loaders._load_with_unstructured", return_value=[]):
        with pytest.raises(ValueError, match="no text"):
            load_requirement_doc(str(f), "proj-1")


def test_s3_path_downloads_then_loads(monkeypatch):
    mock_doc = Document(page_content="s3 content", metadata={})
    with patch("app.ingestion.loaders._download_from_s3", return_value="/tmp/downloaded.pdf") as mock_dl, \
         patch("app.ingestion.loaders._load_with_unstructured", return_value=[mock_doc]) as mock_unstructured:
        docs = load_requirement_doc("s3://my-bucket/path/file.pdf", "proj-1")

    mock_dl.assert_called_once_with("s3://my-bucket/path/file.pdf")
    mock_unstructured.assert_called_once_with("/tmp/downloaded.pdf")
    assert docs[0].metadata["source"] == "s3://my-bucket/path/file.pdf"


def test_download_from_s3_calls_boto3():
    pytest.importorskip("boto3")
    mock_s3 = MagicMock()
    mock_client = MagicMock()
    mock_s3.client.return_value = mock_client

    with patch("boto3.client", mock_s3.client), \
         patch("tempfile.NamedTemporaryFile") as mock_ntf:
        mock_tmp = MagicMock()
        mock_tmp.name = "/tmp/test.pdf"
        mock_ntf.return_value = mock_tmp

        from app.ingestion.loaders import _download_from_s3
        result = _download_from_s3("s3://bucket/key.pdf")

    mock_client.download_file.assert_called_once_with("bucket", "key.pdf", "/tmp/test.pdf")
    assert result == "/tmp/test.pdf"


def test_scanned_pdf_fallback_for_empty_extraction(monkeypatch, tmp_path):
    f = tmp_path / "scanned.pdf"
    f.write_bytes(b"%PDF-1.4 fake scanned")

    mock_doc = Document(page_content="textract content", metadata={})
    with patch("app.ingestion.loaders._load_with_unstructured", return_value=[]), \
         patch("app.ingestion.loaders._load_scanned_pdf_fallback", return_value=[mock_doc]) as mock_fallback:
        docs = load_requirement_doc(str(f), "proj-1")

    mock_fallback.assert_called_once()
    assert docs[0].page_content == "textract content"
