"""
Text cleaning pipeline. Provides configurable text normalization,
HTML stripping, URL removal, whitespace normalization, and language
filtering for raw text data.
"""

import re
import unicodedata
from typing import Optional


class TextCleaner:
    """
    Configurable text cleaner for preprocessing raw text data before
    tokenization and training.

    Supports:
        - HTML tag stripping
        - URL removal
        - Extra whitespace normalization
        - Unicode normalization (NFC, NFD, NFKC, NFKD)
        - Minimum/maximum text length filtering
        - Language detection filtering (requires langdetect)

    Usage:
        cleaner = TextCleaner(remove_html=True, remove_urls=True)
        cleaned = cleaner.clean(dirty_text)
    """

    def __init__(
        self,
        remove_html: bool = True,
        remove_urls: bool = True,
        remove_extra_whitespace: bool = True,
        normalize_unicode: bool = True,
        unicode_form: str = "NFKC",
        min_text_length: int = 50,
        max_text_length: Optional[int] = None,
        language_filter: Optional[str] = None,
    ):
        """
        Initialize the text cleaner.

        Args:
            remove_html: Strip HTML/XML tags.
            remove_urls: Remove URLs from text.
            remove_extra_whitespace: Normalize multiple spaces/newlines.
            normalize_unicode: Apply Unicode normalization.
            unicode_form: Unicode normalization form (NFC, NFD, NFKC, NFKD).
            min_text_length: Minimum text length (characters) to keep.
            max_text_length: Maximum text length (characters) to keep.
            language_filter: ISO language code to filter (requires langdetect).
        """
        self.remove_html = remove_html
        self.remove_urls = remove_urls
        self.remove_extra_whitespace = remove_extra_whitespace
        self.normalize_unicode = normalize_unicode
        self.unicode_form = unicode_form
        self.min_text_length = min_text_length
        self.max_text_length = max_text_length
        self.language_filter = language_filter

        self._html_tag_re = re.compile(r"<[^>]+>")
        self._url_re = re.compile(
            r"(https?://[^\s<>\"']+|www\.[^\s<>\"']+(?:\.[^\s<>\"']+)+)"
        )
        self._whitespace_re = re.compile(r"\s+")
        self._newline_re = re.compile(r"\n{3,}")

    def clean(self, text: str) -> Optional[str]:
        """
        Clean a text string through the configured pipeline.

        Returns None if the text fails any filter (too short, wrong
        language, etc.). Otherwise returns the cleaned text.

        Args:
            text: Raw text string to clean.

        Returns:
            Cleaned text string, or None if filtered out.
        """
        if not text or not isinstance(text, str):
            return None

        text = text.strip()

        if len(text) < self.min_text_length:
            return None

        if self.max_text_length and len(text) > self.max_text_length:
            return None

        if self.remove_html:
            text = self._html_tag_re.sub("", text)

        if self.remove_urls:
            text = self._url_re.sub(" ", text)

        if self.normalize_unicode:
            text = unicodedata.normalize(self.unicode_form, text)

        if self.remove_extra_whitespace:
            text = self._newline_re.sub("\n\n", text)
            text = self._whitespace_re.sub(" ", text)
            text = text.strip()

        if self.language_filter:
            detected = self._detect_language(text)
            if detected != self.language_filter:
                return None

        return text

    def _detect_language(self, text: str) -> Optional[str]:
        """
        Detect the language of a text string.

        Uses langdetect if available. Returns None if langdetect is
        not installed or detection fails.

        Args:
            text: Text to detect language for.

        Returns:
            ISO language code string, or None.
        """
        try:
            from langdetect import detect
            return detect(text)
        except ImportError:
            return None
        except Exception:
            return None

    def clean_batch(self, texts) -> list:
        """
        Clean a batch of texts.

        Args:
            texts: Iterable of text strings.

        Returns:
            List of cleaned texts (filtered entries are excluded).
        """
        return [t for t in (self.clean(text) for text in texts) if t is not None]
