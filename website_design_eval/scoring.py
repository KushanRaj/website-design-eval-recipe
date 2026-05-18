from __future__ import annotations

import base64
import json
import os
from pathlib import Path
from typing import Any

import numpy as np
from bs4 import BeautifulSoup
from PIL import Image
from skimage.metrics import structural_similarity

PathLike = str | os.PathLike[str]

_CLIP_CACHE: dict[tuple[str, str, str], tuple[Any, Any]] = {}
_DREAMSIM_CACHE: dict[tuple[str, str, str], tuple[Any, Any]] = {}


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


def _pixelmatch_color_delta(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """YIQ squared color distance used by pixelmatch-style screenshot diffs."""

    diff = a.astype(np.float32) - b.astype(np.float32)
    y = diff[:, :, 0] * 0.29889531 + diff[:, :, 1] * 0.58662247 + diff[:, :, 2] * 0.11448223
    i = diff[:, :, 0] * 0.59597799 - diff[:, :, 1] * 0.27417610 - diff[:, :, 2] * 0.32180189
    q = diff[:, :, 0] * 0.21147017 - diff[:, :, 1] * 0.52261711 + diff[:, :, 2] * 0.31114694
    return 0.5053 * y * y + 0.299 * i * i + 0.1957 * q * q


def pixelmatch_score(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    threshold: float = 0.1,
    resize_candidate: bool = True,
) -> dict[str, Any]:
    """Pixelmatch-style visual diff score.

    The source reference is Mapbox pixelmatch's YIQ color distance and threshold
    convention. This Python function reports a high-is-better score instead of
    only returning the mismatch count.
    """

    ref, cand = _as_rgb_arrays(reference, candidate, resize_candidate=resize_candidate)
    if ref.shape != cand.shape:
        raise ValueError(f"Image sizes differ: reference={ref.shape}, candidate={cand.shape}")

    max_delta = 35215.0 * threshold * threshold
    deltas = _pixelmatch_color_delta(ref, cand)
    diff_mask = deltas > max_delta
    diff_pixels = int(diff_mask.sum())
    total_pixels = int(diff_mask.size)
    diff_ratio = diff_pixels / total_pixels if total_pixels else 1.0

    return {
        "score": round(float(1.0 - diff_ratio), 6),
        "diff_ratio": round(float(diff_ratio), 6),
        "diff_pixels": diff_pixels,
        "total_pixels": total_pixels,
        "threshold": threshold,
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
    dreamsim_type: str = "open_clip_vitb32",
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


def mobile_overflow_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import mobile_overflow_tags as _mobile_overflow_tags

    return _mobile_overflow_tags(*args, **kwargs)


def accessibility_control_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import accessibility_control_tags as _accessibility_control_tags

    return _accessibility_control_tags(*args, **kwargs)


def webcoderbench_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import webcoderbench_tags as _webcoderbench_tags

    return _webcoderbench_tags(*args, **kwargs)


def presentation_diff_tags(*args: Any, **kwargs: Any) -> dict[str, Any]:
    from .diagnostics import presentation_diff_tags as _presentation_diff_tags

    return _presentation_diff_tags(*args, **kwargs)


def _image_data_url(image_path: PathLike) -> str:
    suffix = Path(image_path).suffix.lower()
    mime = "image/jpeg" if suffix in {".jpg", ".jpeg"} else "image/png"
    encoded = base64.b64encode(Path(image_path).read_bytes()).decode("ascii")
    return f"data:{mime};base64,{encoded}"


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

    prompt = rubric or (
        "Compare the candidate web screenshot against the reference screenshot. "
        "Return compact JSON with keys overall, layout, typography, color, content, "
        "and notes. Scores must be 0 to 1 where 1 means the candidate matches the reference."
    )
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
        return json.loads(text)
    except json.JSONDecodeError:
        return {"raw": text}


def score_screenshot_pair(
    reference: PathLike | Image.Image,
    candidate: PathLike | Image.Image,
    *,
    include_clip: bool = False,
) -> dict[str, Any]:
    result: dict[str, Any] = {
        "reference_render_sanity": render_sanity_score(reference),
        "candidate_render_sanity": render_sanity_score(candidate),
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
        "candidate_render_sanity": _mean([pair["candidate_render_sanity"]["score"] for pair in pairs.values()]),
    }
    if include_clip:
        summary["clip"] = _mean([pair["clip"] for pair in pairs.values()])

    return {"summary": summary, "pairs": pairs}
