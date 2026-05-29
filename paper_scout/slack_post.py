"""Post a paper-scout report to Slack."""

from __future__ import annotations

import json
import os
import re
import urllib.request
import urllib.parse
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


def post_message(text: str, *, token: str | None = None, channel: str | None = None) -> str:
    """Post a single message and return its Slack ts (message ID)."""
    _load_dotenv()
    token = token or os.environ.get("SLACK_BOT_TOKEN")
    channel = channel or os.environ.get("SLACK_CHANNEL")
    if not token:
        raise ValueError("SLACK_BOT_TOKEN not set")
    if not channel:
        raise ValueError("SLACK_CHANNEL not set")
    data = json.dumps({"channel": channel, "text": text}).encode()
    req = urllib.request.Request(
        "https://slack.com/api/chat.postMessage",
        data=data,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=30) as resp:
        result = json.loads(resp.read())
    if not result.get("ok"):
        raise RuntimeError(f"Slack post failed: {result.get('error', 'unknown')}")
    return result["ts"]


def fetch_reactions(ts: str, *, token: str | None = None, channel: str | None = None) -> tuple[int, int]:
    """Return (thumbs_up, thumbs_down) reaction counts for a message identified by ts."""
    _load_dotenv()
    token = token or os.environ.get("SLACK_BOT_TOKEN")
    channel = channel or os.environ.get("SLACK_CHANNEL")
    if not token or not channel:
        return 0, 0
    channel_id = channel if channel.startswith("C") else (_resolve_channel_id(token, channel) or channel)
    url = f"https://slack.com/api/reactions.get?channel={channel_id}&timestamp={urllib.parse.quote(ts)}&full=true"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    if not data.get("ok"):
        return 0, 0
    reactions = data.get("message", {}).get("reactions", [])
    thumbs_up = next((r["count"] for r in reactions if r["name"] in ("thumbsup", "+1")), 0)
    thumbs_down = next((r["count"] for r in reactions if r["name"] in ("thumbsdown", "-1")), 0)
    return thumbs_up, thumbs_down


def collect_feedback(conn, *, token: str | None = None, channel: str | None = None) -> list[dict]:
    """Read 👍/👎 reactions from Slack for all pending paper messages and store in DB.

    Returns list of feedback dicts for appending to the cumulative report file.
    """
    from paper_scout.database import get_unread_posted_messages, save_paper_feedback

    _load_dotenv()
    token = token or os.environ.get("SLACK_BOT_TOKEN")
    channel = channel or os.environ.get("SLACK_CHANNEL")
    if not token or not channel:
        return []

    pending = get_unread_posted_messages(conn)
    if not pending:
        return []

    now = __import__("datetime").datetime.now().isoformat()
    items = []
    for row in pending:
        thumbs_up, thumbs_down = fetch_reactions(row["slack_ts"], token=token, channel=channel)
        save_paper_feedback(conn, row["paper_id"], row["slack_ts"], row["run_id"], thumbs_up, thumbs_down, now)
        items.append({
            "paper_id": row["paper_id"],
            "title": row["title"],
            "url": row["url"],
            "run_id": row["run_id"],
            "slack_ts": row["slack_ts"],
            "thumbs_up": thumbs_up,
            "thumbs_down": thumbs_down,
            "fetched_at": now,
        })
    return items


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


def _resolve_channel_id(token: str, channel_name: str) -> str | None:
    """Resolve a channel name like 'paper-club' to its Slack channel ID."""
    url = "https://slack.com/api/conversations.list?limit=200&types=public_channel,private_channel"
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}"})
    with urllib.request.urlopen(req, timeout=30) as resp:
        data = json.loads(resp.read())
    if not data.get("ok"):
        return None
    name = channel_name.lstrip("#")
    for ch in data.get("channels", []):
        if ch.get("name") == name:
            return ch["id"]
    return None


def _normalize_url(url: str) -> str:
    """Strip Slack mrkdwn decoration and version suffixes for comparison."""
    # Slack wraps links as <url|text> or <url> — strip angle brackets and label
    url = re.sub(r"[<>]", "", url)
    url = url.split("|")[0].strip()
    # Normalize arxiv: strip version suffix and trailing slashes
    url = re.sub(r"(arxiv\.org/abs/[\d.]+)v\d+", r"\1", url)
    url = url.rstrip("/")
    # Normalize http vs https
    url = url.replace("http://arxiv.org", "https://arxiv.org")
    return url


def fetch_posted_urls(*, token: str | None = None, channel: str | None = None) -> set[str]:
    """Return the set of canonical paper URLs that have been posted to the Slack channel."""
    _load_dotenv()
    token = token or os.environ.get("SLACK_BOT_TOKEN")
    channel = channel or os.environ.get("SLACK_CHANNEL")
    if not token or not channel:
        return set()

    # Resolve name → ID if needed
    channel_id = channel if channel.startswith("C") else _resolve_channel_id(token, channel)
    if not channel_id:
        return set()

    posted: set[str] = set()
    cursor = None
    while True:
        params = f"channel={channel_id}&limit=200"
        if cursor:
            params += f"&cursor={urllib.parse.quote(cursor)}"
        req = urllib.request.Request(
            f"https://slack.com/api/conversations.history?{params}",
            headers={"Authorization": f"Bearer {token}"},
        )
        with urllib.request.urlopen(req, timeout=30) as resp:
            data = json.loads(resp.read())
        if not data.get("ok"):
            break
        for msg in data.get("messages", []):
            text = msg.get("text", "")
            # Extract all URLs from Slack mrkdwn <url|label> and plain text
            for raw in re.findall(r"<(https?://[^>|]+)[|>]", text):
                posted.add(_normalize_url(raw))
            for raw in re.findall(r"(?<![<|])(https?://\S+?)(?:[>\s]|$)", text):
                posted.add(_normalize_url(raw))
        next_cursor = data.get("response_metadata", {}).get("next_cursor", "")
        if not next_cursor:
            break
        cursor = next_cursor

    return posted


def sync_posted_papers(conn, *, token: str | None = None, channel: str | None = None) -> int:
    """Read Slack channel history and mark matching DB papers as posted.

    Returns the number of papers newly marked.
    """
    from paper_scout.database import mark_posted_by_urls

    slack_urls = fetch_posted_urls(token=token, channel=channel)
    if not slack_urls:
        return 0

    # Also build normalized versions of all DB paper URLs for matching
    rows = conn.execute(
        "SELECT id, url FROM papers WHERE url != '' AND posted_at IS NULL"
    ).fetchall()

    now = __import__("datetime").datetime.now().isoformat()
    updated = 0
    for row in rows:
        db_url = _normalize_url(row["url"])
        if db_url in slack_urls:
            conn.execute(
                "UPDATE papers SET posted_at = ? WHERE id = ?", (now, row["id"])
            )
            updated += 1
    conn.commit()
    return updated
