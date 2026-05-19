from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from .evaluator import EvaluateConfig, evaluate, print_functional_status
from .scoring import (
    _pick_torch_device,
    accessibility_control_tags,
    bbox_geometry_score,
    cssom_block_style_score,
    dreamsim_distance,
    element_block_pixelmatch_score,
    extract_webcode2m_bbox_tree,
    mobile_overflow_tags,
    presentation_diff_tags,
    score_capture_set,
    score_screenshot_pair,
    visual_block_score,
    webcoderbench_tags,
    webcoderbench_visual_quality_scores,
    websee_dom_localization_tags,
    webcode2m_bbox_tree_to_html,
    webcode2m_bbox_tree_to_style_list,
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
    dreamsim.add_argument("--device", default=None, help="Torch device; defaults to auto-selecting cuda, mps, then cpu")
    dreamsim.add_argument(
        "--dreamsim-type",
        default="ensemble",
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

    webcode2m_bbox = subparsers.add_parser(
        "webcode2m-bbox-tree",
        help="Extract WebCode2M's rendered bbox tree for one HTML file",
    )
    webcode2m_bbox.add_argument("html")
    webcode2m_bbox.add_argument("--viewport-width", type=int, help="Optional Playwright viewport width")
    webcode2m_bbox.add_argument("--viewport-height", type=int, help="Optional Playwright viewport height")
    webcode2m_bbox.add_argument("--normalize-width", type=int, help="Width used to normalize bbox pseudo-HTML")
    webcode2m_bbox.add_argument("--normalize-height", type=int, help="Height used to normalize bbox pseudo-HTML")
    webcode2m_bbox.add_argument("--bbox-html", action="store_true", help="Include WebCode2M bbox-annotated pseudo-HTML")
    webcode2m_bbox.add_argument("--style-list", action="store_true", help="Include WebCode2M style-list view")
    webcode2m_bbox.add_argument("--include-leaves", action="store_true", help="Include leaf nodes in the style-list view")

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

    mobile_overflow = subparsers.add_parser(
        "mobile-overflow-tags",
        help="Emit WebCoderBench-style horizontal overflow tags for a page",
    )
    mobile_overflow.add_argument("html")
    mobile_overflow.add_argument("--viewport-width", type=int, default=390)
    mobile_overflow.add_argument("--viewport-height", type=int, default=844)
    mobile_overflow.add_argument("--threshold-px", type=int, default=0)
    mobile_overflow.add_argument("--include-elements", action="store_true")

    accessibility = subparsers.add_parser(
        "accessibility-control-tags",
        help="Emit control/accessibility tags for rendered controls",
    )
    accessibility.add_argument("html")
    accessibility.add_argument("--viewport-width", type=int, default=1440)
    accessibility.add_argument("--viewport-height", type=int, default=900)
    accessibility.add_argument("--include-elements", action="store_true")

    webcoderbench = subparsers.add_parser(
        "webcoderbench-tags",
        help="Emit a small WebCoderBench-inspired diagnostic tag bundle",
    )
    webcoderbench.add_argument("html")
    webcoderbench.add_argument("--desktop-width", type=int, default=1440)
    webcoderbench.add_argument("--desktop-height", type=int, default=900)
    webcoderbench.add_argument("--mobile-width", type=int, default=390)
    webcoderbench.add_argument("--mobile-height", type=int, default=844)
    webcoderbench.add_argument("--include-elements", action="store_true")

    webcoderbench_visual = subparsers.add_parser(
        "webcoderbench-visual",
        help="Emit WebCoderBench visual-quality local fallback metrics",
    )
    webcoderbench_visual.add_argument("html")
    webcoderbench_visual.add_argument("screenshot")
    webcoderbench_visual.add_argument("--viewport-width", type=int, default=1440)
    webcoderbench_visual.add_argument("--viewport-height", type=int, default=900)
    webcoderbench_visual.add_argument("--include-details", action="store_true")

    presentation_diff = subparsers.add_parser(
        "presentation-diff-tags",
        help="Emit WebSee-style visual diff cluster tags for two screenshots",
    )
    presentation_diff.add_argument("reference")
    presentation_diff.add_argument("candidate")
    presentation_diff.add_argument("--threshold", type=float, default=0.1)
    presentation_diff.add_argument("--min-cluster-area", type=int, default=64)
    presentation_diff.add_argument("--no-clusters", action="store_true")
    presentation_diff.add_argument("--no-resize-candidate", action="store_true")

    websee_localize = subparsers.add_parser(
        "websee-localize",
        help="Map WebSee-style visual diff clusters to candidate DOM elements",
    )
    websee_localize.add_argument("candidate_html")
    websee_localize.add_argument("reference_screenshot")
    websee_localize.add_argument("candidate_screenshot")
    websee_localize.add_argument("--threshold", type=float, default=0.1)
    websee_localize.add_argument("--min-cluster-area", type=int, default=64)
    websee_localize.add_argument("--max-elements-per-cluster", type=int, default=5)
    websee_localize.add_argument("--viewport-width", type=int)
    websee_localize.add_argument("--viewport-height", type=int)

    evaluate_parser = subparsers.add_parser(
        "evaluate",
        help="Run the manifest-aware evaluator on one reference/candidate folder pair",
    )
    evaluate_parser.add_argument("--reference-root", required=True)
    evaluate_parser.add_argument("--reference-manifest", required=True)
    evaluate_parser.add_argument("--candidate-root", required=True)
    evaluate_parser.add_argument("--output-dir", required=True)
    evaluate_parser.add_argument("--capture", action="append", default=None, help="Capture id to run; may be repeated")
    evaluate_parser.add_argument("--skip-vlm", action="store_true")
    evaluate_parser.add_argument("--vlm-model", default="gpt-5.4-mini")
    evaluate_parser.add_argument("--dreamsim-type", default="ensemble")
    evaluate_parser.add_argument("--dreamsim-device", default=None)
    evaluate_parser.add_argument("--dreamsim-cache-dir", default=None)
    evaluate_parser.add_argument("--skip-dreamsim", action="store_true")
    evaluate_parser.add_argument("--visual-block-device", default="cpu")
    evaluate_parser.add_argument("--no-visual-block", action="store_true")

    args = parser.parse_args(argv)
    if args.command == "pair":
        _print_json(score_screenshot_pair(args.reference, args.candidate, include_clip=args.clip))
        return 0
    if args.command == "directory":
        _print_json(score_capture_set(args.reference_dir, args.candidate_dir, include_clip=args.clip))
        return 0
    if args.command == "dreamsim":
        selected_device = _pick_torch_device(args.device)
        _print_json(
            {
                "distance": dreamsim_distance(
                    args.reference,
                    args.candidate,
                    device=selected_device,
                    dreamsim_type=args.dreamsim_type,
                    cache_dir=args.cache_dir,
                ),
                "dreamsim_type": args.dreamsim_type,
                "device": selected_device,
                "requested_device": args.device,
            }
        )
        return 0
    if args.command == "webcode2m-dom":
        _print_json(webcode2m_dom_score(args.reference_html, args.candidate_html))
        return 0
    if args.command == "webcode2m-text":
        _print_json(webcode2m_text_score(args.reference_html, args.candidate_html))
        return 0
    if args.command == "webcode2m-bbox-tree":
        viewport = None
        if args.viewport_width or args.viewport_height:
            if not args.viewport_width or not args.viewport_height:
                parser.error("--viewport-width and --viewport-height must be provided together")
            viewport = (args.viewport_width, args.viewport_height)
        tree = extract_webcode2m_bbox_tree(args.html, viewport=viewport)
        payload: dict[str, Any] = {"tree": tree}
        if tree and args.bbox_html:
            if (args.normalize_width and not args.normalize_height) or (args.normalize_height and not args.normalize_width):
                parser.error("--normalize-width and --normalize-height must be provided together")
            page_size = (
                args.normalize_width or args.viewport_width or 1280,
                args.normalize_height or args.viewport_height or 720,
            )
            payload["bbox_html"] = webcode2m_bbox_tree_to_html(tree, size=page_size)
        if tree and args.style_list:
            payload["style_list"] = webcode2m_bbox_tree_to_style_list(tree, skip_leaf=not args.include_leaves)
        _print_json(payload)
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
    if args.command == "mobile-overflow-tags":
        _print_json(
            mobile_overflow_tags(
                args.html,
                viewport=(args.viewport_width, args.viewport_height),
                threshold_px=args.threshold_px,
                include_elements=args.include_elements,
            )
        )
        return 0
    if args.command == "accessibility-control-tags":
        _print_json(
            accessibility_control_tags(
                args.html,
                viewport=(args.viewport_width, args.viewport_height),
                include_elements=args.include_elements,
            )
        )
        return 0
    if args.command == "webcoderbench-tags":
        _print_json(
            webcoderbench_tags(
                args.html,
                desktop_viewport=(args.desktop_width, args.desktop_height),
                mobile_viewport=(args.mobile_width, args.mobile_height),
                include_elements=args.include_elements,
            )
        )
        return 0
    if args.command == "webcoderbench-visual":
        _print_json(
            webcoderbench_visual_quality_scores(
                args.html,
                args.screenshot,
                viewport=(args.viewport_width, args.viewport_height),
                include_details=args.include_details,
            )
        )
        return 0
    if args.command == "presentation-diff-tags":
        _print_json(
            presentation_diff_tags(
                args.reference,
                args.candidate,
                threshold=args.threshold,
                min_cluster_area=args.min_cluster_area,
                resize_candidate=not args.no_resize_candidate,
                include_clusters=not args.no_clusters,
            )
        )
        return 0
    if args.command == "websee-localize":
        viewport = None
        if args.viewport_width or args.viewport_height:
            if not args.viewport_width or not args.viewport_height:
                parser.error("--viewport-width and --viewport-height must be provided together")
            viewport = (args.viewport_width, args.viewport_height)
        _print_json(
            websee_dom_localization_tags(
                args.candidate_html,
                args.reference_screenshot,
                args.candidate_screenshot,
                threshold=args.threshold,
                min_cluster_area=args.min_cluster_area,
                max_elements_per_cluster=args.max_elements_per_cluster,
                viewport=viewport,
            )
        )
        return 0
    if args.command == "evaluate":
        repo_root = Path(__file__).resolve().parents[1]
        result = evaluate(
            EvaluateConfig(
                reference_root=Path(args.reference_root).resolve(),
                reference_manifest=Path(args.reference_manifest).resolve(),
                candidate_root=Path(args.candidate_root).resolve(),
                output_dir=Path(args.output_dir).resolve(),
                repo_root=repo_root,
                skip_vlm=args.skip_vlm,
                skip_dreamsim=args.skip_dreamsim,
                vlm_model=args.vlm_model,
                dreamsim_type=args.dreamsim_type,
                dreamsim_device=args.dreamsim_device,
                dreamsim_cache_dir=args.dreamsim_cache_dir,
                visual_block_device=args.visual_block_device,
                include_visual_block=not args.no_visual_block,
                capture_filter=set(args.capture or []) or None,
            )
        )
        print_functional_status(result)
        return 0
    parser.error(f"Unknown command: {args.command}")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
