"""
Web access tools for the dabba agent.

Provides URL fetching, web searching, and link extraction
capabilities using requests and BeautifulSoup.
"""

from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Dict, List, Optional
from urllib.parse import urljoin, urlparse

from dabba.agent.tool_schema import ToolDefinition, ToolParameter
from dabba.agent.tool_registry import ToolRegistry
from dabba.utils.logging import get_logger

logger = get_logger("dabba.tools.web_tools")

try:
    import requests
    HAS_REQUESTS = True
except ImportError:
    HAS_REQUESTS = False

try:
    from bs4 import BeautifulSoup
    HAS_BEAUTIFULSOUP = True
except ImportError:
    HAS_BEAUTIFULSOUP = False


REQUEST_TIMEOUT = 30
MAX_RESPONSE_SIZE = 5_000_000  # 5 MB
USER_AGENT = (
    "Mozilla/5.0 (compatible; DabbaAgent/1.0; "
    "+https://github.com/anomalyco/dabba)"
)


class WebToolError(Exception):
    """Base exception for web tool errors."""


def _check_dependencies() -> None:
    """Check that required packages are installed."""
    if not HAS_REQUESTS:
        raise WebToolError(
            "The 'requests' package is required for web tools. "
            "Install it with: pip install requests"
        )


def _create_session() -> requests.Session:
    """Create a configured requests session."""
    session = requests.Session()
    session.headers.update({
        "User-Agent": USER_AGENT,
        "Accept": "text/html,application/json,*/*",
        "Accept-Language": "en-US,en;q=0.5",
    })
    session.max_redirects = 10
    return session


def fetch_url(url: str, timeout: int = REQUEST_TIMEOUT) -> Dict[str, object]:
    """
    Fetch the content of a URL.

    Returns the response body and metadata. Handles both HTML pages
    and raw text/JSON responses.

    Args:
        url: The URL to fetch.
        timeout: Request timeout in seconds.

    Returns:
        Dict with keys: url, status_code, content_type, content (string),
        and headers.

    Raises:
        WebToolError: If the request fails or dependencies are missing.
        ValueError: If the URL is invalid.
    """
    _check_dependencies()

    parsed = urlparse(url)
    if not parsed.scheme or not parsed.netloc:
        raise ValueError(f"Invalid URL: {url}")

    session = _create_session()
    start = time.monotonic()

    try:
        response = session.get(url, timeout=timeout)
        response.raise_for_status()

        content_type = response.headers.get("Content-Type", "").split(";")[0].strip()
        content_length = len(response.content)

        if content_length > MAX_RESPONSE_SIZE:
            raise WebToolError(
                f"Response too large: {content_length} bytes "
                f"(max {MAX_RESPONSE_SIZE})"
            )

        if "text" in content_type or "json" in content_type or "xml" in content_type:
            content = response.text
        else:
            content = response.content.decode("utf-8", errors="replace")

        elapsed = (time.monotonic() - start) * 1000
        logger.info(
            "Fetched '%s' (status=%d, size=%d, %.1fms)",
            url, response.status_code, content_length, elapsed,
        )

        result: Dict[str, object] = {
            "url": url,
            "status_code": response.status_code,
            "content_type": content_type,
            "content": content,
            "headers": dict(response.headers),
        }

        if HAS_BEAUTIFULSOUP and "text/html" in response.headers.get("Content-Type", ""):
            soup = BeautifulSoup(content, "html.parser")
            text_content = soup.get_text(separator="\n", strip=True)
            text_content = re.sub(r"\n{3,}", "\n\n", text_content)
            result["text"] = text_content
            result["title"] = soup.title.string.strip() if soup.title else ""

        return result

    except requests.exceptions.Timeout:
        raise WebToolError(f"Request timed out after {timeout}s: {url}")
    except requests.exceptions.ConnectionError as exc:
        raise WebToolError(f"Connection error for {url}: {exc}")
    except requests.exceptions.HTTPError as exc:
        raise WebToolError(f"HTTP error for {url}: {exc}")
    except requests.exceptions.RequestException as exc:
        raise WebToolError(f"Request failed for {url}: {exc}")


def search_web(
    query: str,
    num_results: int = 8,
    timeout: int = 15,
) -> List[Dict[str, str]]:
    """
    Search the web using a search engine.

    Uses a configurable search backend. Falls back to scraping
    if no API key is configured. Returns a list of search results.

    Args:
        query: Search query string.
        num_results: Number of results to return (max 20).
        timeout: Timeout per request in seconds.

    Returns:
        List of dicts with keys: title, url, snippet.

    Raises:
        WebToolError: If the search fails.
    """
    _check_dependencies()
    num_results = min(num_results, 20)

    search_url = f"https://html.duckduckgo.com/html/?q={requests.utils.quote(query)}"
    session = _create_session()

    try:
        response = session.get(search_url, timeout=timeout)
        response.raise_for_status()

        results: List[Dict[str, str]] = []

        if HAS_BEAUTIFULSOUP:
            soup = BeautifulSoup(response.text, "html.parser")
            for i, result_div in enumerate(
                soup.select(".result, .web-result, .results_links")
            ):
                if len(results) >= num_results:
                    break

                title_el = result_div.select_one(
                    ".result__title a, .result__a, h2 a"
                )
                snippet_el = result_div.select_one(
                    ".result__snippet, .result__snippet a"
                )

                title = title_el.get_text(strip=True) if title_el else ""
                href = title_el.get("href", "") if title_el else ""
                snippet = snippet_el.get_text(strip=True) if snippet_el else ""

                if title and href:
                    results.append({
                        "title": title,
                        "url": href,
                        "snippet": snippet,
                    })

        if not results:
            from urllib.parse import parse_qs, urlparse as up
            for link in soup.select("a"):
                href = link.get("href", "")
                if "://" in href and not href.startswith("http"):
                    parsed_href = up(href)
                    qs = parse_qs(parsed_href.query)
                    actual_url = qs.get("uddg", [None])[0] or href
                    title = link.get_text(strip=True)
                    if title and actual_url:
                        results.append({
                            "title": title,
                            "url": actual_url,
                            "snippet": "",
                        })
                    if len(results) >= num_results:
                        break

        if not results:
            results.append({
                "title": f"Search results for: {query}",
                "url": f"https://duckduckgo.com/?q={requests.utils.quote(query)}",
                "snippet": "Open the link to view search results.",
            })

        logger.info("Web search '%s': %d results", query, len(results))
        return results

    except Exception as exc:
        raise WebToolError(f"Web search failed: {exc}")


def extract_links(url: str, timeout: int = 15) -> List[Dict[str, str]]:
    """
    Extract all links from a web page.

    Args:
        url: The URL of the page to extract links from.
        timeout: Request timeout in seconds.

    Returns:
        List of dicts with keys: text, url, is_internal.

    Raises:
        WebToolError: If the page cannot be fetched.
    """
    if not HAS_BEAUTIFULSOUP:
        raise WebToolError(
            "BeautifulSoup is required for link extraction. "
            "Install with: pip install beautifulsoup4"
        )

    result = fetch_url(url, timeout=timeout)
    content = str(result.get("content", ""))

    soup = BeautifulSoup(content, "html.parser")
    base_url = url
    base_parsed = urlparse(url)
    base_domain = base_parsed.netloc

    links: List[Dict[str, str]] = []
    seen = set()

    for anchor in soup.find_all("a", href=True):
        href = anchor["href"].strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            continue

        absolute_url = urljoin(base_url, href)
        if absolute_url in seen:
            continue
        seen.add(absolute_url)

        parsed = urlparse(absolute_url)
        is_internal = parsed.netloc == base_domain or not parsed.netloc

        text = anchor.get_text(strip=True)[:200]
        links.append({
            "text": text or "(no text)",
            "url": absolute_url,
            "is_internal": str(is_internal),
        })

    logger.info(
        "Extracted %d links from '%s'", len(links), url
    )
    return links


def register_web_tools(registry: ToolRegistry) -> None:
    """
    Register all web access tools with a ToolRegistry.

    Args:
        registry: The tool registry to register with.
    """
    registry.register(
        ToolDefinition(
            name="web_fetch",
            description="Fetch the content of a URL. Returns text, metadata, and headers.",
            parameters=[
                ToolParameter(name="url", type="string", description="The URL to fetch."),
                ToolParameter(name="timeout", type="integer", description="Request timeout in seconds.", required=False, default=REQUEST_TIMEOUT),
            ],
            handler=fetch_url,
            handler_sync=True,
            category="web",
        )
    )
    registry.register(
        ToolDefinition(
            name="web_search",
            description="Search the web for a query and return relevant results.",
            parameters=[
                ToolParameter(name="query", type="string", description="The search query."),
                ToolParameter(name="num_results", type="integer", description="Number of results (max 20).", required=False, default=8),
            ],
            handler=search_web,
            handler_sync=True,
            category="web",
        )
    )
    registry.register(
        ToolDefinition(
            name="web_extract_links",
            description="Extract all links from a web page.",
            parameters=[
                ToolParameter(name="url", type="string", description="The URL to extract links from."),
                ToolParameter(name="timeout", type="integer", description="Request timeout in seconds.", required=False, default=15),
            ],
            handler=extract_links,
            handler_sync=True,
            category="web",
        )
    )
