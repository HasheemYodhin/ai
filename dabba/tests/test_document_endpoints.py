import base64
import io
import zipfile

import pytest

from dabba.api.document_endpoints import (
    MAX_DOCUMENT_CHARS,
    MAX_ZIP_FILE_BYTES,
    _bounded_document_text,
    _decode_data_url,
    extract_document_bytes,
    extract_uploaded_file,
    extract_zip_file,
)
from starlette.datastructures import UploadFile


def _office_package(entries: dict[str, str]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        for name, content in entries.items():
            archive.writestr(name, content)
    return buffer.getvalue()


def test_decode_data_url_rejects_non_base64_content():
    with pytest.raises(ValueError, match="base64"):
        _decode_data_url("data:text/plain,hello")


def test_extract_docx_includes_paragraphs_and_tables():
    from docx import Document

    document = Document()
    document.add_heading("Smart Ecommerce Management", level=1)
    document.add_paragraph("The system manages products, orders, and inventory.")
    table = document.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "Module"
    table.rows[0].cells[1].text = "Inventory"
    buffer = io.BytesIO()
    document.save(buffer)

    text = extract_document_bytes("proposal.docx", buffer.getvalue())

    assert "Smart Ecommerce Management" in text
    assert "products, orders, and inventory" in text
    assert "Module | Inventory" in text


def test_file_signature_handles_docx_with_pdf_extension():
    from docx import Document

    document = Document()
    document.add_paragraph("Content from the renamed Word document.")
    buffer = io.BytesIO()
    document.save(buffer)

    text = extract_document_bytes("proposal.docx.pdf", buffer.getvalue())

    assert text == "Content from the renamed Word document."


def test_decode_data_url_round_trip():
    content = b"document text"
    data_url = "data:text/plain;base64," + base64.b64encode(content).decode("ascii")

    assert _decode_data_url(data_url) == content


def test_extract_xlsx_includes_sheet_name_and_rows():
    content = _office_package({
        "xl/workbook.xml": """
            <workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheets><sheet name="Inventory" sheetId="1"/></sheets>
            </workbook>
        """,
        "xl/worksheets/sheet1.xml": """
            <worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
              <sheetData>
                <row r="1">
                  <c r="A1" t="inlineStr"><is><t>Product</t></is></c>
                  <c r="B1" t="inlineStr"><is><t>Stock</t></is></c>
                </row>
                <row r="2">
                  <c r="A2" t="inlineStr"><is><t>Laptop</t></is></c>
                  <c r="B2"><v>12</v></c>
                </row>
              </sheetData>
            </worksheet>
        """,
    })

    text = extract_document_bytes("inventory.docx", content)

    assert "[Sheet: Inventory]" in text
    assert "Product | Stock" in text
    assert "Laptop | 12" in text


def test_extract_pptx_includes_slide_text():
    content = _office_package({
        "ppt/presentation.xml": """
            <p:presentation xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"/>
        """,
        "ppt/slides/slide1.xml": """
            <p:sld xmlns:p="http://schemas.openxmlformats.org/presentationml/2006/main"
                   xmlns:a="http://schemas.openxmlformats.org/drawingml/2006/main">
              <p:cSld><p:spTree><p:sp><p:txBody>
                <a:p><a:r><a:t>Quarterly Results</a:t></a:r></a:p>
                <a:p><a:r><a:t>Revenue increased by 18 percent</a:t></a:r></a:p>
              </p:txBody></p:sp></p:spTree></p:cSld>
            </p:sld>
        """,
    })

    text = extract_document_bytes("slides.pdf", content)

    assert "[Slide 1]" in text
    assert "Quarterly Results" in text
    assert "Revenue increased by 18 percent" in text


def test_large_text_document_is_not_cut_at_old_30k_limit():
    content = "Complete document content. " * 2_000
    extracted, truncated = _bounded_document_text(content, MAX_DOCUMENT_CHARS)

    assert len(content) > 30_000
    assert truncated is False
    assert extracted == content


def test_extremely_large_document_reports_exact_truncation():
    content = "x" * (MAX_DOCUMENT_CHARS + 10_000)
    extracted, truncated = _bounded_document_text(content, MAX_DOCUMENT_CHARS)

    assert truncated is True
    assert len(extracted) == MAX_DOCUMENT_CHARS
    assert f"of {len(content):,} extracted characters" in extracted


def test_extract_zip_reads_supported_members_without_unpacking():
    content = _office_package({
        "notes/readme.md": "Project overview\n\nThe launch date is Friday.",
        "data/ignored.bin": "not a supported document",
        "reports/status.csv": "owner,status\nAsha,ready",
    })

    text, truncated = extract_zip_file("workspace.zip", io.BytesIO(content))

    assert "--- notes/readme.md ---" in text
    assert "The launch date is Friday." in text
    assert "--- reports/status.csv ---" in text
    assert "Asha,ready" in text
    assert "ignored.bin" not in text
    assert truncated is False


def test_extract_zip_ignores_unsafe_member_paths():
    content = _office_package({
        "../../secret.txt": "must not be read",
        "/absolute.md": "must not be read either",
        "safe/notes.txt": "safe archive content",
    })

    text, _ = extract_zip_file("paths.zip", io.BytesIO(content))

    assert "safe archive content" in text
    assert "must not be read" not in text


def test_zip_upload_policy_accepts_reported_size_over_one_gibibyte():
    content = _office_package({"notes.txt": "large archive metadata test"})
    upload = UploadFile(
        io.BytesIO(content),
        filename="large.zip",
        size=2 * 1024 * 1024 * 1024,
    )

    text, truncated = extract_uploaded_file(upload)

    assert "large archive metadata test" in text
    assert truncated is False


def test_zip_upload_policy_rejects_files_over_ten_gibibytes():
    content = _office_package({"notes.txt": "too large"})
    upload = UploadFile(
        io.BytesIO(content),
        filename="too-large.zip",
        size=MAX_ZIP_FILE_BYTES + 1,
    )

    with pytest.raises(ValueError, match="10 GB"):
        extract_uploaded_file(upload)
