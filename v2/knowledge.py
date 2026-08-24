"""Read AI-Knowledge as Read Only. Never write or invent substitutes.

AI_KNOWLEDGE_TOKEN (optional):
- Purpose: GitHub Contents GET of the four Investment markdown files.
- Not used for commit, PR, PUT/PATCH/DELETE, SMTP, or trading.
- If unset, load_knowledge() returns DATA_UNAVAILABLE and evaluators WAIT.
- Do not treat a missing token as a reason to fabricate holdings or GO.
"""

from __future__ import annotations

import base64
import json
import os
import urllib.error
import urllib.request
from pathlib import Path

from v2 import DATA_UNAVAILABLE
from v2.targets import KB_FILES

DEFAULT_REPO = "marutaka1966/AI-Knowledge"


class KnowledgeSnapshot:
    def __init__(self, files: dict[str, str] | None, error: str | None = None) -> None:
        self.files = files or {}
        self.error = error
        self.available = error is None and bool(files) and all(
            name in self.files and self.files[name].strip() for name in KB_FILES
        )

    def text(self, path: str) -> str:
        return self.files.get(path, "")


def load_knowledge() -> KnowledgeSnapshot:
    """Read only. Never writes to AI-Knowledge."""
    root = os.environ.get("AI_KNOWLEDGE_PATH", "").strip()
    if root:
        return _from_path(root)
    # Read-only tokens only. GITHUB_TOKEN is used for GET if present; never for write.
    token = (
        os.environ.get("AI_KNOWLEDGE_TOKEN", "").strip()
        or os.environ.get("GITHUB_TOKEN", "").strip()
    )
    if token:
        return _from_github(token)
    return KnowledgeSnapshot(None, DATA_UNAVAILABLE)


def _from_path(root: str) -> KnowledgeSnapshot:
    base = Path(root)
    files: dict[str, str] = {}
    for rel in KB_FILES:
        path = base / rel
        if not path.is_file():
            return KnowledgeSnapshot(None, DATA_UNAVAILABLE)
        files[rel] = path.read_text(encoding="utf-8")
    return KnowledgeSnapshot(files)


def _from_github(token: str) -> KnowledgeSnapshot:
    """GET /repos/.../contents/... only. No write APIs."""
    repo = os.environ.get("AI_KNOWLEDGE_REPO", DEFAULT_REPO).strip() or DEFAULT_REPO
    files: dict[str, str] = {}
    for rel in KB_FILES:
        url = f"https://api.github.com/repos/{repo}/contents/{rel}"
        req = urllib.request.Request(
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/vnd.github+json",
                "User-Agent": "marume-report-v2",
            },
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as resp:
                payload = json.loads(resp.read().decode("utf-8"))
        except (urllib.error.URLError, TimeoutError, json.JSONDecodeError):
            return KnowledgeSnapshot(None, DATA_UNAVAILABLE)
        content = payload.get("content")
        if not content:
            return KnowledgeSnapshot(None, DATA_UNAVAILABLE)
        try:
            files[rel] = base64.b64decode(content).decode("utf-8")
        except (ValueError, UnicodeDecodeError):
            return KnowledgeSnapshot(None, DATA_UNAVAILABLE)
    return KnowledgeSnapshot(files)
