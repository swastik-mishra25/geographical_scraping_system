"""Crawl policy engine: SSRF protection, robots.txt compliance, anti-bot/CAPTCHA safety, and politeness."""
from __future__ import annotations

import ipaddress
import re
import socket
import threading
import time
from urllib.parse import urljoin, urlsplit
from urllib.robotparser import RobotFileParser

import requests

from app.config import (
    CRAWLER_REQUEST_DELAY_SECONDS,
    CRAWLER_RESPECT_ROBOTS,
    CRAWLER_TIMEOUT_SECONDS,
    HEADERS,
    ROBOTS_TIMEOUT_SECONDS,
    SSRF_PROTECTED,
    USER_AGENT,
)
from app.services.persistence import get_domain_policy, set_domain_policy

_ROBOTS_CACHE: dict[str, tuple[RobotFileParser | None, float]] = {}
_ROBOTS_LOCK = threading.RLock()
_DOMAIN_ACCESS_TIMESTAMPS: dict[str, float] = {}
_POLITENESS_LOCK = threading.Lock()

# Private and non-routable IP networks to prevent SSRF
PRIVATE_NETWORKS = [
    ipaddress.ip_network("127.0.0.0/8"),
    ipaddress.ip_network("10.0.0.0/8"),
    ipaddress.ip_network("172.16.0.0/12"),
    ipaddress.ip_network("192.168.0.0/16"),
    ipaddress.ip_network("169.254.0.0/16"),  # Link-local / cloud metadata (AWS, GCP, Azure)
    ipaddress.ip_network("0.0.0.0/8"),
    ipaddress.ip_network("::1/128"),
    ipaddress.ip_network("fc00::/7"),
    ipaddress.ip_network("fe80::/10"),
]

BLOCKED_HOSTNAMES = {
    "localhost",
    "metadata.google.internal",
    "169.254.169.254",
    "instance-data",
}

DISALLOWED_EXTENSIONS = {
    ".pdf", ".zip", ".tar", ".gz", ".exe", ".iso", ".dmg",
    ".mp4", ".mp3", ".avi", ".mov", ".mkv",
    ".jpg", ".jpeg", ".png", ".gif", ".webp", ".svg", ".bmp", ".ico",
    ".css", ".js", ".woff", ".woff2", ".ttf", ".eot",
}

CAPTCHA_SIGNATURES = [
    "cf-browser-verification",
    "cf-challenge",
    "cloudflare-turnstile",
    "challenge-running",
    "g-recaptcha",
    "recaptcha/api",
    "hcaptcha.com",
    "h-captcha",
    "distil_identification",
    "perimeterx",
    "please verify you are a human",
    "access denied",
    "bot detection",
]


def is_safe_public_url(url: str) -> tuple[bool, str]:
    """Validate that the URL is public, accessible, and not an SSRF threat."""
    try:
        parsed = urlsplit(url)
        if parsed.scheme.lower() not in ("http", "https"):
            return False, f"Unsupported scheme: {parsed.scheme}"

        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return False, "Empty hostname"

        if hostname in BLOCKED_HOSTNAMES or hostname.endswith(".local") or hostname.endswith(".internal"):
            return False, f"Access to internal hostname {hostname} is blocked for safety."

        # Check file extension
        path = parsed.path.lower()
        for ext in DISALLOWED_EXTENSIONS:
            if path.endswith(ext):
                return False, f"File extension {ext} not permitted for business web crawling."

        if not SSRF_PROTECTED:
            return True, "Allowed"

        # Resolve hostname to IP to protect against SSRF and DNS rebinding
        try:
            addr_info = socket.getaddrinfo(hostname, None)
            ips = [item[4][0] for item in addr_info if item[4]]
        except Exception as exc:
            return False, f"DNS resolution failed: {exc}"

        for ip_str in ips:
            try:
                ip_obj = ipaddress.ip_address(ip_str)
                for net in PRIVATE_NETWORKS:
                    if ip_obj in net:
                        return False, f"Resolved IP {ip_str} falls inside private network {net}. Blocked for SSRF safety."
            except ValueError:
                return False, f"Invalid IP address format: {ip_str}"

        return True, "Allowed"
    except Exception as exc:
        return False, f"URL safety check failed: {exc}"


def check_crawl_permission(url: str) -> tuple[bool, str]:
    """Check both SSRF safety and robots.txt permission for target URL."""
    safe, reason = is_safe_public_url(url)
    if not safe:
        return False, reason

    if not CRAWLER_RESPECT_ROBOTS:
        return True, "Crawl permission granted (robots check disabled)"

    parsed = urlsplit(url)
    domain = parsed.netloc.lower()

    # Check database domain policy first
    cached_policy = get_domain_policy(domain)
    if cached_policy and cached_policy.get("crawl_permission_status") == "disallowed":
        return False, f"Domain blocked by policy: {cached_policy.get('block_reason', 'disallowed')}"

    # Check robots.txt
    now = time.monotonic()
    cache_key = f"{parsed.scheme}://{domain}"

    with _ROBOTS_LOCK:
        parser = None
        if cache_key in _ROBOTS_CACHE:
            p, cached_at = _ROBOTS_CACHE[cache_key]
            if (now - cached_at) < 3600.0:
                parser = p

    if parser is None:
        parser = RobotFileParser()
        robots_url = urljoin(f"{parsed.scheme}://{domain}", "/robots.txt")
        try:
            resp = requests.get(robots_url, headers=HEADERS, timeout=ROBOTS_TIMEOUT_SECONDS)
            if resp.status_code in (401, 403):
                parser.parse(["User-agent: *", "Disallow: /"])
                set_domain_policy(domain, "403_disallowed", "disallowed", block_reason="robots.txt returned 401/403")
            elif resp.status_code >= 400:
                parser.parse(["User-agent: *", "Allow: /"])
                set_domain_policy(domain, "404_allowed", "allowed")
            else:
                parser.parse(resp.text.splitlines())
                crawl_delay = parser.crawl_delay(USER_AGENT) or 0.0
                set_domain_policy(domain, "parsed", "allowed", crawl_delay=crawl_delay)
        except Exception:
            # On connection failure to robots.txt, fail open with default policy
            parser.parse(["User-agent: *", "Allow: /"])
            set_domain_policy(domain, "timeout_fallback_allowed", "allowed")

        with _ROBOTS_LOCK:
            _ROBOTS_CACHE[cache_key] = (parser, now)

    can_fetch = parser.can_fetch(USER_AGENT, url)
    if not can_fetch:
        return False, f"Disallowed by robots.txt for User-Agent: {USER_AGENT}"

    return True, "robots.txt permits crawling"


def detect_anti_bot_or_auth(response_status: int, response_text: str) -> tuple[bool, str]:
    """Detect if response is an authentication barrier, paywall, CAPTCHA, or anti-bot challenge."""
    if response_status in (401, 403):
        return True, f"HTTP {response_status} Access Denied. Halting at authentication barrier."
    if response_status == 429:
        return True, "HTTP 429 Too Many Requests. Rate limited by server."

    lower_text = response_text[:10000].lower()
    for sig in CAPTCHA_SIGNATURES:
        if sig in lower_text:
            return True, f"Anti-bot or CAPTCHA challenge detected ({sig}). Halting in compliance with crawling policy."

    return False, "Accessible"


def apply_domain_politeness(domain: str) -> None:
    """Enforce polite crawl delay per domain."""
    with _POLITENESS_LOCK:
        last_accessed = _DOMAIN_ACCESS_TIMESTAMPS.get(domain, 0.0)
        now = time.monotonic()
        elapsed = now - last_accessed
        if elapsed < CRAWLER_REQUEST_DELAY_SECONDS:
            sleep_time = CRAWLER_REQUEST_DELAY_SECONDS - elapsed
            time.sleep(sleep_time)
        _DOMAIN_ACCESS_TIMESTAMPS[domain] = time.monotonic()

