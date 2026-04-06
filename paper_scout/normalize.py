"""Title and author normalization for deduplication."""

import hashlib
import re


def normalize_title(title: str) -> str:
    """Normalize title for deduplication: lowercase, strip punctuation, collapse spaces."""
    normalized = title.lower()
    normalized = re.sub(r'[^\w\s\-]', '', normalized)
    normalized = re.sub(r'\s+', ' ', normalized).strip()
    return normalized


def compute_title_hash(title: str) -> str:
    """SHA-256 hash of normalized title."""
    return hashlib.sha256(normalize_title(title).encode()).hexdigest()
