from __future__ import annotations

import argparse
import json
from typing import Any

from .scoring import (
    bbox_geometry_score,
    cssom_block_style_score,
    dreamsim_distance,
    element_block_pixelmatch_score,
    score_capture_set,
    score_screenshot_pair,
    visual_block_score,
    webcode2m_dom_score,
    webcode2m_text_score,
)


def _print_json(payload: dict[str, Any]) -> None:
    print(json.dumps(payload, indent=2, sort_keys=True))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="website-design-eval")
    subparsers = parser.add_subparsers(dest="command", required=True)

    pair = subparsers.add_parser("pair", help="Score one reference/candidate screenshot pair")
    pair.add_argument("reference")
    pair.add_argument("candidate")
    pair.add_argument("--clip", action="store_true", help="Also run local CLIP similarity")

    directory = subparsers.add_parser("directory", help="Score matching PNG names in two directories")
    directory.add_argument("reference_dir")
    directory.add_argument("candidate_dir")
    directory.add_argument("--clip", action="store_true", help="Also run local CLIP similarity")

    dreamsim = subparsers.add_parser("dreamsim", help="Run DreamSim perceptual distance on one screenshot pair")
    dreamsim.add_argument("reference")
    dreamsim.add_argument("candidate")
    dreamsim.add_argument("--device", default="cpu", help="Torch device")
    dreamsim.add_argument(
        "--dreamsim-type",
        default="open_clip_vitb32",
        help="DreamSim model type, for example open_clip_vitb32 or ensemble",
    )
    dreamsim.add_argument("--cache-dir", help="Directory for DreamSim model weights")

    webcode2m_dom = subparsers.add_parser(
        "webcode2m-dom",
        help="Run WebCode2M DOM subtree BLEU/ROUGE on one HTML pair",
    )
    webcode2m_dom.add_argument("reference_html")
    webcode2m_dom.add_argument("candidate_html")

    webcode2m_text = subparsers.add_parser(
        "webcode2m-text",
        help="Run WebCode2M visible text BLEU-1/ROUGE-1 on one HTML pair",
    )
    webcode2m_text.add_argument("reference_html")
    webcode2m_text.add_argument("candidate_html")

    visual_block = subparsers.add_parser(
        "visual-block",
        help="Score one page with the WebCode2M/Design2Code visual block metric",
    )
    visual_block.add_argument("reference_html")
    visual_block.add_argument("candidate_html")
    visual_block.add_argument("reference_screenshot")
    visual_block.add_argument("candidate_screenshot")
    visual_block.add_argument("--tmp-dir", help="Optional directory for intermediate HTML/PNG files")
    visual_block.add_argument("--device", default="cpu", help="Torch device for masked CLIP scoring")
    visual_block.add_argument("--debug", action="store_true", help="Enable upstream debug output")
    visual_block.add_argument("--include-pairs", action="store_true", help="Return matched and unmatched block details")
    visual_block.add_argument("--block-pixelmatch", action="store_true", help="Run pixelmatch over matched block crops")
    visual_block.add_argument("--pixelmatch-threshold", type=float, default=0.1, help="Pixelmatch threshold for block crops")

    block_pixelmatch = subparsers.add_parser(
        "block-pixelmatch",
        help="Run crop-level pixelmatch over WebCode2M/Design2Code matched visual blocks",
    )
    block_pixelmatch.add_argument("reference_html")
    block_pixelmatch.add_argument("candidate_html")
    block_pixelmatch.add_argument("reference_screenshot")
    block_pixelmatch.add_argument("candidate_screenshot")
    block_pixelmatch.add_argument("--tmp-dir", help="Optional directory for intermediate HTML/PNG files")
    block_pixelmatch.add_argument("--device", default="cpu", help="Torch device for masked CLIP scoring")
    block_pixelmatch.add_argument("--debug", action="store_true", help="Enable upstream debug output")
    block_pixelmatch.add_argument("--include-pairs", action="store_true", help="Return matched and unmatched block details")
    block_pixelmatch.add_argument("--pixelmatch-threshold", type=float, default=0.1, help="Pixelmatch threshold for block crops")

    bbox_geometry = subparsers.add_parser(
        "bbox-geometry",
        help="Compare WebCode2M/Design2Code matched block bounding boxes without comparing crop pixels",
    )
    bbox_geometry.add_argument("reference_html")
    bbox_geometry.add_argument("candidate_html")
    bbox_geometry.add_argument("reference_screenshot")
    bbox_geometry.add_argument("candidate_screenshot")
    bbox_geometry.add_argument("--tmp-dir", help="Optional directory for intermediate HTML/PNG files")
    bbox_geometry.add_argument("--device", default="cpu", help="Torch device for masked CLIP scoring")
    bbox_geometry.add_argument("--debug", action="store_true", help="Enable upstream debug output")
    bbox_geometry.add_argument("--include-pairs", action="store_true", help="Return matched and unmatched block details")

    cssom_block = subparsers.add_parser(
        "cssom-block-style",
        help="Compare computed CSSOM styles over WebCode2M/Design2Code matched visual blocks",
    )
    cssom_block.add_argument("reference_html")
    cssom_block.add_argument("candidate_html")
    cssom_block.add_argument("reference_screenshot")
    cssom_block.add_argument("candidate_screenshot")
    cssom_block.add_argument("--tmp-dir", help="Optional directory for intermediate HTML/PNG files")
    cssom_block.add_argument("--device", default="cpu", help="Torch device for masked CLIP scoring")
    cssom_block.add_argument("--debug", action="store_true", help="Enable upstream debug output")
    cssom_block.add_argument("--include-pairs", action="store_true", help="Return resolved and unresolved pair details")
    cssom_block.add_argument("--viewport-width", type=int, help="Override Playwright viewport width")
    cssom_block.add_argument("--viewport-height", type=int, help="Override Playwright viewport height")
    cssom_block.add_argument(
        "--min-resolution-score",
        type=float,
        default=0.35,
        help="Minimum within-page block-to-DOM resolution confidence",
    )

    args = parser.parse_args(argv)
    if args.command == "pair":
        _print_json(score_screenshot_pair(args.reference, args.candidate, include_clip=args.clip))
        return 0
    if args.command == "directory":
        _print_json(score_capture_set(args.reference_dir, args.candidate_dir, include_clip=args.clip))
        return 0
    if args.command == "dreamsim":
        _print_json(
            {
                "distance": dreamsim_distance(
                    args.reference,
                    args.candidate,
                    device=args.device,
                    dreamsim_type=args.dreamsim_type,
                    cache_dir=args.cache_dir,
                ),
                "dreamsim_type": args.dreamsim_type,
                "device": args.device,
            }
        )
        return 0
    if args.command == "webcode2m-dom":
        _print_json(webcode2m_dom_score(args.reference_html, args.candidate_html))
        return 0
    if args.command == "webcode2m-text":
        _print_json(webcode2m_text_score(args.reference_html, args.candidate_html))
        return 0
    if args.command == "visual-block":
        _print_json(
            visual_block_score(
                args.reference_html,
                args.candidate_html,
                args.reference_screenshot,
                args.candidate_screenshot,
                tmp_dir=args.tmp_dir,
                device=args.device,
                debug=args.debug,
                include_pairs=args.include_pairs,
                include_block_pixelmatch=args.block_pixelmatch,
                pixelmatch_threshold=args.pixelmatch_threshold,
            )
        )
        return 0
    if args.command == "block-pixelmatch":
        _print_json(
            element_block_pixelmatch_score(
                args.reference_html,
                args.candidate_html,
                args.reference_screenshot,
                args.candidate_screenshot,
                tmp_dir=args.tmp_dir,
                device=args.device,
                debug=args.debug,
                include_pairs=args.include_pairs,
                pixelmatch_threshold=args.pixelmatch_threshold,
            )
        )
        return 0
    if args.command == "bbox-geometry":
        _print_json(
            bbox_geometry_score(
                args.reference_html,
                args.candidate_html,
                args.reference_screenshot,
                args.candidate_screenshot,
                tmp_dir=args.tmp_dir,
                device=args.device,
                debug=args.debug,
                include_pairs=args.include_pairs,
            )
        )
        return 0
    if args.command == "cssom-block-style":
        viewport = None
        if args.viewport_width or args.viewport_height:
            if not args.viewport_width or not args.viewport_height:
                parser.error("--viewport-width and --viewport-height must be provided together")
            viewport = (args.viewport_width, args.viewport_height)
        _print_json(
            cssom_block_style_score(
                args.reference_html,
                args.candidate_html,
                args.reference_screenshot,
                args.candidate_screenshot,
                tmp_dir=args.tmp_dir,
                device=args.device,
                debug=args.debug,
                include_pairs=args.include_pairs,
                viewport=viewport,
                min_resolution_score=args.min_resolution_score,
            )
        )
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
