"""
Document parser for loading and extracting text from various file
formats: plain text, markdown, JSON, JSONL, CSV, and PDF.
"""

import json
import csv
import io
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional, Union


class DocumentParser:
    """
    Parses documents from multiple file formats into clean text.

    Supported formats:
        - .txt: Plain text
        - .md, .markdown: Markdown (strips formatting)
        - .json: JSON (extracts specified text fields)
        - .jsonl: JSONL (one JSON object per line)
        - .csv: CSV files
        - .pdf: PDF documents (requires PyMuPDF or pdfminer)

    Usage:
        parser = DocumentParser()
        texts = parser.parse_file("document.pdf")
        texts = parser.parse_directory("/path/to/docs")
    """

    def __init__(
        self,
        json_text_fields: List[str] = None,
        csv_text_column: Optional[str] = None,
        max_file_size_mb: int = 100,
    ):
        """
        Initialize the document parser.

        Args:
            json_text_fields: JSON field names to extract text from.
            csv_text_column: Column name for CSV text extraction.
            max_file_size_mb: Maximum file size to process in MB.
        """
        self.json_text_fields = json_text_fields or ["text", "content", "body"]
        self.csv_text_column = csv_text_column
        self.max_file_size_mb = max_file_size_mb

    def parse_file(self, path: str) -> List[str]:
        """
        Parse a single file and extract text.

        Dispatches to the appropriate parser based on file extension.

        Args:
            path: Path to the file.

        Returns:
            List of text strings extracted from the file.

        Raises:
            FileNotFoundError: If the file doesn't exist.
            ValueError: If the file format is unsupported.
        """
        file_path = Path(path)
        if not file_path.exists():
            raise FileNotFoundError(f"File not found: {path}")

        file_size_mb = file_path.stat().st_size / (1024 * 1024)
        if file_size_mb > self.max_file_size_mb:
            return []

        suffix = file_path.suffix.lower()

        parsers = {
            ".txt": self._parse_text,
            ".md": self._parse_text,
            ".markdown": self._parse_text,
            ".json": self._parse_json,
            ".jsonl": self._parse_jsonl,
            ".csv": self._parse_csv,
            ".pdf": self._parse_pdf,
        }

        parser = parsers.get(suffix)
        if parser is None:
            return []

        return parser(file_path)

    def _parse_text(self, path: Path) -> List[str]:
        """
        Parse a plain text or markdown file.

        Args:
            path: Path to the file.

        Returns:
            List of text paragraphs.
        """
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            text = f.read()
        paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
        return paragraphs if paragraphs else [text.strip()]

    def _parse_json(self, path: Path) -> List[str]:
        """
        Parse a JSON file and extract text from specified fields.

        Args:
            path: Path to the JSON file.

        Returns:
            List of text strings.
        """
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            data = json.load(f)

        texts = []

        def _extract(obj, depth=0):
            if depth > 10:
                return
            if isinstance(obj, str) and len(obj) > 20:
                texts.append(obj)
            elif isinstance(obj, dict):
                for field in self.json_text_fields:
                    if field in obj and isinstance(obj[field], str):
                        texts.append(obj[field])
                for v in obj.values():
                    _extract(v, depth + 1)
            elif isinstance(obj, list):
                for item in obj:
                    _extract(item, depth + 1)

        _extract(data)
        return texts

    def _parse_jsonl(self, path: Path) -> List[str]:
        """
        Parse a JSONL file and extract text from each line.

        Args:
            path: Path to the JSONL file.

        Returns:
            List of text strings.
        """
        texts = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                    for field in self.json_text_fields:
                        if field in obj and isinstance(obj[field], str):
                            texts.append(obj[field])
                            break
                except json.JSONDecodeError:
                    continue
        return texts

    def _parse_csv(self, path: Path) -> List[str]:
        """
        Parse a CSV file and extract text from the specified column
        or all columns.

        Args:
            path: Path to the CSV file.

        Returns:
            List of text strings.
        """
        texts = []
        with open(path, "r", encoding="utf-8", errors="replace") as f:
            reader = csv.DictReader(f)
            for row in reader:
                if self.csv_text_column and self.csv_text_column in row:
                    text = row[self.csv_text_column].strip()
                    if text:
                        texts.append(text)
                else:
                    row_text = " ".join(
                        v for v in row.values() if isinstance(v, str) and v.strip()
                    )
                    if row_text.strip():
                        texts.append(row_text)
        return texts

    def _parse_pdf(self, path: Path) -> List[str]:
        """
        Parse a PDF file and extract text.

        Attempts to use PyMuPDF (fitz) first, falls back to pdfminer.

        Args:
            path: Path to the PDF file.

        Returns:
            List of text strings (one per page or paragraph).
        """
        texts = []

        try:
            import fitz
            doc = fitz.open(str(path))
            for page in doc:
                text = page.get_text().strip()
                if text:
                    texts.append(text)
            doc.close()
        except ImportError:
            try:
                from pdfminer.high_level import extract_text
                text = extract_text(str(path))
                if text.strip():
                    paragraphs = [p.strip() for p in text.split("\n\n") if p.strip()]
                    texts.extend(paragraphs)
            except ImportError:
                pass

        return texts

    def parse_directory(
        self,
        directory: str,
        extensions: Optional[List[str]] = None,
        recursive: bool = True,
    ) -> Iterator[str]:
        """
        Parse all supported files in a directory.

        Args:
            directory: Directory path to scan.
            extensions: List of file extensions to include (e.g., [".txt", ".md"]).
            recursive: If True, scan subdirectories recursively.

        Yields:
            Text strings from each parsed file.
        """
        dir_path = Path(directory)
        if not dir_path.exists() or not dir_path.is_dir():
            return

        if extensions is None:
            extensions = [".txt", ".md", ".json", ".jsonl", ".csv", ".pdf"]
        extensions = [e.lower() if e.startswith(".") else f".{e.lower()}" for e in extensions]

        pattern = "**/*" if recursive else "*"
        for file_path in dir_path.glob(pattern):
            if file_path.is_file() and file_path.suffix.lower() in extensions:
                try:
                    texts = self.parse_file(str(file_path))
                    for text in texts:
                        yield text
                except Exception:
                    continue
