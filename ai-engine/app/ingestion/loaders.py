import logging
import pathlib
import tempfile
import urllib.parse

from langchain_core.documents import Document

from app.config import settings

logger = logging.getLogger("devpilot.ingestion")

SUPPORTED_EXTENSIONS = {
    ".pdf", ".docx", ".doc", ".txt", ".md", ".csv", ".pptx", ".xlsx", ".html",
}


def _load_with_unstructured(file_path: str) -> list[Document]:
    from langchain_community.document_loaders import UnstructuredFileLoader
    loader = UnstructuredFileLoader(file_path, mode="single")
    return loader.load()


def _load_with_docling(file_path: str) -> list[Document]:
    """
    Structure-aware parse (headings, tables, page numbers). Preferred for PDF/DOCX; see §2.2.1.
    The Block list rides along in metadata["_blocks"] so the ingestion pipeline builds the tree
    from the same parse (with real page ranges) instead of re-parsing Markdown. The pipeline pops it.
    """
    from app.ingestion.docling_parser import blocks_to_markdown, parse_to_blocks
    blocks = parse_to_blocks(file_path)
    return [Document(page_content=blocks_to_markdown(blocks),
                     metadata={"parser": "docling", "_blocks": blocks})]


def _load_plain_text(file_path: str) -> list[Document]:
    text = pathlib.Path(file_path).read_text(encoding="utf-8", errors="replace")
    return [Document(page_content=text, metadata={})]


def _load_scanned_pdf_fallback(file_path: str) -> list[Document]:
    from langchain_community.document_loaders import AmazonTextractPDFLoader
    loader = AmazonTextractPDFLoader(file_path)
    return loader.load()


def _download_from_s3(s3_uri: str) -> str:
    import boto3

    parsed = urllib.parse.urlparse(s3_uri)
    bucket, key = parsed.netloc, parsed.path.lstrip("/")
    suffix = "." + key.rsplit(".", 1)[-1] if "." in key else ""

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=suffix)
    tmp.close()
    boto3.client("s3").download_file(bucket, key, tmp.name)
    return tmp.name


def load_requirement_doc(
    file_path: str,
    project_id: str,
    doc_type: str = "requirement",
) -> list[Document]:

    local_path = file_path
    if file_path.startswith("s3://"):
        local_path = _download_from_s3(file_path)

    ext = local_path.lower().rsplit(".", 1)[-1]
    if f".{ext}" not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '.{ext}'. Supported: {sorted(SUPPORTED_EXTENSIONS)}"
        )

    try:
        if ext in ("txt", "md"):
            docs = _load_plain_text(local_path)
        elif ext in ("pdf", "docx") and settings.DOCLING_ENABLED:
            try:
                docs = _load_with_docling(local_path)
            except Exception as e:  # docling failure must not block ingestion
                logger.warning("Docling failed on %s (%s); falling back to unstructured.",
                               local_path, e)
                docs = _load_with_unstructured(local_path)
        else:
            docs = _load_with_unstructured(local_path)
        if not docs or all(not d.page_content.strip() for d in docs):
            raise ValueError("Extraction produced no text")
    except Exception:
        # Most common cause: scanned/image-only PDF with no extractable text layer.
        if ext == "pdf":
            docs = _load_scanned_pdf_fallback(local_path)
        else:
            raise

    for d in docs:
        d.metadata.update({
            "project_id": project_id,
            "doc_type": doc_type,
            # Record the ORIGINAL reference (s3:// URI or shared path), not
            # the local tmp path, so traceability metadata stays meaningful
            # after the tmp file is gone.
            "source": file_path,
        })
    return docs
