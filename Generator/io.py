from __future__ import annotations

import json
from pathlib import Path, PurePosixPath
from typing import Iterable

from pydantic import BaseModel

from .models import WebsiteBundle

ALLOWED_SUFFIXES = {
    ".html",
    ".css",
    ".js",
    ".json",
    ".svg",
    ".txt",
    ".md",
}


class BundleValidationError(ValueError):
    pass


def normalize_bundle_path(raw_path: str) -> str:
    normalized = raw_path.replace("\\", "/").strip()
    pure = PurePosixPath(normalized)
    if not normalized or pure.is_absolute():
        raise BundleValidationError(f"bundle path must be relative: {raw_path!r}")
    if any(part in {"", ".", ".."} for part in pure.parts):
        raise BundleValidationError(f"bundle path cannot contain empty, dot, or parent parts: {raw_path!r}")
    if pure.suffix.lower() not in ALLOWED_SUFFIXES:
        raise BundleValidationError(f"unsupported bundle file type: {raw_path!r}")
    return pure.as_posix()


def validate_bundle(bundle: WebsiteBundle) -> list[str]:
    paths: list[str] = []
    seen: set[str] = set()
    for file in bundle.files:
        path = normalize_bundle_path(file.path)
        if path in seen:
            raise BundleValidationError(f"duplicate bundle path: {path}")
        seen.add(path)
        paths.append(path)
    if "index.html" not in seen:
        raise BundleValidationError("bundle must include root index.html")
    for asset in bundle.assets:
        normalize_bundle_path(asset.path)
        if asset.path not in seen:
            raise BundleValidationError(f"asset path is declared but not included in files: {asset.path}")
    return paths


def write_website_bundle(bundle: WebsiteBundle, target_dir: str | Path, *, overwrite: bool = True) -> list[Path]:
    paths = validate_bundle(bundle)
    root = Path(target_dir)
    root.mkdir(parents=True, exist_ok=True)
    written: list[Path] = []
    for file, normalized_path in zip(bundle.files, paths, strict=True):
        destination = root / normalized_path
        if destination.exists() and not overwrite:
            raise BundleValidationError(f"refusing to overwrite existing file: {destination}")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(file.content, encoding="utf-8")
        written.append(destination)
    return written


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
