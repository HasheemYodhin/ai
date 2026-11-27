"""Text extraction endpoints for documents attached in the web chat."""

from __future__ import annotations

import asyncio
import base64
import binascii
import codecs
import io
import tempfile
import zipfile
from pathlib import Path, PurePosixPath
from typing import BinaryIO, List

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel

from dabba.data.document_parser import DocumentParser

MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_TOTAL_BYTES = 25 * 1024 * 1024
MAX_MULTIPART_FILE_BYTES = 25 * 1024 * 1024
# Large archives stay on disk and are scanned incrementally. A finite ceiling
# limits temporary disk consumption.
MAX_ZIP_FILE_BYTES = 100 * 1024 * 1024
MAX_ZIP_ENTRIES = 5_000
MAX_ZIP_MEMBER_BYTES = 25 * 1024 * 1024
MAX_ZIP_SCAN_BYTES = 512 * 1024 * 1024
MAX_ZIP_DOCUMENTS = 100
# DeepSeek V4/GLM-class models have large context windows. The old 30K limit
# silently discarded most of ordinary reports and theses before the provider
# ever saw them. Keep a bounded safety ceiling for unusually huge uploads,
# while allowing roughly 60K tokens per document and 120K across attachments.
MAX_DOCUMENT_CHARS = 250_000
MAX_TOTAL_CHARS = 500_000
SUPPORTED_SUFFIXES = {
    ".pdf",
    ".docx",
    ".xlsx",
    ".pptx",
    ".txt",
    ".md",
    ".markdown",
    ".json",
    ".jsonl",
    ".csv",
}
TEXT_SUFFIXES = {".txt", ".md", ".markdown", ".json", ".jsonl", ".csv"}


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


def _safe_archive_name(name: str) -> str | None:
    """Return a display-only archive path, rejecting traversal/absolute paths."""
    normalized = name.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        return None
    clean = "/".join(part for part in path.parts if part not in ("", "."))
    return clean or None


def _read_zip_text_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    char_limit: int,
    byte_limit: int,
) -> tuple[str, int, bool]:
    decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
    pieces: list[str] = []
    characters = 0
    bytes_read = 0
    truncated = False
    with archive.open(info, "r") as source:
        while characters <= char_limit and bytes_read < byte_limit:
            chunk = source.read(min(64 * 1024, byte_limit - bytes_read))
            if not chunk:
                pieces.append(decoder.decode(b"", final=True))
                break
            bytes_read += len(chunk)
            decoded = decoder.decode(chunk)
            pieces.append(decoded)
            characters += len(decoded)
        else:
            truncated = True
        if bytes_read < info.file_size and (
            characters > char_limit or bytes_read >= byte_limit
        ):
            truncated = True
    return "".join(pieces)[:char_limit], bytes_read, truncated


def _parse_zip_document_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    suffix: str,
    char_limit: int,
) -> tuple[str, int]:
    if info.file_size > MAX_ZIP_MEMBER_BYTES:
        return "", 0
    tmp_path = ""
    bytes_read = 0
    try:
        with archive.open(info, "r") as source:
            with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
                tmp_path = tmp.name
                while bytes_read <= MAX_ZIP_MEMBER_BYTES:
                    chunk = source.read(
                        min(1024 * 1024, MAX_ZIP_MEMBER_BYTES + 1 - bytes_read)
                    )
                    if not chunk:
                        break
                    tmp.write(chunk)
                    bytes_read += len(chunk)
        if bytes_read > MAX_ZIP_MEMBER_BYTES:
            return "", bytes_read
        sections = DocumentParser(
            max_file_size_mb=MAX_ZIP_MEMBER_BYTES // (1024 * 1024),
        ).parse_file(tmp_path, label_pdf_pages=True)
        pieces: list[str] = []
        remaining = char_limit
        for section in sections:
            section = section.strip()
            if not section or remaining <= 0:
                continue
            pieces.append(section[:remaining])
            remaining -= len(pieces[-1])
        return "\n\n".join(pieces), bytes_read
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)


def extract_zip_file(name: str, file_obj: BinaryIO) -> tuple[str, bool]:
    """Extract bounded readable text without unpacking an archive to disk."""
    try:
        file_obj.seek(0)
        with zipfile.ZipFile(file_obj) as archive:
            infos = archive.infolist()
            if len(infos) > MAX_ZIP_ENTRIES:
                raise ValueError(
                    f'"{name}" contains too many entries ({len(infos):,}; '
                    f"maximum {MAX_ZIP_ENTRIES:,})."
                )

            parts: list[str] = []
            characters = 0
            scanned_bytes = 0
            documents = 0
            truncated = False

            for info in infos:
                safe_name = _safe_archive_name(info.filename)
                if info.is_dir() or safe_name is None:
                    continue
                suffix = Path(safe_name).suffix.lower()
                if suffix not in SUPPORTED_SUFFIXES:
                    continue
                if info.flag_bits & 0x1:
                    truncated = True
                    continue
                if (
                    documents >= MAX_ZIP_DOCUMENTS
                    or scanned_bytes >= MAX_ZIP_SCAN_BYTES
                ):
                    truncated = True
                    break

                header = f"\n\n--- {safe_name} ---\n"
                remaining = MAX_DOCUMENT_CHARS - characters - len(header)
                if remaining <= 0:
                    truncated = True
                    break

                try:
                    if suffix in TEXT_SUFFIXES:
                        text, consumed, member_truncated = _read_zip_text_member(
                            archive,
                            info,
                            remaining,
                            MAX_ZIP_SCAN_BYTES - scanned_bytes,
                        )
                        truncated = truncated or member_truncated
                    else:
                        text, consumed = _parse_zip_document_member(
                            archive,
                            info,
                            suffix,
                            remaining,
                        )
                        if not text and info.file_size > MAX_ZIP_MEMBER_BYTES:
                            truncated = True
                except (OSError, RuntimeError, ValueError, zipfile.BadZipFile):
                    truncated = True
                    continue

                scanned_bytes += consumed
                if not text.strip():
                    continue
                part = header + text.strip()
                parts.append(part)
                characters += len(part)
                documents += 1
                if characters >= MAX_DOCUMENT_CHARS:
                    truncated = True
                    break
    except (OSError, zipfile.BadZipFile) as exc:
        raise ValueError(f'Could not read ZIP archive "{name}": {exc}') from exc

    if not parts:
        raise ValueError(
            f'No readable supported documents were found in "{name}". '
            "ZIP archives may contain PDF, Office, text, Markdown, JSON, JSONL, or CSV files."
        )

    text = "".join(parts).strip()
    if truncated:
        marker = (
            "\n\n[Archive extraction was limited for safety or to fit the chat context. "
            "Ask about a smaller archive or a specific extracted file for complete contents.]"
        )
        text = text[: max(0, MAX_DOCUMENT_CHARS - len(marker))] + marker
    return text, truncated


def extract_document_bytes(name: str, content: bytes) -> str:
    if not content:
        raise ValueError(f'"{name}" is empty.')
    if len(content) > MAX_FILE_BYTES:
        raise ValueError(f'"{name}" exceeds the 10 MB attachment limit.')

    suffix = _detected_suffix(name, content)
    if suffix == ".zip":
        return extract_zip_file(name, io.BytesIO(content))[0]
    if suffix not in SUPPORTED_SUFFIXES:
        supported = ", ".join(sorted(SUPPORTED_SUFFIXES))
        raise ValueError(
            f'Unsupported document type for "{name}". Supported: {supported}.'
        )

    tmp_path = ""
    try:
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        sections = DocumentParser(max_file_size_mb=10).parse_file(
            tmp_path, label_pdf_pages=True
        )
    except Exception as exc:
        raise ValueError(f'Could not read "{name}": {exc}') from exc
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    text = "\n\n".join(
        section.strip() for section in sections if section.strip()
    ).strip()
    if not text:
        if suffix == ".pdf":
            raise ValueError(
                f'No readable text was found in "{name}". It may be a scanned PDF; '
                "convert it with OCR and attach it again."
            )
        raise ValueError(f'No readable text was found in "{name}".')
    return text


def extract_uploaded_file(upload: UploadFile) -> tuple[str, bool]:
    """Read a spooled multipart upload without loading ZIPs into memory."""
    name = Path(upload.filename or "attachment").name
    suffix = Path(name).suffix.lower()
    size = upload.size
    is_zip = suffix == ".zip" or upload.content_type in {
        "application/zip",
        "application/x-zip-compressed",
    }

    if is_zip:
        if size is not None and size > MAX_ZIP_FILE_BYTES:
            raise ValueError(
                f'"{name}" exceeds the {MAX_ZIP_FILE_BYTES // (1024 * 1024)} MiB ZIP attachment limit.'
            )
        return extract_zip_file(name, upload.file)

    if size is not None and size > MAX_MULTIPART_FILE_BYTES:
        raise ValueError(
            f'"{name}" exceeds the {MAX_MULTIPART_FILE_BYTES // (1024 * 1024)} MiB document attachment limit.'
        )

    tmp_path = ""
    copied = 0
    try:
        upload.file.seek(0)
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp_path = tmp.name
            while copied <= MAX_MULTIPART_FILE_BYTES:
                chunk = upload.file.read(
                    min(1024 * 1024, MAX_MULTIPART_FILE_BYTES + 1 - copied)
                )
                if not chunk:
                    break
                tmp.write(chunk)
                copied += len(chunk)
        if copied > MAX_MULTIPART_FILE_BYTES:
            raise ValueError(
                f'"{name}" exceeds the {MAX_MULTIPART_FILE_BYTES // (1024 * 1024)} MiB document attachment limit.'
            )

        with open(tmp_path, "rb") as source:
            signature = source.read(min(copied, MAX_FILE_BYTES))
        detected = _detected_suffix(name, signature)
        if detected not in SUPPORTED_SUFFIXES:
            supported = ", ".join(sorted(SUPPORTED_SUFFIXES | {".zip"}))
            raise ValueError(
                f'Unsupported document type for "{name}". Supported: {supported}.'
            )
        sections = DocumentParser(max_file_size_mb=100).parse_file(
            tmp_path, label_pdf_pages=True
        )
    except ValueError:
        raise
    except Exception as exc:
        raise ValueError(f'Could not read "{name}": {exc}') from exc
    finally:
        if tmp_path:
            Path(tmp_path).unlink(missing_ok=True)

    text = "\n\n".join(
        section.strip() for section in sections if section.strip()
    ).strip()
    if not text:
        raise ValueError(f'No readable text was found in "{name}".')
    return text, False


def _bounded_document_text(text: str, limit: int) -> tuple[str, bool]:
    """Bound extracted text while clearly reporting the original size."""
    if len(text) <= limit:
        return text, False
    marker = (
        f"\n\n[Document text truncated after {limit:,} of "
        f"{len(text):,} extracted characters to fit the chat context.]"
    )
    return text[: max(0, limit - len(marker))] + marker, True


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
                raise HTTPException(
                    status_code=400, detail=f"{upload.name}: {exc}"
                ) from exc
            total_bytes += len(content)
            if total_bytes > MAX_TOTAL_BYTES:
                raise HTTPException(
                    status_code=413,
                    detail="Attachments exceed the 25 MB combined limit.",
                )
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
            documents.append(
                {
                    "name": name,
                    "text": extracted,
                    "characters": len(text),
                    "truncated": truncated,
                }
            )

        return {"documents": documents}

    @router.post("/extract-upload")
    async def extract_uploaded_documents(files: List[UploadFile] = File(...)):
        if not files:
            raise HTTPException(status_code=400, detail="No documents were attached.")

        documents = []
        remaining_chars = MAX_TOTAL_CHARS
        try:
            for upload in files:
                name = Path(upload.filename or "attachment").name
                try:
                    text, source_truncated = await asyncio.to_thread(
                        extract_uploaded_file, upload
                    )
                except ValueError as exc:
                    raise HTTPException(status_code=422, detail=str(exc)) from exc

                limit = min(MAX_DOCUMENT_CHARS, remaining_chars)
                if limit <= 0:
                    break
                extracted, context_truncated = _bounded_document_text(text, limit)
                remaining_chars -= len(extracted)
                documents.append(
                    {
                        "name": name,
                        "text": extracted,
                        "characters": len(text),
                        "truncated": source_truncated or context_truncated,
                    }
                )
        finally:
            for upload in files:
                await upload.close()

        return {"documents": documents}

    return router
