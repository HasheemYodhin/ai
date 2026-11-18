"""Parse and fetch SKILL.md files (YAML frontmatter + Markdown body) for import."""

from __future__ import annotations

import ipaddress
import re
import socket
import urllib.error
import urllib.request
from typing import Tuple
from urllib.parse import urljoin, urlparse

import yaml

MAX_BYTES = 512 * 1024
MAX_REDIRECTS = 3
TIMEOUT_SECONDS = 15

_FRONTMATTER = re.compile(
    r"\A﻿?---[ \t]*\r?\n(.*?)\r?\n---[ \t]*(?:\r?\n|\Z)(.*)\Z", re.S
)
_GITHUB_BLOB = re.compile(r"^https://github\.com/([^/]+)/([^/]+)/blob/(.+)$")
_REDIRECT_CODES = {301, 302, 303, 307, 308}


class SkillImportError(ValueError):
    pass


def parse_skill_markdown(text: str) -> Tuple[str, str, str]:
    """Return (name, description, instructions) from a SKILL.md document."""
    text = text.strip()
    if not text:
        raise SkillImportError("The SKILL.md file is empty")

    meta: dict = {}
    body = text
    match = _FRONTMATTER.match(text)
    if match:
        try:
            loaded = yaml.safe_load(match.group(1))
        except yaml.YAMLError as exc:
            raise SkillImportError(f"Could not read the SKILL.md header: {exc}") from exc
        meta = loaded if isinstance(loaded, dict) else {}
        body = match.group(2).strip()

    name = str(meta.get("name") or "").strip()
    if not name:
        heading = re.search(r"^#\s+(.+)$", body, re.M)
        name = heading.group(1).strip() if heading else ""
    if not name:
        raise SkillImportError(
            "No skill name found. Add a 'name:' header or a '# Title' line"
        )
    if not body:
        raise SkillImportError("The SKILL.md file has no instructions")

    description = " ".join(str(meta.get("description") or "").split())
    return name[:120], description[:1000], body


def _require_public_host(host: str) -> None:
    # Blocks SSRF into localhost, the LAN and cloud metadata endpoints.
    try:
        infos = socket.getaddrinfo(host, 443, proto=socket.IPPROTO_TCP)
    except socket.gaierror as exc:
        raise SkillImportError(f"Could not resolve {host}") from exc
    for info in infos:
        if not ipaddress.ip_address(info[4][0]).is_global:
            raise SkillImportError("Only public internet addresses can be imported from")


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def fetch_skill_markdown(url: str) -> str:
    """Download a SKILL.md over https, re-validating the host on every redirect."""
    url = url.strip()
    blob = _GITHUB_BLOB.match(url)
    if blob:
        url = f"https://raw.githubusercontent.com/{blob.group(1)}/{blob.group(2)}/{blob.group(3)}"

    opener = urllib.request.build_opener(_NoRedirect)
    for _ in range(MAX_REDIRECTS + 1):
        parsed = urlparse(url)
        if parsed.scheme != "https" or not parsed.hostname:
            raise SkillImportError("Use an https:// link to a SKILL.md file")
        _require_public_host(parsed.hostname)

        request = urllib.request.Request(
            url,
            headers={
                "User-Agent": "Dabba-skill-import",
                "Accept": "text/markdown, text/plain, */*",
            },
        )
        try:
            response = opener.open(request, timeout=TIMEOUT_SECONDS)
        except urllib.error.HTTPError as exc:
            location = exc.headers.get("Location") if exc.headers else None
            if exc.code in _REDIRECT_CODES and location:
                url = urljoin(url, location)
                continue
            raise SkillImportError(f"The link returned HTTP {exc.code}") from exc
        except urllib.error.URLError as exc:
            raise SkillImportError(f"Could not download the file: {exc.reason}") from exc

        with response:
            content_type = response.headers.get_content_type()
            data = response.read(MAX_BYTES + 1)
        if len(data) > MAX_BYTES:
            raise SkillImportError("The file is larger than 512 KB")
        if content_type == "text/html":
            raise SkillImportError(
                "That link is a web page, not a SKILL.md file. "
                "Use the page's download link or a raw file link"
            )
        return data.decode("utf-8", errors="replace")

    raise SkillImportError("The link redirected too many times")
