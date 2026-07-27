"""Text extraction endpoints for documents attached in the web chat."""
from __future__ import annotations

import asyncio
import base64
import binascii
import tempfile
import io
import zipfile
from pathlib import Path
from typing import List

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from dabba.data.document_parser import DocumentParser


MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
# DeepSeek V4/GLM-class models have large context windows. The old 30K limit
# silently discarded most of ordinary reports and theses before the provider
# ever saw them. Keep a bounded safety ceiling for unusually huge uploads,
# while allowing roughly 60K tokens per document and 120K across attachments.
MAX_DOCUMENT_CHARS = 250_000
MAX_TOTAL_CHARS = 500_000
SUPPORTED_SUFFIXES = {
    ".pdf", ".docx", ".xlsx", ".pptx",
    ".txt", ".md", ".markdown", ".json", ".jsonl", ".csv",
}


class DocumentUpload(BaseModel):
    name: str
    data_url: str


class DocumentExtractRequest(BaseModel):
    files: List[DocumentUpload]


def _decode_data_url(data_url: str) -> bytes:
    try:
        header, encoded = data_url.split(",", 1)
    except ValueError as exc:
        raise ValueError("Attachment is not a valid data URL.") from exc
    if ";base64" not in header.lower():
        raise ValueError("Attachment data must be base64 encoded.")
    try:
        return base64.b64decode(encoded, validate=True)
    except (ValueError, binascii.Error) as exc:
        raise ValueError("Attachment contains invalid base64 data.") from exc


def _detected_suffix(name: str, content: bytes) -> str:
    if content.startswith(b"%PDF"):
        return ".pdf"
    if content.startswith(b"PK\x03\x04"):
        try:
            with zipfile.ZipFile(io.BytesIO(content)) as archive:
                names = set(archive.namelist())
                if "word/document.xml" in names:
                    return ".docx"
                if "xl/workbook.xml" in names:
                    return ".xlsx"
                if "ppt/presentation.xml" in names:
                    return ".pptx"
        except (OSError, zipfile.BadZipFile):
            pass
    return Path(name).suffix.lower()


def extract_document_bytes(name: str, content: bytes) -> str:
    if not content:
        raise ValueError(f'"{name}" is empty.')
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f'"{name}" exceeds the 10 MB attachment limit.')

    suffix = _detected_suffix(name, content)
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(f'Unsupported document type for "{name}". Supported: {supported}.')

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        sections = DocumentParser(max_file_size_mb=10).parse_file(tmp_path)
    except Exception as exc:
        raise ValueError(f'Could not read "{name}": {exc}') from exc
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    text = "\n\n".join(section.strip() for section in sections if section.strip()).strip()
    if not text:
        if suffix == ".pdf":
            raise ValueError(
                f'No readable text was found in "{name}". It may be a scanned PDF; '
                "convert it with OCR and attach it again."
            )
        raise ValueError(f'No readable text was found in "{name}".')
    return text


def _bounded_document_text(text: str, limit: int) -> tuple[str, bool]:
    """Bound extracted text while clearly reporting the original size."""
    if len(text) <= limit:
        return text, False
    marker = (
        f"\n\n[Document text truncated after {limit:,} of "
        f"{len(text):,} extracted characters to fit the chat context.]"
    )
    return text[:max(0, limit - len(marker))] + marker, True


def create_document_router() -> APIRouter:
    router = APIRouter(prefix="/v1/documents", tags=["documents"])

    @router.post("/extract")
    async def extract_documents(req: DocumentExtractRequest):
        if not req.files:
            raise HTTPException(status_code=400, detail="No documents were attached.")

        decoded: list[tuple[str, bytes]] = []
        total_bytes = 0
        for upload in req.files:
            try:
                content = _decode_data_url(upload.data_url)
            except ValueError as exc:
                raise HTTPException(status_code=400, detail=f'{upload.name}: {exc}') from exc
            total_bytes += len(content)
            if total_bytes > MAX_TOTAL_BYTES:
                raise HTTPException(status_code=413, detail="Attachments exceed the 25 MB combined limit.")
            decoded.append((upload.name, content))

        documents = []
        remaining_chars = MAX_TOTAL_CHARS
        for name, content in decoded:
            try:
                text = await asyncio.to_thread(extract_document_bytes, name, content)
            except ValueError as exc:
                raise HTTPException(status_code=422, detail=str(exc)) from exc

            limit = min(MAX_DOCUMENT_CHARS, remaining_chars)
            if limit <= 0:
                break
            extracted, truncated = _bounded_document_text(text, limit)
            remaining_chars -= len(extracted)
            documents.append({
                "name": name,
                "text": extracted,
                "characters": len(text),
                "truncated": truncated,
            })

        return {"documents": documents}

    return router
