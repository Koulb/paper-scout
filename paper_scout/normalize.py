"""Title and author normalization for deduplication."""

import hashlib
import re
import unicodedata


def normalize_title(title: str) -> str:
    """Normalize title for deduplication: lowercase, strip punctuation, collapse spaces.

    Handles LaTeX accent commands (e.g. \\'o → o) and Unicode accented chars (ó → o)
    so the same paper fetched from different sources deduplicates correctly.
    """
    # Strip LaTeX accent commands like \'o, \"u, \^e, \`a, \~n before anything else
    normalized = re.sub(r"\\['\"`^~=.](?:\{[a-zA-Z]\}|[a-zA-Z]?)", r"", title)
    # Decompose unicode and drop combining characters (ó → o, ü → u, etc.)
    normalized = unicodedata.normalize("NFKD", normalized)
    normalized = normalized.encode("ascii", "ignore").decode("ascii")
    normalized = normalized.lower()
    normalized = re.sub(r'[^\w\s\-]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def compute_title_hash(title: str) -> str:
    """SHA-256 hash of normalized title."""
    return hashlib.sha256(normalize_title(title).encode()).hexdigest()
