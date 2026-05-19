from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _download_dreamsim(cache_dir: Path, dreamsim_type: str) -> dict[str, Any]:
    from dreamsim.model import download_weights

    cache_dir.mkdir(parents=True, exist_ok=True)
    download_weights(str(cache_dir), dreamsim_type)
    zip_path = cache_dir / "pretrained.zip"
    if zip_path.exists():
        zip_path.unlink()
    files = sorted(path.relative_to(cache_dir).as_posix() for path in cache_dir.rglob("*") if path.is_file())
    return {
        "dreamsim_type": dreamsim_type,
        "cache_dir": str(cache_dir),
        "file_count": len(files),
        "sample_files": files[:20],
    }


def _verify_dreamsim_load(cache_dir: Path, dreamsim_type: str, device: str) -> None:
    from dreamsim import dreamsim

    model, _preprocess = dreamsim(
        pretrained=True,
        device=device,
        cache_dir=str(cache_dir),
        dreamsim_type=dreamsim_type,
    )
    del model


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Download verifier model weights into the image/cache.")
    parser.add_argument("--dreamsim-cache-dir", default="/opt/wde/models/dreamsim")
    parser.add_argument("--dreamsim-type", default="ensemble")
    parser.add_argument("--device", default="cpu")
    parser.add_argument("--verify-load", action="store_true")
    parser.add_argument("--manifest", default="/opt/wde/models/model-manifest.json")
    args = parser.parse_args(argv)

    # Local source install fallback for image builds that have not run pip install yet.
    source_root = Path("/opt/wde/research/source-repos/dreamsim")
    if source_root.exists():
        sys.path.insert(0, str(source_root))

    cache_dir = Path(args.dreamsim_cache_dir)
    payload = {
        "dreamsim": _download_dreamsim(cache_dir, args.dreamsim_type),
        "verified_load": False,
    }
    if args.verify_load:
        _verify_dreamsim_load(cache_dir, args.dreamsim_type, args.device)
        payload["verified_load"] = True

    _write_json(Path(args.manifest), payload)
    print(json.dumps(payload, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
