from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Iterable

from pydantic import BaseModel

ALLOWED_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".json",
    ".svg",
    ".txt",
    ".md",
}


class SitePathError(ValueError):
    """Raised when a generated site file is at a path or extension we won't accept."""


def normalize_bundle_path(raw_path: str) -> str:
    """Validate and normalize a relative path that the builder agent wrote.

    Rejects absolute paths, traversal, empty segments, and unsupported file
    types. The historical name 'bundle' is kept so older callers keep working;
    the builder no longer ships a typed bundle, but the path-hygiene rules
    are still useful when sanity-checking what the coding agent produced.
    """

    normalized = raw_path.replace("\\", "/").strip()
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute():
        raise SitePathError(f"site path must be relative: {raw_path!r}")
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise SitePathError(f"site path cannot contain empty, dot, or parent parts: {raw_path!r}")
    if pure.suffix.lower() not in ALLOWED_SUFFIXES:
        raise SitePathError(f"unsupported site file type: {raw_path!r}")
    return pure.as_posix()


# Backwards-compatible alias for any caller still importing the old name.
BundleValidationError = SitePathError


def list_site_files(site_dir: str | Path) -> list[str]:
    root = Path(site_dir)
    if not root.exists():
        return []
    return sorted(
        str(path.relative_to(root)).replace("\\", "/")
        for path in root.rglob("*")
        if path.is_file()
    )


def write_json(path: str | Path, payload: BaseModel | dict | list) -> None:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(payload, BaseModel):
        text = payload.model_dump_json(indent=2)
    else:
        text = json.dumps(payload, indent=2, sort_keys=True)
    target.write_text(text, encoding="utf-8")


def read_json(path: str | Path) -> dict:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def ensure_files_exist(paths: Iterable[str | Path]) -> list[str]:
    missing = [str(path) for path in paths if not Path(path).exists()]
    return missing
