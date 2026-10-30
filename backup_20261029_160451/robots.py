from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

from app.config import USER_AGENT


def allowed_by_robots(url: str) -> tuple[bool, str]:
    try:
        parsed = urlparse(url)
        if parsed.scheme not in ("http", "https") or not parsed.netloc:
            return False, "Invalid website URL"

        robots_url = urljoin(
            f"{parsed.scheme}://{parsed.netloc}",
            "/robots.txt",
        )

        parser = RobotFileParser()
        parser.set_url(robots_url)
        parser.read()

        allowed = parser.can_fetch(USER_AGENT, url)

        if allowed:
            return True, "robots.txt permits access"
        return False, "robots.txt does not permit access"

    except Exception as exc:
        return False, f"robots.txt check failed: {exc}"
