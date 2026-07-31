"""Format-preserving Office and PDF text edits."""

from __future__ import annotations

import shutil
from pathlib import Path
from typing import Dict


def _replace_runs(paragraph, replacements: Dict[str, str]) -> int:
    count = 0
    for run in paragraph.runs:
        for old, new in replacements.items():
            occurrences = run.text.count(old)
            if occurrences:
                run.text = run.text.replace(old, new)
                count += occurrences
    # A phrase may span several styled runs. Preserve the first run's style
    # and only collapse the runs when a cross-run replacement is necessary.
    combined = "".join(run.text for run in paragraph.runs)
    updated = combined
    cross_run_count = 0
    for old, new in replacements.items():
        occurrences = updated.count(old)
        if occurrences:
            updated = updated.replace(old, new)
            cross_run_count += occurrences
    if cross_run_count and paragraph.runs:
        paragraph.runs[0].text = updated
        for run in paragraph.runs[1:]:
            run.text = ""
        count += cross_run_count
    return count


def edit_docx(source: Path, destination: Path, replacements: Dict[str, str]) -> int:
    from docx import Document

    document = Document(str(source))
    count = 0
    for paragraph in document.paragraphs:
        count += _replace_runs(paragraph, replacements)
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                for paragraph in cell.paragraphs:
                    count += _replace_runs(paragraph, replacements)
    for section in document.sections:
        for container in (section.header, section.footer):
            for paragraph in container.paragraphs:
                count += _replace_runs(paragraph, replacements)
            for table in container.tables:
                for row in table.rows:
                    for cell in row.cells:
                        for paragraph in cell.paragraphs:
                            count += _replace_runs(paragraph, replacements)
    document.save(str(destination))
    return count


def edit_xlsx(source: Path, destination: Path, replacements: Dict[str, str]) -> int:
    from openpyxl import load_workbook

    workbook = load_workbook(str(source))
    count = 0
    for worksheet in workbook.worksheets:
        for row in worksheet.iter_rows():
            for cell in row:
                # Formulas are intentionally left untouched.
                if not isinstance(cell.value, str) or cell.value.startswith("="):
                    continue
                updated = cell.value
                for old, new in replacements.items():
                    occurrences = updated.count(old)
                    if occurrences:
                        updated = updated.replace(old, new)
                        count += occurrences
                if updated != cell.value:
                    cell.value = updated
    workbook.save(str(destination))
    return count


def edit_pptx(source: Path, destination: Path, replacements: Dict[str, str]) -> int:
    from pptx import Presentation

    presentation = Presentation(str(source))
    count = 0

    def edit_text_frame(text_frame) -> int:
        changed = 0
        for paragraph in text_frame.paragraphs:
            changed += _replace_runs(paragraph, replacements)
        return changed

    for slide in presentation.slides:
        for shape in slide.shapes:
            if getattr(shape, "has_text_frame", False):
                count += edit_text_frame(shape.text_frame)
            if getattr(shape, "has_table", False):
                for row in shape.table.rows:
                    for cell in row.cells:
                        count += edit_text_frame(cell.text_frame)
        notes = getattr(slide, "notes_slide", None)
        if notes:
            for shape in notes.shapes:
                if getattr(shape, "has_text_frame", False):
                    count += edit_text_frame(shape.text_frame)
    presentation.save(str(destination))
    return count


def edit_pdf(source: Path, destination: Path, replacements: Dict[str, str]) -> int:
    import fitz

    document = fitz.open(str(source))
    count = 0
    for page in document:
        pending = []
        for old, new in replacements.items():
            for rect in page.search_for(old):
                page.add_redact_annot(rect, fill=(1, 1, 1))
                pending.append((rect, new))
                count += 1
        if pending:
            page.apply_redactions()
            for rect, new in pending:
                page.insert_textbox(
                    rect,
                    new,
                    fontsize=max(6, min(11, rect.height * 0.8)),
                    color=(0, 0, 0),
                )
    document.save(str(destination), garbage=4, deflate=True)
    document.close()
    return count


def edit_document(source: Path, destination: Path, replacements: Dict[str, str]) -> int:
    suffix = source.suffix.lower()
    destination.parent.mkdir(parents=True, exist_ok=True)
    if suffix == ".docx":
        count = edit_docx(source, destination, replacements)
    elif suffix == ".xlsx":
        count = edit_xlsx(source, destination, replacements)
    elif suffix == ".pptx":
        count = edit_pptx(source, destination, replacements)
    elif suffix == ".pdf":
        count = edit_pdf(source, destination, replacements)
    else:
        raise ValueError(f"Format-preserving edits are not supported for {suffix}")
    if count == 0:
        destination.unlink(missing_ok=True)
        raise ValueError(
            "None of the requested text was found; the original was not changed"
        )
    if not destination.exists() or destination.stat().st_size == 0:
        destination.unlink(missing_ok=True)
        raise OSError("Document editor did not produce a valid output file")
    return count
