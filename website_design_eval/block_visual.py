from __future__ import annotations

import importlib.util
import os
import subprocess
import sys
import tempfile
import types
from copy import deepcopy
from difflib import SequenceMatcher
from pathlib import Path
from typing import Any

from PIL import Image


PathLike = str | os.PathLike[str]


_PACKAGE_NAME = "_website_design_eval_webcode2m_design2code"
_VISUAL_SCORE_MODULE = None
_OPEN_CLIP_CACHE: dict[tuple[str, str], tuple[Any, Any]] = {}


def _project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def _metrics_dir() -> Path:
    return (
        _project_root()
        / "research"
        / "source-repos"
        / "naturalcc"
        / "examples"
        / "webcode2m"
        / "scripts"
        / "evaluation"
        / "design2code"
    )


def _html2screenshot_script() -> Path:
    return _metrics_dir().parent / "html2screenshot.py"


def _install_open_clip_compat() -> None:
    """Expose a tiny old-`clip` compatible module backed by open-clip-torch."""

    if "clip" in sys.modules and getattr(sys.modules["clip"], "_website_design_eval_compat", False):
        return

    compat = types.ModuleType("clip")
    compat._website_design_eval_compat = True

    def load(name: str = "ViT-B/32", device: str = "cpu", *_args: Any, **_kwargs: Any) -> tuple[Any, Any]:
        import open_clip

        # OpenAI CLIP's ViT-B/32 maps most closely to open_clip's quickgelu variant.
        model_name = "ViT-B-32-quickgelu" if name == "ViT-B/32" else name.replace("/", "-")
        key = (model_name, device)
        if key not in _OPEN_CLIP_CACHE:
            model, _, preprocess = open_clip.create_model_and_transforms(
                model_name,
                pretrained="openai",
                device=device,
            )
            model.eval()
            _OPEN_CLIP_CACHE[key] = (model, preprocess)
        return _OPEN_CLIP_CACHE[key]

    compat.load = load
    sys.modules["clip"] = compat


def _load_research_visual_score() -> Any:
    global _VISUAL_SCORE_MODULE
    if _VISUAL_SCORE_MODULE is not None:
        return _VISUAL_SCORE_MODULE

    metrics_dir = _metrics_dir()
    visual_score_path = metrics_dir / "visual_score.py"
    if not visual_score_path.exists():
        raise FileNotFoundError(f"Missing research visual_score.py: {visual_score_path}")

    _install_open_clip_compat()

    package = types.ModuleType(_PACKAGE_NAME)
    package.__path__ = [str(metrics_dir)]
    sys.modules[_PACKAGE_NAME] = package

    spec = importlib.util.spec_from_file_location(f"{_PACKAGE_NAME}.visual_score", visual_score_path)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load research visual score module from {visual_score_path}")

    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)

    utils = sys.modules[f"{_PACKAGE_NAME}.ocr_free_utils"]
    module.get_blocks_ocr_free = _build_get_blocks_ocr_free(utils)
    _VISUAL_SCORE_MODULE = module
    return module


def _load_ocr_free_utils() -> Any:
    _load_research_visual_score()
    return sys.modules[f"{_PACKAGE_NAME}.ocr_free_utils"]


def _build_get_blocks_ocr_free(utils: Any) -> Any:
    def get_blocks_ocr_free(html_path: PathLike, image_path: PathLike, tmp_dir: PathLike) -> list[dict[str, Any]]:
        p_html, p_html_1, p_png, p_png_1 = utils.get_itermediate_names(html_path, tmp_dir)
        cleanup_paths = [Path(p_html), Path(p_html_1), Path(p_png), Path(p_png_1)]

        try:
            utils.process_html(html_path, p_html)
            utils.process_html(html_path, p_html_1, offset=50)

            script = _html2screenshot_script()
            for html, png in ((p_html, p_png), (p_html_1, p_png_1)):
                subprocess.run(
                    [sys.executable, str(script), "--input", str(html), "--output", str(png)],
                    check=True,
                    cwd=_project_root(),
                )

            different_pixels = utils.find_different_pixels(p_png, p_png_1)
            if different_pixels is None:
                print(f"[Warning] Unable to get pixels with different colors from {p_png}, {p_png_1}...")
                return []

            html_text_color_tree = utils.flatten_tree(utils.extract_text_with_color(p_html))
            try:
                return utils.get_blocks_from_image_diff_pixels(
                    str(image_path),
                    str(p_png),
                    html_text_color_tree,
                    different_pixels,
                )
            except Exception:
                print(f"[Warning] Unable to get blocks from {p_png}...")
                return []
        finally:
            for path in cleanup_paths:
                path.unlink(missing_ok=True)

    return get_blocks_ocr_free


VISUAL_BLOCK_RECOLOR_SCRIPT = """
({ offset }) => {
  const rgbToHex = (rgb) => rgb.map((value) => value.toString(16).padStart(2, '0').toUpperCase()).join('');
  const colors = [];
  for (let r = 10; r <= 250; r += 16) {
    for (let g = 10; g <= 250; g += 16) {
      for (let b = 10; b <= 250; b += 16) {
        colors.push(rgbToHex([(r + offset) % 256, (g + offset) % 256, (b + offset) % 256]));
      }
    }
  }
  const popColor = () => {
    const color = colors.pop();
    if (!color) throw new Error('visual block color pool exhausted');
    return `#${color}`;
  };
  const textTags = 'p,h1,h2,h3,h4,h5,h6,div,span,a,b,li,table,td,th,button,footer,header,figcaption';
  for (const el of Array.from(document.querySelectorAll('*'))) {
    el.style.setProperty('background-color', 'rgba(255, 255, 255, 0.0)', 'important');
  }
  for (const el of Array.from(document.querySelectorAll(textTags))) {
    const color = popColor();
    el.setAttribute('data-wde-visual-block-color', color);
    el.style.setProperty('color', color, 'important');
    el.style.setProperty('opacity', '1.0', 'important');
  }

  const directColor = (el) => el.getAttribute?.('data-wde-visual-block-color') || '';
  const flatten = [];
  const walk = (node, parentColor) => {
    if (node.nodeType === Node.COMMENT_NODE) return;
    if (node.nodeType === Node.TEXT_NODE) {
      const text = (node.textContent || '').trim();
      if (text) flatten.push([text, parentColor]);
      return;
    }
    if (node.nodeType !== Node.ELEMENT_NODE) return;
    const color = directColor(node) || parentColor;
    for (const child of Array.from(node.childNodes)) walk(child, color);
  };
  if (document.body) walk(document.body, '#000000');
  return flatten;
}
"""


def _round(value: Any, digits: int = 6) -> float:
    return round(float(value), digits)


def _block_area(block: dict[str, Any]) -> float:
    bbox = block["bbox"]
    return float(bbox[2] * bbox[3])


def _block_center(block: dict[str, Any]) -> tuple[float, float]:
    x, y, width, height = block["bbox"]
    return float(x + width / 2), float(y + height / 2)


def _block_payload(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": str(block.get("text", "")),
        "bbox": [_round(value) for value in block.get("bbox", [])],
        "color": [int(value) for value in block.get("color", [])],
        "area": _round(_block_area(block)),
    }


def _block_artifact_payload(block: dict[str, Any]) -> dict[str, Any]:
    return {
        "text": str(block.get("text", "")),
        "bbox": [float(value) for value in block.get("bbox", [])],
        "color": [int(value) for value in block.get("color", [])],
    }


def _pixel_bbox(bbox: list[float] | tuple[float, ...], image_size: tuple[int, int]) -> tuple[int, int, int, int] | None:
    image_width, image_height = image_size
    x_ratio, y_ratio, width_ratio, height_ratio = bbox
    left = max(0, min(image_width, int(round(x_ratio * image_width))))
    top = max(0, min(image_height, int(round(y_ratio * image_height))))
    right = max(left, min(image_width, int(round((x_ratio + width_ratio) * image_width))))
    bottom = max(top, min(image_height, int(round((y_ratio + height_ratio) * image_height))))
    if right <= left or bottom <= top:
        return None
    return left, top, right, bottom


def _crop_block(image: Image.Image, bbox: list[float]) -> Image.Image | None:
    pixel_bbox = _pixel_bbox(bbox, image.size)
    if pixel_bbox is None:
        return None
    return image.crop(pixel_bbox)


def _score_block_pixelmatch(
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    matched_pairs: list[dict[str, Any]],
    *,
    coverage_score: float,
    threshold: float = 0.1,
) -> dict[str, Any]:
    from .scoring import pixelmatch_score

    reference_image = Image.open(reference_screenshot).convert("RGB")
    candidate_image = Image.open(candidate_screenshot).convert("RGB")

    weighted_score = 0.0
    weight_total = 0.0
    scored_pairs = 0

    for pair in matched_pairs:
        reference_crop = _crop_block(reference_image, pair["reference"]["bbox"])
        candidate_crop = _crop_block(candidate_image, pair["candidate"]["bbox"])
        if reference_crop is None or candidate_crop is None:
            pair["pixelmatch"] = {"score": 0.0, "skipped": True}
            continue

        pixelmatch = pixelmatch_score(reference_crop, candidate_crop, threshold=threshold)
        pair["pixelmatch"] = pixelmatch
        weight = max(pair["reference"]["area"], 0.0)
        weighted_score += float(pixelmatch["score"]) * weight
        weight_total += weight
        scored_pairs += 1

    matched_score = weighted_score / weight_total if weight_total > 0 else 0.0
    coverage_adjusted_score = matched_score * coverage_score

    return {
        "score": _round(coverage_adjusted_score),
        "matched_pixelmatch": _round(matched_score),
        "coverage_adjusted_score": _round(coverage_adjusted_score),
        "coverage_score": _round(coverage_score),
        "pair_count": len(matched_pairs),
        "scored_pair_count": scored_pairs,
        "weighted_reference_area": _round(weight_total),
        "threshold": threshold,
    }


def _bbox_iou(reference_bbox: list[float], candidate_bbox: list[float]) -> float:
    ref_left, ref_top, ref_width, ref_height = reference_bbox
    cand_left, cand_top, cand_width, cand_height = candidate_bbox
    ref_right = ref_left + ref_width
    ref_bottom = ref_top + ref_height
    cand_right = cand_left + cand_width
    cand_bottom = cand_top + cand_height

    intersection_width = max(0.0, min(ref_right, cand_right) - max(ref_left, cand_left))
    intersection_height = max(0.0, min(ref_bottom, cand_bottom) - max(ref_top, cand_top))
    intersection_area = intersection_width * intersection_height
    union_area = ref_width * ref_height + cand_width * cand_height - intersection_area
    if union_area <= 0:
        return 0.0
    return intersection_area / union_area


def _bbox_area_similarity(reference_bbox: list[float], candidate_bbox: list[float]) -> float:
    reference_area = max(reference_bbox[2] * reference_bbox[3], 0.0)
    candidate_area = max(candidate_bbox[2] * candidate_bbox[3], 0.0)
    if reference_area <= 0 or candidate_area <= 0:
        return 0.0
    return min(reference_area, candidate_area) / max(reference_area, candidate_area)


def _score_bbox_geometry(
    matched_pairs: list[dict[str, Any]],
    *,
    coverage_score: float,
) -> dict[str, Any]:
    weighted_iou = 0.0
    weighted_area = 0.0
    weighted_center = 0.0
    weighted_area_similarity = 0.0
    weighted_bbox_score = 0.0

    for pair in matched_pairs:
        reference_bbox = pair["reference"]["bbox"]
        candidate_bbox = pair["candidate"]["bbox"]
        iou = _bbox_iou(reference_bbox, candidate_bbox)
        area_similarity = _bbox_area_similarity(reference_bbox, candidate_bbox)
        center_similarity = float(pair["position"])
        bbox_score = (iou + area_similarity + center_similarity) / 3
        pair["bbox_geometry"] = {
            "iou": _round(iou),
            "area_similarity": _round(area_similarity),
            "center_similarity": _round(center_similarity),
            "score": _round(bbox_score),
        }

        weight = max(float(pair["reference"]["area"]), 0.0)
        weighted_iou += iou * weight
        weighted_area_similarity += area_similarity * weight
        weighted_center += center_similarity * weight
        weighted_bbox_score += bbox_score * weight
        weighted_area += weight

    if weighted_area <= 0:
        matched_bbox_score = 0.0
        matched_iou = 0.0
        matched_area_similarity = 0.0
        matched_center_similarity = 0.0
    else:
        matched_bbox_score = weighted_bbox_score / weighted_area
        matched_iou = weighted_iou / weighted_area
        matched_area_similarity = weighted_area_similarity / weighted_area
        matched_center_similarity = weighted_center / weighted_area

    coverage_adjusted_score = matched_bbox_score * coverage_score
    return {
        "score": _round(coverage_adjusted_score),
        "coverage_adjusted_score": _round(coverage_adjusted_score),
        "matched_bbox_score": _round(matched_bbox_score),
        "matched_iou": _round(matched_iou),
        "matched_area_similarity": _round(matched_area_similarity),
        "matched_center_similarity": _round(matched_center_similarity),
        "coverage_score": _round(coverage_score),
        "pair_count": len(matched_pairs),
        "weighted_reference_area": _round(weighted_area),
    }


def _run_visual_block_analysis_from_blocks(
    module: Any,
    reference_blocks: list[dict[str, Any]],
    candidate_blocks: list[dict[str, Any]],
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    *,
    device: str,
    debug: bool,
    include_masked_clip: bool = True,
) -> dict[str, Any]:
    if include_masked_clip and module.CLIP_MODEL is None:
        module.CLIP_MODEL, module.CLIP_PREPROCESS = module.clip.load("ViT-B/32", device=device)

    reference_blocks = module.merge_blocks_by_bbox(reference_blocks)

    if len(candidate_blocks) == 0 or len(reference_blocks) == 0:
        return {
            "score": 0.0,
            "weighted_area": 0.0,
            "size": 0.0,
            "text": 0.0,
            "position": 0.0,
            "text_color": 0.0,
            "masked_clip": 0.0 if include_masked_clip else None,
            "matched_pairs": [],
            "unmatched_reference_blocks": [_block_payload(block) for block in reference_blocks],
            "unmatched_candidate_blocks": [_block_payload(block) for block in candidate_blocks],
            "reference_block_count": len(reference_blocks),
            "candidate_block_count": len(candidate_blocks),
            "matched_pair_count": 0,
        }

    candidate_blocks = module.merge_blocks_by_bbox(candidate_blocks)
    candidate_blocks_m, reference_blocks_m, matching = module.find_possible_merge(
        candidate_blocks,
        deepcopy(reference_blocks),
        0.1,
        1,
        debug=debug,
    )

    filtered_matching = []
    for candidate_index, reference_index in matching:
        text_similarity = SequenceMatcher(
            None,
            candidate_blocks_m[candidate_index]["text"],
            reference_blocks_m[reference_index]["text"],
        ).ratio()
        if text_similarity < 0.5:
            continue
        filtered_matching.append((candidate_index, reference_index, text_similarity))

    candidate_indices = {item[0] for item in filtered_matching}
    reference_indices = {item[1] for item in filtered_matching}

    unmatched_candidate_area = sum(
        _block_area(block)
        for index, block in enumerate(candidate_blocks_m)
        if index not in candidate_indices
    )
    unmatched_reference_area = sum(
        _block_area(block)
        for index, block in enumerate(reference_blocks_m)
        if index not in reference_indices
    )

    sum_areas = [unmatched_candidate_area + unmatched_reference_area]
    matched_areas = []
    matched_text_scores = []
    position_scores = []
    text_color_scores = []
    matched_pairs = []

    for candidate_index, reference_index, text_similarity in filtered_matching:
        candidate_block = candidate_blocks_m[candidate_index]
        reference_block = reference_blocks_m[reference_index]
        sum_block_area = _block_area(candidate_block) + _block_area(reference_block)

        candidate_center = _block_center(candidate_block)
        reference_center = _block_center(reference_block)
        position_similarity = 1 - module.calculate_distance_max_1d(
            candidate_center[0],
            candidate_center[1],
            reference_center[0],
            reference_center[1],
        )
        text_color_similarity = module.color_similarity_ciede2000(
            candidate_block["color"],
            reference_block["color"],
        )

        sum_areas.append(sum_block_area)
        matched_areas.append(sum_block_area)
        matched_text_scores.append(text_similarity)
        position_scores.append(position_similarity)
        text_color_scores.append(text_color_similarity)
        matched_pairs.append(
            {
                "candidate_index": int(candidate_index),
                "reference_index": int(reference_index),
                "reference": _block_payload(reference_block),
                "candidate": _block_payload(candidate_block),
                "text": _round(text_similarity),
                "position": _round(position_similarity),
                "text_color": _round(text_color_similarity),
                "area_weight": _round(sum_block_area),
            }
        )

    if matched_areas:
        weighted_area = float(module.np.sum(sum_areas))
        size = float(module.np.sum(matched_areas) / module.np.sum(sum_areas))
        text = float(module.np.mean(matched_text_scores))
        position = float(module.np.mean(position_scores))
        text_color = float(module.np.mean(text_color_scores))
        if include_masked_clip:
            masked_clip: float | None = float(
                module.calculate_clip_similarity_with_blocks(
                    str(candidate_screenshot),
                    str(reference_screenshot),
                    candidate_blocks,
                    reference_blocks,
                    device,
                )
            )
            score = 0.2 * (size + text + position + text_color + masked_clip)
        else:
            masked_clip = None
            score = 0.25 * (size + text + position + text_color)
    else:
        weighted_area = 0.0
        size = 0.0
        text = 0.0
        position = 0.0
        text_color = 0.0
        if include_masked_clip:
            masked_clip = float(
                module.calculate_clip_similarity_with_blocks(
                    str(candidate_screenshot),
                    str(reference_screenshot),
                    candidate_blocks,
                    reference_blocks,
                    device,
                )
            )
            score = 0.2 * masked_clip
        else:
            masked_clip = None
            score = 0.0

    return {
        "score": score,
        "weighted_area": weighted_area,
        "size": size,
        "text": text,
        "position": position,
        "text_color": text_color,
        "masked_clip": masked_clip,
        "matched_pairs": matched_pairs,
        "unmatched_reference_blocks": [
            _block_payload(block)
            for index, block in enumerate(reference_blocks_m)
            if index not in reference_indices
        ],
        "unmatched_candidate_blocks": [
            _block_payload(block)
            for index, block in enumerate(candidate_blocks_m)
            if index not in candidate_indices
        ],
        "reference_block_count": len(reference_blocks_m),
        "candidate_block_count": len(candidate_blocks_m),
        "matched_pair_count": len(matched_pairs),
    }


def _run_visual_block_analysis(
    module: Any,
    reference_html: PathLike,
    candidate_html: PathLike,
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    work_dir: Path,
    *,
    device: str,
    debug: bool,
    include_masked_clip: bool = True,
) -> dict[str, Any]:
    candidate_blocks = module.get_blocks_ocr_free(str(candidate_html), str(candidate_screenshot), str(work_dir))
    reference_blocks = module.get_blocks_ocr_free(str(reference_html), str(reference_screenshot), str(work_dir))
    return _run_visual_block_analysis_from_blocks(
        module,
        reference_blocks,
        candidate_blocks,
        reference_screenshot,
        candidate_screenshot,
        device=device,
        debug=debug,
        include_masked_clip=include_masked_clip,
    )


def _format_visual_block_result(
    analysis: dict[str, Any],
    *,
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    device: str,
    include_pairs: bool,
    include_block_pixelmatch: bool,
    pixelmatch_threshold: float,
    source: str,
    artifact_source: str,
) -> dict[str, Any]:
    result = {
        "score": _round(analysis["score"]),
        "weighted_area": _round(analysis["weighted_area"]),
        "size": _round(analysis["size"]),
        "text": _round(analysis["text"]),
        "position": _round(analysis["position"]),
        "text_color": _round(analysis["text_color"]),
        "masked_clip": _round(analysis["masked_clip"]) if analysis.get("masked_clip") is not None else None,
        "masked_clip_skipped": analysis.get("masked_clip") is None,
        "reference_block_count": analysis["reference_block_count"],
        "candidate_block_count": analysis["candidate_block_count"],
        "matched_pair_count": analysis["matched_pair_count"],
        "unmatched_reference_count": len(analysis["unmatched_reference_blocks"]),
        "unmatched_candidate_count": len(analysis["unmatched_candidate_blocks"]),
        "device": device,
        "source": source,
        "artifact_source": artifact_source,
    }
    if include_block_pixelmatch:
        result["block_pixelmatch"] = _score_block_pixelmatch(
            reference_screenshot,
            candidate_screenshot,
            analysis["matched_pairs"],
            coverage_score=float(analysis["size"]),
            threshold=pixelmatch_threshold,
        )
    if include_pairs:
        result["matched_pairs"] = analysis["matched_pairs"]
        result["unmatched_reference_blocks"] = analysis["unmatched_reference_blocks"]
        result["unmatched_candidate_blocks"] = analysis["unmatched_candidate_blocks"]
    return result


def visual_block_score(
    reference_html: PathLike,
    candidate_html: PathLike,
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    *,
    tmp_dir: PathLike | None = None,
    device: str = "cpu",
    debug: bool = False,
    include_pairs: bool = False,
    include_block_pixelmatch: bool = False,
    pixelmatch_threshold: float = 0.1,
    include_masked_clip: bool = True,
) -> dict[str, Any]:
    """Run the checked-in WebCode2M/Design2Code OCR-free visual block metric.

    The research implementation is intentionally kept under `research/`. This
    adapter gives the project a stable JSON-shaped API while preserving the
    upstream scoring logic for experimentation.
    """

    module = _load_research_visual_score()

    def run(work_dir: Path) -> dict[str, Any]:
        work_dir.mkdir(parents=True, exist_ok=True)
        analysis = _run_visual_block_analysis(
            module,
            reference_html,
            candidate_html,
            reference_screenshot,
            candidate_screenshot,
            work_dir,
            device=device,
            debug=debug,
            include_masked_clip=include_masked_clip,
        )
        return _format_visual_block_result(
            analysis,
            reference_screenshot=reference_screenshot,
            candidate_screenshot=candidate_screenshot,
            device=device,
            include_pairs=include_pairs,
            include_block_pixelmatch=include_block_pixelmatch,
            pixelmatch_threshold=pixelmatch_threshold,
            source="research/source-repos/naturalcc/examples/webcode2m/scripts/evaluation/design2code",
            artifact_source="legacy_file_render",
        )

    if tmp_dir is not None:
        return run(Path(tmp_dir))

    with tempfile.TemporaryDirectory(prefix="visual-block-") as directory:
        return run(Path(directory))


def extract_visual_blocks_from_playwright_page(
    page: Any,
    origin_screenshot: PathLike,
    *,
    screenshot_options: dict[str, Any],
    tmp_dir: PathLike | None = None,
) -> dict[str, Any]:
    """Extract OCR-free visual blocks from an already replayed Playwright page.

    The page is intentionally expected to be isolated: this function mutates text
    colors in-place to mirror WebCode2M's OCR-free render IO.
    """

    utils = _load_ocr_free_utils()

    def run(work_dir: Path) -> dict[str, Any]:
        work_dir.mkdir(parents=True, exist_ok=True)
        p_png = work_dir / "visual_block_recolor_0.png"
        p_png_1 = work_dir / "visual_block_recolor_50.png"
        html_text_color_tree = page.evaluate(VISUAL_BLOCK_RECOLOR_SCRIPT, {"offset": 0})
        page.screenshot(**{**screenshot_options, "path": str(p_png)})
        page.evaluate(VISUAL_BLOCK_RECOLOR_SCRIPT, {"offset": 50})
        page.screenshot(**{**screenshot_options, "path": str(p_png_1)})

        different_pixels = utils.find_different_pixels(p_png, p_png_1)
        if different_pixels is None:
            return {
                "status": "empty",
                "reason": "no_different_pixels",
                "blocks": [],
                "block_count": 0,
                "artifact_source": "isolated_playwright_manifest_state",
            }
        blocks = utils.get_blocks_from_image_diff_pixels(
            str(origin_screenshot),
            str(p_png),
            html_text_color_tree,
            different_pixels,
        )
        return {
            "status": "ok",
            "reason": None,
            "blocks": [_block_artifact_payload(block) for block in blocks],
            "block_count": len(blocks),
            "artifact_source": "isolated_playwright_manifest_state",
        }

    if tmp_dir is not None:
        return run(Path(tmp_dir))

    with tempfile.TemporaryDirectory(prefix="visual-block-page-") as directory:
        return run(Path(directory))


def visual_block_score_from_blocks(
    reference_blocks: list[dict[str, Any]],
    candidate_blocks: list[dict[str, Any]],
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    *,
    device: str = "cpu",
    debug: bool = False,
    include_pairs: bool = False,
    include_block_pixelmatch: bool = False,
    pixelmatch_threshold: float = 0.1,
    artifact_source: str = "isolated_playwright_manifest_state",
    include_masked_clip: bool = True,
) -> dict[str, Any]:
    module = _load_research_visual_score()
    analysis = _run_visual_block_analysis_from_blocks(
        module,
        deepcopy(reference_blocks),
        deepcopy(candidate_blocks),
        reference_screenshot,
        candidate_screenshot,
        device=device,
        debug=debug,
        include_masked_clip=include_masked_clip,
    )
    return _format_visual_block_result(
        analysis,
        reference_screenshot=reference_screenshot,
        candidate_screenshot=candidate_screenshot,
        device=device,
        include_pairs=include_pairs,
        include_block_pixelmatch=include_block_pixelmatch,
        pixelmatch_threshold=pixelmatch_threshold,
        source="research/source-repos/naturalcc/examples/webcode2m/scripts/evaluation/design2code",
        artifact_source=artifact_source,
    )


def element_block_pixelmatch_score(
    reference_html: PathLike,
    candidate_html: PathLike,
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    *,
    tmp_dir: PathLike | None = None,
    device: str = "cpu",
    debug: bool = False,
    include_pairs: bool = False,
    pixelmatch_threshold: float = 0.1,
) -> dict[str, Any]:
    result = visual_block_score(
        reference_html,
        candidate_html,
        reference_screenshot,
        candidate_screenshot,
        tmp_dir=tmp_dir,
        device=device,
        debug=debug,
        include_pairs=include_pairs,
        include_block_pixelmatch=True,
        pixelmatch_threshold=pixelmatch_threshold,
    )
    payload = {
        "score": result["block_pixelmatch"]["score"],
        "matched_pixelmatch": result["block_pixelmatch"]["matched_pixelmatch"],
        "coverage_adjusted_score": result["block_pixelmatch"]["coverage_adjusted_score"],
        "coverage_score": result["block_pixelmatch"]["coverage_score"],
        "pair_count": result["block_pixelmatch"]["pair_count"],
        "scored_pair_count": result["block_pixelmatch"]["scored_pair_count"],
        "visual_block": {
            key: result[key]
            for key in (
                "score",
                "size",
                "text",
                "position",
                "text_color",
                "masked_clip",
                "reference_block_count",
                "candidate_block_count",
                "matched_pair_count",
                "unmatched_reference_count",
                "unmatched_candidate_count",
            )
        },
    }
    if include_pairs:
        payload["matched_pairs"] = result["matched_pairs"]
        payload["unmatched_reference_blocks"] = result["unmatched_reference_blocks"]
        payload["unmatched_candidate_blocks"] = result["unmatched_candidate_blocks"]
    return payload


def bbox_geometry_score(
    reference_html: PathLike,
    candidate_html: PathLike,
    reference_screenshot: PathLike,
    candidate_screenshot: PathLike,
    *,
    tmp_dir: PathLike | None = None,
    device: str = "cpu",
    debug: bool = False,
    include_pairs: bool = False,
) -> dict[str, Any]:
    result = visual_block_score(
        reference_html,
        candidate_html,
        reference_screenshot,
        candidate_screenshot,
        tmp_dir=tmp_dir,
        device=device,
        debug=debug,
        include_pairs=True,
    )
    geometry = _score_bbox_geometry(
        result["matched_pairs"],
        coverage_score=float(result["size"]),
    )
    payload = {
        **geometry,
        "visual_block": {
            key: result[key]
            for key in (
                "score",
                "size",
                "text",
                "position",
                "text_color",
                "masked_clip",
                "reference_block_count",
                "candidate_block_count",
                "matched_pair_count",
                "unmatched_reference_count",
                "unmatched_candidate_count",
            )
        },
    }
    if include_pairs:
        payload["matched_pairs"] = result["matched_pairs"]
        payload["unmatched_reference_blocks"] = result["unmatched_reference_blocks"]
        payload["unmatched_candidate_blocks"] = result["unmatched_candidate_blocks"]
    return payload
