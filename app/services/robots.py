"""Robots.txt parser with timeout, memory caching, and graceful failure handling."""
from __future__ import annotations

import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from app.config import HEADERS, ROBOTS_TIMEOUT_SECONDS, USER_AGENT

_ROBOTS_CACHE: dict[str, tuple[RobotFileParser | None, float]] = {}
_ROBOTS_LOCK = threading.Lock()
ROBOTS_CACHE_TTL = 3600.0  # 1 hour


def _get_robot_parser(scheme: str, netloc: str) -> RobotFileParser | None:
    now = time.monotonic()
    cache_key = f"{scheme}://{netloc.lower()}"

    with _ROBOTS_LOCK:
        if cache_key in _ROBOTS_CACHE:
            parser, cached_time = _ROBOTS_CACHE[cache_key]
            if (now - cached_time) < ROBOTS_CACHE_TTL:
                return parser

    robots_url = urljoin(f"{scheme}://{netloc}", "/robots.txt")
    parser = RobotFileParser()

    try:
        resp = requests.get(robots_url, headers=HEADERS, timeout=ROBOTS_TIMEOUT_SECONDS)
        if resp.status_code in (401, 403):
            # Explicit denial of robots.txt implies restricted access
            parser.parse(["User-agent: *", "Disallow: /"])
        elif resp.status_code >= 400:
            # 404 or 4xx means no robots restrictions
            parser.parse(["User-agent: *", "Allow: /"])
        else:
            parser.parse(resp.text.splitlines())
    except Exception:
        # On connection failure or timeout, fail open with a default permissive policy
        parser.parse(["User-agent: *", "Allow: /"])

    with _ROBOTS_LOCK:
        _ROBOTS_CACHE[cache_key] = (parser, now)
    return parser


def allowed_by_robots(url: str) -> tuple[bool, str]:
    """Check if URL fetching is permitted by robots.txt."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False, "Invalid website URL"

        parser = _get_robot_parser(parsed.scheme, parsed.netloc)
        if parser is None:
            return True, "robots.txt check bypassed"

        allowed = parser.can_fetch(USER_AGENT, url)
        if allowed:
            return True, "robots.txt permits access"
        return False, "robots.txt does not permit access"

    except Exception as exc:
        return False, f"robots.txt check failed: {exc}"
