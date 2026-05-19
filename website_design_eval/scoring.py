from __future__ import annotations

import base64
import json
import os
import re
from pathlib import Path
from typing import Any

import numpy as np
from bs4 import BeautifulSoup
from PIL import Image
from skimage.metrics import structural_similarity

PathLike = str | os.PathLike[str]

_CLIP_CACHE: dict[tuple[str, str, str], tuple[Any, Any]] = {}
_DREAMSIM_CACHE: dict[tuple[str, str, str], tuple[Any, Any]] = {}

WEB2CODE_DIMENSION_NAMES = [
    "layout_consistency",
    "element_alignment",
    "proportional_accuracy",
    "visual_harmony",
    "color_scheme_aesthetic_match",
    "aesthetic_resemblance",
    "font_characteristics_consistency",
    "textual_content_match",
    "numeric_special_character_accuracy",
    "user_interface_consistency",
]

WEB2CODE_GROUP_INDICES = {
    "visual_structure_and_alignment": [0, 1, 2, 3],
    "color_and_aesthetic_design": [4, 5],
    "textual_and_content_consistency": [6, 7, 8],
    "user_interface_and_interactivity": [9],
}

WEB2CODE_VLM_PROMPT = """
You are an advanced AI model equipped with OCR and image processing capabilities, capable of analyzing visual elements in detail.

Your task is to assess two webpage images and output a score between 0 and 10 for each of the following questions.
If the answer to a question is a definite YES, output a score of 10, signifying perfect similarity.
Conversely, a definite NO should yield a score of 0, indicating no similarity.
For answers that fall in between, assign a score accordingly, where a higher number indicates a greater degree of similarity.
Example contexts are provided for clarity. Examples provide the idea, but you can output any number in the 0-10 range accordingly.
DO NOT give a score of 10 for any category unless the two images are identical for that category.

1. Layout Consistency (Score: 0-10): Does the placement of headers, footers, and sidebars match in both webpages? (e.g., A score of 10 for identical layouts, 5 for similar but not exact placements, and 0 for completely different layouts.)
2. Element Alignment (Score: 0-10): Are elements like images, buttons, and text boxes aligned similarly on both pages? (e.g., A score of 10 for perfectly aligned elements, 6 for slight misalignments, and 0 for major misalignments.)
3. Proportional Accuracy (Score: 0-10): Do the sizes and aspect ratios of images, buttons, and text boxes appear consistent across both pages? (e.g., A score of 10 for exact proportions, 4 for noticeable size differences, and 0 for drastic inconsistencies.)
4. Visual Harmony (Score: 0-10): Do both webpages exhibit a similar level of visual harmony and balance in their design? (e.g., A score of 10 for harmonious designs, 5 for some dissonance, and 0 for clashing designs.)
5. Color Scheme and Aesthetic Match (Score: 0-10): How closely do the color schemes of the two webpages align in terms of background and text colors? Evaluate the similarity in hues, saturation, and overall color aesthetics. (e.g., A score of 10 for perfectly matching color schemes, including identical hues and saturation levels, 6 for similar color palettes with minor variations, and 0 for starkly different color schemes that create entirely different visual impacts.)
6. Aesthetic Resemblance (Score: 0-10): Is the overall aesthetic appeal (modern, minimalistic, traditional, etc.) similar on both pages? (e.g., A score of 10 for identical aesthetics, 4 for somewhat similar but distinguishable styles, and 0 for completely different aesthetics.)
7. Font Characteristics and Consistency (Score: 0-10): Assess the degree of consistency in font attributes across both webpages. This includes not only the font type and size but also the nuances of font style (italic, bold) and weight (light, regular, bold). (e.g., A score of 10 for complete uniformity in font type, size, style, and weight across both pages, 5 for consistency in font type and size but variations in style or weight, and 0 for wide disparities in font type, size, style, or weight, leading to a distinctly different textual appearance.)
8. Textual Content Match (Score: 0-10): Do the words and sentences match between the two webpages? (e.g., A score of 10 for identical text, 5 for some similar paragraphs or sections, and 0 for completely different textual content.)
9. Numeric and Special Character Accuracy (Score: 0-10): Are numbers, dates, and special characters (like email addresses) consistent between the two pages? (e.g., A score of 10 for exact matches, 6 for minor discrepancies, and 0 for major differences.)
10. User Interface Consistency (Score: 0-10): Do the user interface elements (like menus, buttons, and forms) on both pages share a similar design language and appearance? (e.g., A score of 10 for identical UI elements, 6 for slight design variations, and 0 for completely different UI designs.)

Return only a JSON object with this exact shape:
{"scores":[0,0,0,0,0,0,0,0,0,0]}

The scores array must contain exactly 10 numbers in the same order as the questions above. Do not include explanations or additional keys.
""".strip()


def _read_text(path_or_text: PathLike | str) -> str:
    if isinstance(path_or_text, os.PathLike):
        return Path(path_or_text).read_text(encoding="utf-8", errors="ignore")
    try:
        path = Path(path_or_text)
        if "\n" not in path_or_text and len(path_or_text) < 512 and path.exists():
            return path.read_text(encoding="utf-8", errors="ignore")
    except OSError:
        pass
    return str(path_or_text)


def _load_rgb(path_or_image: PathLike | Image.Image) -> Image.Image:
    if isinstance(path_or_image, Image.Image):
        return path_or_image.convert("RGB")
    return Image.open(path_or_image).convert("RGB")


def _load_rgba(path_or_image: PathLike | Image.Image) -> Image.Image:
    if isinstance(path_or_image, Image.Image):
        return path_or_image.convert("RGBA")
    return Image.open(path_or_image).convert("RGBA")


def _resize_pair(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    mode: str = "RGB",
    resize_candidate: bool = True,
) -> tuple[Image.Image, Image.Image]:
    loader = _load_rgba if mode == "RGBA" else _load_rgb
    ref = loader(reference)
    cand = loader(candidate)
    if resize_candidate and cand.size != ref.size:
        cand = cand.resize(ref.size, Image.Resampling.LANCZOS)
    return ref, cand


def _dimension_match_score(reference_value: int, candidate_value: int) -> float:
    if reference_value <= 0 or candidate_value <= 0:
        return 0.0
    return min(reference_value, candidate_value) / max(reference_value, candidate_value)


def screenshot_size_match_score(reference: PathLike | Image.Image, candidate: PathLike | Image.Image) -> dict[str, Any]:
    """Compare screenshot canvas dimensions before any resizing."""

    ref = _load_rgb(reference)
    cand = _load_rgb(candidate)
    reference_width, reference_height = ref.size
    candidate_width, candidate_height = cand.size
    reference_area = reference_width * reference_height
    candidate_area = candidate_width * candidate_height

    width_score = _dimension_match_score(reference_width, candidate_width)
    height_score = _dimension_match_score(reference_height, candidate_height)
    area_score = _dimension_match_score(reference_area, candidate_area)
    reference_aspect = reference_width / reference_height if reference_height else 0.0
    candidate_aspect = candidate_width / candidate_height if candidate_height else 0.0
    aspect_ratio_score = (
        min(reference_aspect, candidate_aspect) / max(reference_aspect, candidate_aspect)
        if reference_aspect > 0 and candidate_aspect > 0
        else 0.0
    )

    return {
        "score": round(float(width_score * height_score), 6),
        "width_score": round(float(width_score), 6),
        "height_score": round(float(height_score), 6),
        "area_score": round(float(area_score), 6),
        "aspect_ratio_score": round(float(aspect_ratio_score), 6),
        "reference": {
            "width": reference_width,
            "height": reference_height,
            "area": reference_area,
            "aspect_ratio": round(float(reference_aspect), 6),
        },
        "candidate": {
            "width": candidate_width,
            "height": candidate_height,
            "area": candidate_area,
            "aspect_ratio": round(float(candidate_aspect), 6),
        },
        "width_ratio": round(float(candidate_width / reference_width), 6) if reference_width else None,
        "height_ratio": round(float(candidate_height / reference_height), 6) if reference_height else None,
        "area_ratio": round(float(candidate_area / reference_area), 6) if reference_area else None,
    }


def _as_rgb_arrays(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    resize_candidate: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    ref, cand = _resize_pair(reference, candidate, mode="RGB", resize_candidate=resize_candidate)
    return np.asarray(ref), np.asarray(cand)


def _load_cv2_bgr(path_or_image: PathLike | Image.Image) -> np.ndarray:
    import cv2

    if isinstance(path_or_image, Image.Image):
        rgb = np.asarray(path_or_image.convert("RGB"))
        return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)

    image = cv2.imread(str(path_or_image))
    if image is None:
        raise FileNotFoundError(f"Unable to read image with cv2: {path_or_image}")
    return image


def _as_webcode2m_bgr_arrays(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    resize_candidate: bool = True,
) -> tuple[np.ndarray, np.ndarray]:
    import cv2

    ref = _load_cv2_bgr(reference)
    cand = _load_cv2_bgr(candidate)
    if resize_candidate and cand.shape != ref.shape:
        cand = cv2.resize(cand, (ref.shape[1], ref.shape[0]), interpolation=cv2.INTER_LANCZOS4)
    return ref, cand


def _as_designbench_arrays(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    max_size: int = 512,
) -> tuple[np.ndarray, np.ndarray]:
    image1 = _load_rgb(reference)
    image2 = _load_rgb(candidate)
    width1, height1 = image1.size
    width2, height2 = image2.size
    new_width = max(width1, width2)
    new_height = max(height1, height2)

    def pad_image(image: Image.Image) -> Image.Image:
        random_padding = np.random.randint(0, 256, (new_height, new_width, 3), dtype=np.uint8)
        padded_image = Image.fromarray(random_padding)
        padded_image.paste(image, (0, 0))
        return padded_image

    padded_image1 = pad_image(image1)
    padded_image2 = pad_image(image2)
    aspect_ratio = min(max_size / new_width, max_size / new_height)
    new_size = (int(new_width * aspect_ratio), int(new_height * aspect_ratio))
    resized_image1 = padded_image1.resize(new_size, Image.Resampling.LANCZOS)
    resized_image2 = padded_image2.resize(new_size, Image.Resampling.LANCZOS)
    return np.array(resized_image1).astype(np.int16), np.array(resized_image2).astype(np.int16)


def render_sanity_score(image_path: PathLike | Image.Image, html_path: PathLike | None = None) -> dict[str, Any]:
    """Score whether a render produced a plausible, non-blank screenshot.

    This is intentionally not a reference-match metric. It catches failed captures,
    white pages, near-empty screenshots, and HTML pages with no rendered text.
    """

    image = _load_rgb(image_path)
    arr = np.asarray(image)
    gray = (
        arr[:, :, 0].astype(np.float32) * 0.2126
        + arr[:, :, 1].astype(np.float32) * 0.7152
        + arr[:, :, 2].astype(np.float32) * 0.0722
    )
    histogram = np.bincount(gray.astype(np.uint8).ravel(), minlength=256)
    probabilities = histogram[histogram > 0] / histogram.sum()
    entropy = float(-(probabilities * np.log2(probabilities)).sum())
    non_white_ratio = float(np.mean(np.any(arr < 250, axis=2)))
    non_black_ratio = float(np.mean(np.any(arr > 8, axis=2)))
    color_std = float(gray.std())
    unique_color_ratio = float(len(np.unique(arr.reshape(-1, 3), axis=0)) / (arr.shape[0] * arr.shape[1]))

    text_chars = None
    text_score = 1.0
    if html_path is not None:
        soup = BeautifulSoup(_read_text(html_path), "lxml")
        text_chars = len(soup.get_text(" ", strip=True))
        text_score = min(text_chars / 120.0, 1.0)

    dimension_score = 1.0 if image.width >= 16 and image.height >= 16 else 0.0
    variation_score = min(color_std / 36.0, 1.0)
    content_score = min(non_white_ratio / 0.08, 1.0)
    entropy_score = min(entropy / 4.0, 1.0)
    not_black_score = min(non_black_ratio / 0.95, 1.0)

    score = (
        0.20 * dimension_score
        + 0.25 * variation_score
        + 0.25 * content_score
        + 0.20 * entropy_score
        + 0.10 * not_black_score
    )
    if html_path is not None:
        score = 0.85 * score + 0.15 * text_score

    return {
        "score": round(float(max(0.0, min(score, 1.0))), 6),
        "passed": bool(score >= 0.65),
        "width": image.width,
        "height": image.height,
        "entropy": round(entropy, 6),
        "gray_std": round(color_std, 6),
        "non_white_ratio": round(non_white_ratio, 6),
        "non_black_ratio": round(non_black_ratio, 6),
        "unique_color_ratio": round(unique_color_ratio, 6),
        "html_text_chars": text_chars,
    }


def _pixelmatch_color_delta(a: np.ndarray, b: np.ndarray, *, checkerboard: bool = True) -> np.ndarray:
    """Signed YIQ squared color distance from Mapbox pixelmatch."""

    img1 = a.reshape(-1, 4).astype(np.float64)
    img2 = b.reshape(-1, 4).astype(np.float64)

    r1, g1, b1, a1 = img1[:, 0], img1[:, 1], img1[:, 2], img1[:, 3]
    r2, g2, b2, a2 = img2[:, 0], img2[:, 1], img2[:, 2], img2[:, 3]
    dr = r1 - r2
    dg = g1 - g2
    db = b1 - b2
    da = a1 - a2

    alpha_mask = (a1 < 255) | (a2 < 255)
    if np.any(alpha_mask):
        rb = np.full(img1.shape[0], 255.0)
        gb = np.full(img1.shape[0], 255.0)
        bb = np.full(img1.shape[0], 255.0)
        if checkerboard:
            k = np.arange(img1.shape[0], dtype=np.float64) * 4.0
            rb = 48.0 + 159.0 * np.mod(k, 2.0)
            gb = 48.0 + 159.0 * np.mod(np.floor(k / 1.618033988749895), 2.0)
            bb = 48.0 + 159.0 * np.mod(np.floor(k / 2.618033988749895), 2.0)
        dr = dr.copy()
        dg = dg.copy()
        db = db.copy()
        dr[alpha_mask] = (
            r1[alpha_mask] * a1[alpha_mask]
            - r2[alpha_mask] * a2[alpha_mask]
            - rb[alpha_mask] * da[alpha_mask]
        ) / 255.0
        dg[alpha_mask] = (
            g1[alpha_mask] * a1[alpha_mask]
            - g2[alpha_mask] * a2[alpha_mask]
            - gb[alpha_mask] * da[alpha_mask]
        ) / 255.0
        db[alpha_mask] = (
            b1[alpha_mask] * a1[alpha_mask]
            - b2[alpha_mask] * a2[alpha_mask]
            - bb[alpha_mask] * da[alpha_mask]
        ) / 255.0

    y = dr * 0.29889531 + dg * 0.58662247 + db * 0.11448223
    i = dr * 0.59597799 - dg * 0.27417610 - db * 0.32180189
    q = dr * 0.21147017 - dg * 0.52261711 + db * 0.31114694
    delta = 0.5053 * y * y + 0.299 * i * i + 0.1957 * q * q
    return np.where(y > 0, -delta, delta)


def _pixelmatch_background(pos: int, checkerboard: bool) -> tuple[float, float, float]:
    if not checkerboard:
        return 255.0, 255.0, 255.0
    return (
        48.0 + 159.0 * (pos % 2),
        48.0 + 159.0 * (int(pos / 1.618033988749895) % 2),
        48.0 + 159.0 * (int(pos / 2.618033988749895) % 2),
    )


def _pixelmatch_brightness_delta(
    img: np.ndarray,
    center_pos: int,
    neighbor_pos: int,
    center_rgba: tuple[int, int, int, int],
    *,
    checkerboard: bool,
) -> float:
    r1, g1, b1, a1 = center_rgba
    r2 = int(img[neighbor_pos])
    g2 = int(img[neighbor_pos + 1])
    b2 = int(img[neighbor_pos + 2])
    a2 = int(img[neighbor_pos + 3])

    dr = r1 - r2
    dg = g1 - g2
    db = b1 - b2
    da = a1 - a2
    if not dr and not dg and not db and not da:
        return 0.0

    if a1 < 255 or a2 < 255:
        rb, gb, bb = _pixelmatch_background(center_pos, checkerboard)
        dr = (r1 * a1 - r2 * a2 - rb * da) / 255.0
        dg = (g1 * a1 - g2 * a2 - gb * da) / 255.0
        db = (b1 * a1 - b2 * a2 - bb * da) / 255.0

    return dr * 0.29889531 + dg * 0.58662247 + db * 0.11448223


def _pixelmatch_has_many_siblings(img32: np.ndarray, x1: int, y1: int, width: int, height: int) -> bool:
    x0 = max(x1 - 1, 0)
    y0 = max(y1 - 1, 0)
    x2 = min(x1 + 1, width - 1)
    y2 = min(y1 + 1, height - 1)
    value = img32[y1, x1]
    zeroes = 1 if x1 == x0 or x1 == x2 or y1 == y0 or y1 == y2 else 0

    for x in range(x0, x2 + 1):
        for y in range(y0, y2 + 1):
            if x == x1 and y == y1:
                continue
            if value == img32[y, x]:
                zeroes += 1
                if zeroes > 2:
                    return True
    return False


def _pixelmatch_antialiased(
    img: np.ndarray,
    x1: int,
    y1: int,
    width: int,
    height: int,
    img32: np.ndarray,
    other32: np.ndarray,
    *,
    checkerboard: bool,
) -> bool:
    x0 = max(x1 - 1, 0)
    y0 = max(y1 - 1, 0)
    x2 = min(x1 + 1, width - 1)
    y2 = min(y1 + 1, height - 1)
    center_pos = (y1 * width + x1) * 4
    center_rgba = (
        int(img[center_pos]),
        int(img[center_pos + 1]),
        int(img[center_pos + 2]),
        int(img[center_pos + 3]),
    )
    zeroes = 1 if x1 == x0 or x1 == x2 or y1 == y0 or y1 == y2 else 0
    min_delta = 0.0
    max_delta = 0.0
    min_x = min_y = max_x = max_y = 0

    for x in range(x0, x2 + 1):
        for y in range(y0, y2 + 1):
            if x == x1 and y == y1:
                continue

            delta = _pixelmatch_brightness_delta(
                img,
                center_pos,
                (y * width + x) * 4,
                center_rgba,
                checkerboard=checkerboard,
            )
            if delta == 0:
                zeroes += 1
                if zeroes > 2:
                    return False
            elif delta < min_delta:
                min_delta = delta
                min_x = x
                min_y = y
            elif delta > max_delta:
                max_delta = delta
                max_x = x
                max_y = y

    if min_delta == 0 or max_delta == 0:
        return False

    return (
        _pixelmatch_has_many_siblings(img32, min_x, min_y, width, height)
        and _pixelmatch_has_many_siblings(other32, min_x, min_y, width, height)
    ) or (
        _pixelmatch_has_many_siblings(img32, max_x, max_y, width, height)
        and _pixelmatch_has_many_siblings(other32, max_x, max_y, width, height)
    )


def pixelmatch_score(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    threshold: float = 0.1,
    include_aa: bool = False,
    checkerboard: bool = True,
    resize_candidate: bool = True,
) -> dict[str, Any]:
    """Mapbox pixelmatch visual diff score, returned as high-is-better JSON."""

    ref_image, cand_image = _resize_pair(reference, candidate, mode="RGBA", resize_candidate=resize_candidate)
    ref = np.ascontiguousarray(np.asarray(ref_image, dtype=np.uint8))
    cand = np.ascontiguousarray(np.asarray(cand_image, dtype=np.uint8))
    if ref.shape != cand.shape:
        raise ValueError(f"Image sizes differ: reference={ref.shape}, candidate={cand.shape}")

    height, width = ref.shape[:2]
    total_pixels = int(width * height)
    if np.array_equal(ref, cand):
        return {
            "score": 1.0,
            "diff_ratio": 0.0,
            "diff_pixels": 0,
            "aa_pixels": 0,
            "total_pixels": total_pixels,
            "threshold": threshold,
            "include_aa": include_aa,
            "checkerboard": checkerboard,
            "resized_candidate": bool(resize_candidate),
        }

    max_delta = 35215.0 * threshold * threshold
    deltas = _pixelmatch_color_delta(ref, cand, checkerboard=checkerboard)
    candidate_indices = np.flatnonzero(np.abs(deltas) > max_delta)

    aa_pixels = 0
    if include_aa:
        diff_pixels = int(candidate_indices.size)
    else:
        ref32 = ref.view(np.uint32).reshape(height, width)
        cand32 = cand.view(np.uint32).reshape(height, width)
        ref_flat = ref.reshape(-1)
        cand_flat = cand.reshape(-1)
        diff_pixels = 0
        for pixel_index in candidate_indices:
            x = int(pixel_index % width)
            y = int(pixel_index // width)
            is_aa = _pixelmatch_antialiased(
                ref_flat,
                x,
                y,
                width,
                height,
                ref32,
                cand32,
                checkerboard=checkerboard,
            ) or _pixelmatch_antialiased(
                cand_flat,
                x,
                y,
                width,
                height,
                cand32,
                ref32,
                checkerboard=checkerboard,
            )
            if is_aa:
                aa_pixels += 1
            else:
                diff_pixels += 1

    diff_ratio = diff_pixels / total_pixels if total_pixels else 1.0

    return {
        "score": round(float(1.0 - diff_ratio), 6),
        "diff_ratio": round(float(diff_ratio), 6),
        "diff_pixels": diff_pixels,
        "aa_pixels": aa_pixels,
        "total_pixels": total_pixels,
        "threshold": threshold,
        "include_aa": include_aa,
        "checkerboard": checkerboard,
        "resized_candidate": bool(resize_candidate),
    }


def mse_score(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    resize_candidate: bool = True,
) -> float:
    """WebCode2M MSE after resizing the candidate with OpenCV Lanczos4."""

    ref, cand = _as_webcode2m_bgr_arrays(reference, candidate, resize_candidate=resize_candidate)
    im_1 = ref / 255.0
    im_2 = cand / 255.0
    err = np.sum((im_1.astype("float") - im_2.astype("float")) ** 2)
    err /= float(im_1.shape[0] * im_1.shape[1])
    return round(float(err), 8)


def mae_score(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    max_size: int = 512,
) -> float:
    """DesignBench MAE with its pad-to-shared-size and resize preprocessing."""

    ref, cand = _as_designbench_arrays(reference, candidate, max_size=max_size)
    err = np.mean(np.abs(ref - cand))
    return round(float(err), 8)


def ssim_score(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    resize_candidate: bool = True,
) -> float:
    """WebCode2M RGB SSIM after resizing the candidate with OpenCV Lanczos4."""

    ref, cand = _as_webcode2m_bgr_arrays(reference, candidate, resize_candidate=resize_candidate)
    score = structural_similarity(
        ref,
        cand,
        multichannel=True,
        channel_axis=2,
        gaussian_weights=True,
        sigma=1.5,
        use_sample_covariance=False,
        data_range=255.0,
    )
    return round(float(score), 8)


def cw_ssim_score(*_args: Any, **_kwargs: Any) -> float:
    raise NotImplementedError(
        "CW-SSIM is not wired yet. Add a Complex Wavelet SSIM implementation, "
        "for example pyssim/pycw-ssim style code, before using this metric."
    )


def html_text_score(reference_html: PathLike | str, candidate_html: PathLike | str) -> dict[str, Any]:
    return webcode2m_text_score(reference_html, candidate_html)


def webcode2m_text_score(reference_html: PathLike | str, candidate_html: PathLike | str) -> dict[str, Any]:
    from .webcode2m import webcode2m_text_score as _webcode2m_text_score

    return _webcode2m_text_score(reference_html, candidate_html)


def webcode2m_dom_score(reference_html: PathLike | str, candidate_html: PathLike | str) -> dict[str, Any]:
    from .webcode2m import webcode2m_dom_score as _webcode2m_dom_score

    return _webcode2m_dom_score(reference_html, candidate_html)


def extract_webcode2m_bbox_tree(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    from .webcode2m_bbox import extract_webcode2m_bbox_tree as _extract_webcode2m_bbox_tree

    return _extract_webcode2m_bbox_tree(*args, **kwargs)


def webcode2m_bbox_tree_to_html(*args: Any, **kwargs: Any) -> str:
    from .webcode2m_bbox import webcode2m_bbox_tree_to_html as _webcode2m_bbox_tree_to_html

    return _webcode2m_bbox_tree_to_html(*args, **kwargs)


def webcode2m_bbox_tree_to_style_list(*args: Any, **kwargs: Any) -> list[dict[str, Any]]:
    from .webcode2m_bbox import webcode2m_bbox_tree_to_style_list as _webcode2m_bbox_tree_to_style_list

    return _webcode2m_bbox_tree_to_style_list(*args, **kwargs)


def webcode2m_html_to_bbox_tree(*args: Any, **kwargs: Any) -> dict[str, Any] | None:
    from .webcode2m_bbox import webcode2m_html_to_bbox_tree as _webcode2m_html_to_bbox_tree

    return _webcode2m_html_to_bbox_tree(*args, **kwargs)


def _pick_torch_device(explicit_device: str | None = None) -> str:
    if explicit_device:
        return explicit_device
    import torch

    if torch.cuda.is_available():
        return "cuda"
    if getattr(torch.backends, "mps", None) is not None and torch.backends.mps.is_available():
        return "mps"
    return "cpu"


def clip_similarity(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    model_name: str = "ViT-B-32-quickgelu",
    pretrained: str = "openai",
    device: str | None = None,
    cache_dir: PathLike | None = None,
) -> float:
    """CLIP image-embedding cosine similarity using open-clip-torch."""

    import open_clip
    import torch

    resolved_device = _pick_torch_device(device)
    key = (model_name, pretrained, resolved_device)
    if key not in _CLIP_CACHE:
        model, _, preprocess = open_clip.create_model_and_transforms(
            model_name,
            pretrained=pretrained,
            device=resolved_device,
            cache_dir=str(cache_dir) if cache_dir else None,
        )
        model.eval()
        _CLIP_CACHE[key] = (model, preprocess)
    else:
        model, preprocess = _CLIP_CACHE[key]

    image_1 = preprocess(_load_rgb(reference)).unsqueeze(0).to(resolved_device)
    image_2 = preprocess(_load_rgb(candidate)).unsqueeze(0).to(resolved_device)

    with torch.no_grad():
        features_1 = model.encode_image(image_1)
        features_2 = model.encode_image(image_2)
        features_1 = features_1 / features_1.norm(dim=-1, keepdim=True)
        features_2 = features_2 / features_2.norm(dim=-1, keepdim=True)
        similarity = (features_1 * features_2).sum(dim=-1).item()
    return round(float(similarity), 8)


def dreamsim_distance(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    device: str | None = None,
    dreamsim_type: str = "ensemble",
    cache_dir: PathLike | None = None,
) -> float:
    """DreamSim perceptual distance."""

    try:
        import torch
        from dreamsim import dreamsim
    except ImportError as exc:
        raise RuntimeError(
            "DreamSim is not installed. Install the DreamSim package and let it "
            "download its model weights before calling dreamsim_distance()."
        ) from exc

    resolved_device = _pick_torch_device(device)
    resolved_cache_dir = str(cache_dir) if cache_dir else "./models"
    key = (dreamsim_type, resolved_device, resolved_cache_dir)
    if key not in _DREAMSIM_CACHE:
        model, preprocess = dreamsim(
            pretrained=True,
            device=resolved_device,
            dreamsim_type=dreamsim_type,
            cache_dir=resolved_cache_dir,
        )
        model.eval()
        _DREAMSIM_CACHE[key] = (model, preprocess)
    else:
        model, preprocess = _DREAMSIM_CACHE[key]
    image_1 = preprocess(_load_rgb(reference)).to(resolved_device)
    image_2 = preprocess(_load_rgb(candidate)).to(resolved_device)
    with torch.no_grad():
        distance = model(image_1, image_2).item()
    return round(float(distance), 8)


def visual_block_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .block_visual import visual_block_score as _visual_block_score

    return _visual_block_score(*args, **kwargs)


def element_block_pixelmatch_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .block_visual import element_block_pixelmatch_score as _element_block_pixelmatch_score

    return _element_block_pixelmatch_score(*args, **kwargs)


def bbox_geometry_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .block_visual import bbox_geometry_score as _bbox_geometry_score

    return _bbox_geometry_score(*args, **kwargs)


def extract_cssom_snapshot(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .cssom import extract_cssom_snapshot as _extract_cssom_snapshot

    return _extract_cssom_snapshot(*args, **kwargs)


def cssom_block_style_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .cssom import cssom_block_style_score as _cssom_block_style_score

    return _cssom_block_style_score(*args, **kwargs)


def cssom_block_style_score_from_snapshots(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .cssom import cssom_block_style_score_from_snapshots as _cssom_block_style_score_from_snapshots

    return _cssom_block_style_score_from_snapshots(*args, **kwargs)


def mobile_overflow_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import mobile_overflow_tags as _mobile_overflow_tags

    return _mobile_overflow_tags(*args, **kwargs)


def accessibility_control_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import accessibility_control_tags as _accessibility_control_tags

    return _accessibility_control_tags(*args, **kwargs)


def webcoderbench_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import webcoderbench_tags as _webcoderbench_tags

    return _webcoderbench_tags(*args, **kwargs)


def webcoderbench_component_style_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import webcoderbench_component_style_score as _webcoderbench_component_style_score

    return _webcoderbench_component_style_score(*args, **kwargs)


def webcoderbench_icon_style_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import webcoderbench_icon_style_score as _webcoderbench_icon_style_score

    return _webcoderbench_icon_style_score(*args, **kwargs)


def webcoderbench_layout_consistency_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import webcoderbench_layout_consistency_score as _webcoderbench_layout_consistency_score

    return _webcoderbench_layout_consistency_score(*args, **kwargs)


def webcoderbench_layout_sparsity_score(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import webcoderbench_layout_sparsity_score as _webcoderbench_layout_sparsity_score

    return _webcoderbench_layout_sparsity_score(*args, **kwargs)


def webcoderbench_visual_quality_scores(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import webcoderbench_visual_quality_scores as _webcoderbench_visual_quality_scores

    return _webcoderbench_visual_quality_scores(*args, **kwargs)


def presentation_diff_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import presentation_diff_tags as _presentation_diff_tags

    return _presentation_diff_tags(*args, **kwargs)


def websee_dom_localization_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import websee_dom_localization_tags as _websee_dom_localization_tags

    return _websee_dom_localization_tags(*args, **kwargs)


def _image_data_url(image_path: PathLike) -> str:
    suffix = Path(image_path).suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


def _extract_web2code_scores(parsed: Any, raw_text: str) -> list[float] | None:
    scores: Any = None
    if isinstance(parsed, dict):
        if "scores" in parsed:
            scores = parsed["scores"]
        elif "dimensions" in parsed and isinstance(parsed["dimensions"], dict):
            dimensions = parsed["dimensions"]
            scores = [dimensions.get(name) for name in WEB2CODE_DIMENSION_NAMES]
        elif all(name in parsed for name in WEB2CODE_DIMENSION_NAMES):
            scores = [parsed.get(name) for name in WEB2CODE_DIMENSION_NAMES]
    elif isinstance(parsed, list):
        scores = parsed

    if scores is None:
        scores = re.findall(r"-?\d+(?:\.\d+)?", raw_text)

    if not isinstance(scores, list) or len(scores) != len(WEB2CODE_DIMENSION_NAMES):
        return None

    coerced: list[float] = []
    try:
        for score in scores:
            value = float(score)
            coerced.append(min(max(value, 0.0), 10.0))
    except (TypeError, ValueError):
        return None
    return coerced


def _aggregate_web2code_scores(scores: list[float]) -> dict[str, Any]:
    dimensions = {
        name: round(float(score), 4)
        for name, score in zip(WEB2CODE_DIMENSION_NAMES, scores, strict=True)
    }
    groups: dict[str, float] = {}
    for group_name, indices in WEB2CODE_GROUP_INDICES.items():
        group_score_0_to_10 = sum(scores[index] for index in indices) / len(indices)
        groups[group_name] = round(float(group_score_0_to_10 / 10.0), 6)

    overall = sum(groups.values()) / len(groups)
    return {
        "overall": round(float(overall), 6),
        "overall_0_to_10": round(float(overall * 10.0), 4),
        "dimensions": dimensions,
        "groups": groups,
        "raw_scores": [round(float(score), 4) for score in scores],
        "rubric": "web2code_10_dimension",
    }


def vlm_judge_score(
    reference: PathLike,
    candidate: PathLike,
    *,
    model: str = "gpt-5.5",
    rubric: str | None = None,
) -> dict[str, Any]:
    """Use an OpenAI vision-capable model to judge screenshot similarity.

    Requires OPENAI_API_KEY. The model name defaults to gpt-5.5 per the current
    project direction.
    """

    from openai import OpenAI

    prompt = rubric or WEB2CODE_VLM_PROMPT
    client = OpenAI()
    response = client.responses.create(
        model=model,
        input=[
            {
                "role": "user",
                "content": [
                    {"type": "input_text", "text": prompt},
                    {"type": "input_text", "text": "Reference screenshot:"},
                    {"type": "input_image", "image_url": _image_data_url(reference), "detail": "auto"},
                    {"type": "input_text", "text": "Candidate screenshot:"},
                    {"type": "input_image", "image_url": _image_data_url(candidate), "detail": "auto"},
                ],
            }
        ],
        text={"format": {"type": "json_object"}},
    )
    text = response.output_text
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        parsed = None

    scores = _extract_web2code_scores(parsed, text)
    if scores is None:
        return {"raw": text, "parsed": parsed}
    result = _aggregate_web2code_scores(scores)
    result["model"] = model
    return result


def score_screenshot_pair(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    include_clip: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "reference_render_sanity": render_sanity_score(reference),
        "candidate_render_sanity": render_sanity_score(candidate),
        "size_match": screenshot_size_match_score(reference, candidate),
        "pixelmatch": pixelmatch_score(reference, candidate),
        "mse": mse_score(reference, candidate),
        "mae": mae_score(reference, candidate),
        "ssim": ssim_score(reference, candidate),
    }
    if include_clip:
        result["clip"] = clip_similarity(reference, candidate)
    return result


def _mean(values: list[float]) -> float | None:
    return round(float(sum(values) / len(values)), 8) if values else None


def score_capture_set(
    reference_dir: PathLike,
    candidate_dir: PathLike,
    *,
    include_clip: bool = False,
) -> dict[str, Any]:
    reference_root = Path(reference_dir)
    candidate_root = Path(candidate_dir)
    pairs: dict[str, Any] = {}
    missing: list[str] = []

    for reference_path in sorted(reference_root.glob("*.png")):
        candidate_path = candidate_root / reference_path.name
        if not candidate_path.exists():
            missing.append(reference_path.name)
            continue
        pairs[reference_path.name] = score_screenshot_pair(
            reference_path,
            candidate_path,
            include_clip=include_clip,
        )

    summary = {
        "count": len(pairs),
        "missing": missing,
        "pixelmatch": _mean([pair["pixelmatch"]["score"] for pair in pairs.values()]),
        "ssim": _mean([pair["ssim"] for pair in pairs.values()]),
        "mse": _mean([pair["mse"] for pair in pairs.values()]),
        "mae": _mean([pair["mae"] for pair in pairs.values()]),
        "size_match": _mean([pair["size_match"]["score"] for pair in pairs.values()]),
        "candidate_render_sanity": _mean([pair["candidate_render_sanity"]["score"] for pair in pairs.values()]),
    }
    if include_clip:
        summary["clip"] = _mean([pair["clip"] for pair in pairs.values()])

    return {"summary": summary, "pairs": pairs}
