"""Post a paper-scout report to Slack."""

from __future__ import annotations

import json
import os
import urllib.request
from pathlib import Path


def _load_dotenv() -> None:
    env_path = Path(__file__).resolve().parent.parent / ".env"
    if not env_path.exists():
        return
    for line in env_path.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value


def post_report(report: str, *, token: str | None = None, channel: str | None = None) -> None:
    """Post report text to Slack. Reads SLACK_BOT_TOKEN and SLACK_CHANNEL from .env if not passed."""
    _load_dotenv()
    token = token or os.environ.get("SLACK_BOT_TOKEN")
    channel = channel or os.environ.get("SLACK_CHANNEL")
    if not token:
        raise ValueError("SLACK_BOT_TOKEN not set — add it to .env or pass token=")
    if not channel:
        raise ValueError("SLACK_CHANNEL not set — add it to .env or pass channel=")

    data = json.dumps({"channel": channel, "text": report}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        },
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Slack post failed: {result.get('error', 'unknown')}")
