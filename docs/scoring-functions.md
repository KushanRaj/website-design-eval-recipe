# Scoring Functions

This page documents the scoring API in `website_design_eval`.

The implementation lives in:

```text
website_design_eval/scoring.py
```

The CLI wrapper lives in:

```text
website_design_eval/cli.py
```

## Quickstart

Score one screenshot pair:

```bash
uv run website-design-eval pair test-site/screenshots/reference/home.desktop.full.png reproductions/claude-attempt-01/screenshots/home.desktop.full.png
```

Score all matching `.png` filenames in two directories:

```bash
uv run website-design-eval directory test-site/screenshots/reference reproductions/claude-attempt-01/screenshots
```

Include local CLIP similarity:

```bash
uv run website-design-eval pair test-site/screenshots/reference/home.desktop.full.png reproductions/claude-attempt-01/screenshots/home.desktop.full.png --clip
```

Import directly from Python:

```python
from website_design_eval import score_screenshot_pair

scores = score_screenshot_pair(
    "test-site/screenshots/reference/home.desktop.full.png",
    "reproductions/claude-attempt-01/screenshots/home.desktop.full.png",
    include_clip=True,
)
```

## Runtime Requirements

| Function group | Needs API? | Downloads model? | Notes |
| --- | --- | --- | --- |
| Render sanity, pixelmatch-style, MSE, MAE, SSIM | No | No | Runs with local Python dependencies. |
| WebCode2M HTML text and DOM | No | No | Runs on local strings or files. |
| CLIP | No | Yes | Uses `open-clip-torch`; first call downloads `ViT-B-32-quickgelu/openai`. |
| DreamSim | No | Yes | Installed from `research/source-repos/dreamsim`; first call downloads model weights. |
| VLM judge | Yes | No local model | Uses OpenAI `gpt-5.5`; requires `OPENAI_API_KEY`. |
| CW-SSIM | No | Not wired | Explicit placeholder raising `NotImplementedError`. |
| Visual block matching, bbox geometry, element block pixelmatch, CSSOM block style | No | Yes | Uses checked-in WebCode2M/Design2Code OCR-free block metric under `research/`; first masked-CLIP call loads `open-clip-torch`. CSSOM extraction also launches Chromium through Playwright. |
| WebCoderBench/WebSee diagnostic tags | No | No | Runs local Playwright/image processing checks and returns tags/raw measurements, not final reward scores. WebCoderBench visual fallbacks use paper formulas, not released evaluator code. |

The verified local CLIP cache for this workspace is:

```text
.cache/open_clip
```

Do not commit that cache; it is a large local model artifact.

The visual block adapter also needs Chromium installed for Python Playwright. In this workspace it was installed under the ignored `./.playwright` directory with:

```bash
PLAYWRIGHT_BROWSERS_PATH=./.playwright uv run playwright install chromium
```

## Source-Fidelity Audit

| Function | Source relationship | Sanity-check result |
| --- | --- | --- |
| `webcode2m_text_score` / `html_text_score` | Calls the same `nltk` BLEU-1 and `rouge` ROUGE-1 flow as WebCode2M `metrics.py::bleu_rouge`. | Faithful. |
| `webcode2m_dom_score` | Mirrors WebCode2M `metrics.py::dom_sim` and `html_tree.py::html2tree`. | Faithful, with unrelated optional imports avoided. |
| `extract_webcode2m_bbox_tree` / `webcode2m_bbox_tree_to_html` / `webcode2m_bbox_tree_to_style_list` | Mirrors WebCode2M `html2screenshot.py::output_bbox` and `scripts/train/utils.py` bbox-tree serializers. | Faithful surface; this is a data/training representation, not an official scalar score. |
| `visual_block_score` | Adapter around checked-in WebCode2M/Design2Code `visual_score_v3`. | Faithful to the scoring logic; subprocess cleanup and CLIP loading are modernized. |
| `dreamsim_distance` | Calls the local DreamSim package. | Defaults to DreamSim's full `ensemble` rather than the lighter single-branch model. |
| `screenshot_size_match_score` | Local diagnostic comparing raw screenshot dimensions before any resizing. | Not a paper metric; useful to separate canvas/document-height mismatch from pixel-level visual mismatch. |
| `mse_score` | Mirrors WebCode2M `metrics.py::mse` after the same OpenCV Lanczos4 candidate resize used by `image_sim_scores`. | Faithful. |
| `ssim_score` | Mirrors WebCode2M `metrics.py::ssim` after the same OpenCV Lanczos4 candidate resize used by `image_sim_scores`. | Faithful. |
| `mae_score` | Mirrors DesignBench `metric.py::mae_score` and `process_imgs`. | Faithful, including random padding for unequal image sizes. |
| `clip_similarity` | Same metric family as WebCode2M/DesignBench CLIP cosine. | Good substitute, but uses `open-clip-torch` instead of the older `clip` package. |
| `pixelmatch_score` | Python port of Mapbox pixelmatch mismatch counting. | Faithful against upstream fixture mismatch counts, including anti-alias exclusion and alpha/checkerboard handling. |
| `element_block_pixelmatch_score`, `bbox_geometry_score`, `cssom_block_style_score` | Local extensions over visual-block matched pairs. | Not paper metrics; useful experimental probes. `cssom_block_style_score` uses browser CSSOM extraction inspired by computed-style/layout testing work, but keeps Design2Code/WebCode2M as the correspondence source. |
| `mobile_overflow_tags`, `accessibility_control_tags`, `webcoderbench_tags` | Local WebCoderBench-inspired diagnostics. | Tag/measurement surfaces only; no reward aggregation yet. |
| `webcoderbench_component_style_score`, `webcoderbench_icon_style_score`, `webcoderbench_layout_consistency_score`, `webcoderbench_layout_sparsity_score` | Local WebCoderBench paper-formula fallbacks. | Public artifacts checked expose leaderboard/results, not evaluator implementation. These keep the paper formulas and report local extraction assumptions. |
| `presentation_diff_tags`, `websee_dom_localization_tags` | Local WebSee-inspired visual diff clustering and DOM localization. | Upstream WebSee Java repo cloned, but build is blocked by old Maven HTTP/USC Artifactory dependencies. Local fallback maps diff clusters to Playwright CSSOM boxes. |

## Function Reference

### `render_sanity_score(image_path, html_path=None)`

Checks whether a screenshot is plausibly rendered rather than blank, black, tiny, or otherwise failed.

Inputs:

- `image_path`: screenshot path or PIL image.
- `html_path`: optional HTML path. When present, text length contributes to the score.

Output:

- `score`: high-is-better value from 0 to 1.
- `passed`: boolean thresholded at `0.65`.
- Diagnostic fields: width, height, entropy, grayscale standard deviation, non-white ratio, non-black ratio, unique color ratio, optional HTML text chars.

Source lineage:

- Local implementation based on the repo's screenshot-capture workflow.
- This is not copied from a paper metric; it is a guardrail for failed renders.

### `screenshot_size_match_score(reference, candidate)`

Compares the raw screenshot canvas dimensions before any resizing.

Output:

- `score`: `width_score * height_score`, high is better.
- `width_score`, `height_score`: `min(reference, candidate) / max(reference, candidate)` for each axis.
- `area_score`, `aspect_ratio_score`.
- `reference`, `candidate`: raw width, height, area, and aspect ratio.
- `width_ratio`, `height_ratio`, `area_ratio`: candidate/reference ratios.

Interpretation:

- Use this to detect when full-page screenshots differ because document heights differ.
- Keep it separate from pixelmatch/MSE/SSIM, because those metrics resize or pad before comparison and can hide or amplify size mismatch effects.
- For VLM judges, raw size mismatch is especially important: a taller full-page screenshot can make the same content appear compressed when viewed as a whole image.

### `pixelmatch_score(reference, candidate, threshold=0.1, include_aa=False, checkerboard=True, resize_candidate=True)`

Computes a Mapbox pixelmatch screenshot diff and returns it as a high-is-better score.

Inputs:

- `reference`: reference screenshot path or PIL image.
- `candidate`: candidate screenshot path or PIL image.
- `threshold`: pixelmatch YIQ distance threshold.
- `include_aa`: whether to count anti-aliased pixels as differences. Defaults to `False`, matching pixelmatch.
- `checkerboard`: whether semi-transparent pixels are composited against pixelmatch's checkerboard background rather than plain white.
- `resize_candidate`: resize candidate to the reference size before scoring.

Output:

- `score`: `1 - diff_ratio`, high is better.
- `diff_ratio`, `diff_pixels`, `aa_pixels`, `total_pixels`, `threshold`, `include_aa`, `checkerboard`, `resized_candidate`.

Source lineage:

- Ported from Mapbox `pixelmatch` in `research/source-repos/pixelmatch/index.js`.
- Verified against the upstream fixture mismatch counts in `research/source-repos/pixelmatch/test/test.js`.

### `mse_score(reference, candidate, resize_candidate=True)`

WebCode2M mean squared pixel error.

Output:

- Float where lower is better.

Source lineage:

- Mirrors WebCode2M `metrics.py::mse`.
- Candidate screenshots are resized to the reference shape with OpenCV `INTER_LANCZOS4`, matching WebCode2M `image_sim_scores`.
- Note the scale: WebCode2M sums RGB channel error and divides by `height * width`, so this is not capped at 1.

### `mae_score(reference, candidate, max_size=512)`

DesignBench mean absolute pixel error.

Output:

- Float where lower is better.

Source lineage:

- Mirrors DesignBench `metric.py::mae_score` and `process_imgs`.
- It pads both images to a shared size with random RGB pixels, resizes to a max of 512, converts to `int16`, and averages raw 0-255 absolute error.
- Because the upstream padding is random, this metric is not deterministic when image sizes differ.

### `ssim_score(reference, candidate, resize_candidate=True)`

WebCode2M RGB Structural Similarity Index.

Output:

- Float where higher is better.

Source lineage:

- Mirrors WebCode2M `metrics.py::ssim`.
- Candidate screenshots are resized to the reference shape with OpenCV `INTER_LANCZOS4`, matching WebCode2M `image_sim_scores`.
- DesignBench's SSIM implementation is different: it uses grayscale images.

### `cw_ssim_score(...)`

Placeholder for Complex Wavelet SSIM.

Current behavior:

- Raises `NotImplementedError`.

Why it exists:

- CW-SSIM is useful when small translations or phase shifts should be penalized less than raw pixel metrics penalize them.
- It needs a proper complex wavelet implementation before it should be used in the default pipeline.

### `html_text_score(reference_html, candidate_html)` / `webcode2m_text_score(reference_html, candidate_html)`

Compares visible HTML text with WebCode2M's text metric.

Inputs:

- HTML file paths or raw HTML strings.

Output:

- `bleu_1`: WebCode2M BLEU-1 over visible text tokens.
- `rouge_1_recall`: WebCode2M ROUGE-1 recall over visible text tokens.
- `reference_tokens`, `candidate_tokens`.

Source lineage:

- Mirrors WebCode2M `metrics.py::bleu_rouge`, including `nltk.translate.bleu_score` and `rouge.Rouge`.

CLI:

```bash
uv run website-design-eval webcode2m-text \
  test-site/index.html \
  reproductions/claude-attempt-01/index.html
```

### `webcode2m_dom_score(reference_html, candidate_html)`

Runs the WebCode2M DOM subtree metric.

Why this exists:

- The upstream `metrics.py::dom_sim` function is tiny, but importing the file directly also imports optional `clip`, `rouge`, `nltk`, and `graphviz` dependencies.
- This wrapper mirrors the relevant WebCode2M tree construction and subtree BLEU/ROUGE logic while keeping those unrelated imports out of the scorer path.

Output:

- `tree_bleu`: candidate subtree precision.
- `tree_rouge_1`: reference subtree recall.
- `f1`: balanced subtree match.
- Count fields for total/unique/matched subtrees.

CLI:

```bash
uv run website-design-eval webcode2m-dom \
  test-site/index.html \
  reproductions/claude-attempt-01/index.html
```

Six-page mean results:

| Reproduction | Tree BLEU ↑ | Tree ROUGE-1 ↑ | F1 ↑ |
| --- | ---: | ---: | ---: |
| `claude-attempt-01` | 0.391 | 0.344 | 0.364 |
| `claude-attempt-02-bad` | 0.283 | 0.216 | 0.244 |

### `extract_webcode2m_bbox_tree(html_path, viewport=None)`

Extracts WebCode2M's rendered bbox tree for one HTML file.

Why this exists:

- WebCode2M has a bbox-annotated tree surface in its screenshot/data/training pipeline.
- It is not the same thing as `dom_sim` and it is not an official scalar evaluation metric.
- The implementation mirrors the upstream Playwright `output_bbox` JavaScript: start at `document.body`, skip hidden/zero-size nodes, keep inline `style`, `content`, integer `[x, y, width, height]`, and recurse through element children.

Related serializers:

- `webcode2m_bbox_tree_to_html(tree, size=(w, h))`: mirrors WebCode2M `BboxTree2Html`, producing bbox-annotated pseudo-HTML with normalized coordinates.
- `webcode2m_bbox_tree_to_style_list(tree)`: mirrors WebCode2M `BboxTree2StyleList`, producing the parent/child bbox/style view used by the styler stage.
- `webcode2m_html_to_bbox_tree(html, size=(w, h))`: mirrors WebCode2M `Html2BboxTree` for parsing bbox pseudo-HTML back into a tree.

CLI:

```bash
uv run website-design-eval webcode2m-bbox-tree \
  test-site/index.html \
  --viewport-width 1440 \
  --viewport-height 900 \
  --bbox-html \
  --style-list
```

Interpretation:

- Use this when we want the WebCode2M bbox/tree representation itself.
- Use `visual_block_score.position` when we want WebCode2M's official geometry-like evaluation signal from `visual_score_v3`.
- Use `bbox_geometry_score` only as our local extension over matched visual blocks.

### `clip_similarity(reference, candidate, model_name="ViT-B-32-quickgelu", pretrained="openai", device=None, cache_dir=None)`

Computes CLIP image embedding cosine similarity.

Inputs:

- `reference`: screenshot path or PIL image.
- `candidate`: screenshot path or PIL image.
- `model_name`: defaults to `ViT-B-32-quickgelu`.
- `pretrained`: defaults to `openai`.
- `device`: optional `cpu`, `cuda`, or `mps`. Auto-detected when omitted.
- `cache_dir`: optional local model cache directory.

Output:

- Float cosine similarity where higher is better.

Requirements:

- No API key.
- Downloads CLIP weights on first call.
- Uses `open-clip-torch`.

Source lineage:

- WebCode2M and DesignBench both include CLIP image similarity.
- The upstream code paths checked here use OpenAI CLIP `ViT-B/32`.
- Local implementation uses `open-clip-torch`'s `ViT-B-32-quickgelu/openai`, which is the closest equivalent to the older `clip.load("ViT-B/32")` API.

### `dreamsim_distance(reference, candidate, device=None, dreamsim_type="ensemble", cache_dir=None)`

DreamSim perceptual distance wrapper.

Current behavior:

- Uses the local DreamSim package from `research/source-repos/dreamsim`.
- Defaults to DreamSim's full `ensemble`: DINO ViT-B/16 + CLIP ViT-B/16 + OpenCLIP ViT-B/16.
- The lighter `open_clip_vitb32` branch can still be requested explicitly for faster local experiments.
- Caches the loaded model in-process so scoring multiple screenshots does not reload the model each time.

Output:

- Float distance where lower is better.

Requirements:

- No API key.
- Downloads DreamSim weights on first use. In this workspace the cache path used for experiments is `.cache/dreamsim`.

CLI:

```bash
uv run website-design-eval dreamsim \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-01/screenshots/home.desktop.full.png \
  --dreamsim-type ensemble \
  --cache-dir .cache/dreamsim
```

Screenshot-set mean results with `score = 1 - distance`:

| Reproduction | Mean distance ↓ | Mean score ↑ | Count |
| --- | ---: | ---: | ---: |
| `claude-attempt-01` | 0.094 | 0.906 | 9 |
| `claude-attempt-02-bad` | 0.522 | 0.478 | 8 |

### `visual_block_score(reference_html, candidate_html, reference_screenshot, candidate_screenshot, tmp_dir=None, device="cpu", debug=False, include_pairs=False, include_block_pixelmatch=False, pixelmatch_threshold=0.1)`

Runs the checked-in WebCode2M/Design2Code OCR-free visual block metric through a local adapter.

Current behavior:

- Uses `research/source-repos/naturalcc/examples/webcode2m/scripts/evaluation/design2code/visual_score.py`.
- Instruments text blocks in temporary HTML files, renders them with Playwright, recovers block boxes by pixel diffing, and matches candidate/reference blocks.
- Uses `open-clip-torch` through a small compatibility shim instead of adding the old `clip` stack.
- Returns named JSON fields instead of the upstream tuple.
- Replaces the upstream shell calls and `rm` cleanup with controlled Python subprocesses and `TemporaryDirectory`/`Path.unlink`.

Output:

- `score`: average of size, text, position, text color, and masked-CLIP sub-scores.
- `weighted_area`: upstream block-area accounting value.
- `size`: matched block area coverage.
- `text`: matched text similarity.
- `position`: normalized block-position similarity.
- `text_color`: text color similarity.
- `masked_clip`: CLIP similarity after masking detected text blocks.
- `reference_block_count`, `candidate_block_count`, `matched_pair_count`: matcher diagnostics.
- `matched_pairs`: included only when `include_pairs=True`; each pair contains reference/candidate text, normalized bbox, color, and pair-level text/position/color scores.
- `block_pixelmatch`: included only when `include_block_pixelmatch=True`.

CLI:

```bash
uv run website-design-eval visual-block \
  test-site/index.html \
  reproductions/claude-attempt-01/index.html \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-01/screenshots/home.desktop.full.png
```

Include matched pairs and block crop pixelmatch:

```bash
uv run website-design-eval visual-block \
  test-site/index.html \
  reproductions/claude-attempt-01/index.html \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-01/screenshots/home.desktop.full.png \
  --include-pairs \
  --block-pixelmatch
```

Initial home-page results:

| Reproduction | Score ↑ | Size ↑ | Text ↑ | Position ↑ | Text color ↑ | Masked CLIP ↑ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.957 | 1.000 | 0.997 | 0.885 | 0.972 | 0.931 |
| `claude-attempt-02-bad` | 0.584 | 0.096 | 0.729 | 0.752 | 0.628 | 0.717 |

Caveat:

- This is now wired for experimentation, but it is still slower and more brittle than pixel/CLIP/text metrics. It should stay optional until we test it across more pages and states.

### `element_block_pixelmatch_score(reference_html, candidate_html, reference_screenshot, candidate_screenshot, tmp_dir=None, device="cpu", debug=False, include_pairs=False, pixelmatch_threshold=0.1)`

Runs crop-level pixelmatch over the matched block pairs from `visual_block_score`.

This does not introduce a new matcher. It reuses the Design2Code/WebCode2M block matcher, then compares the actual rendered pixels inside each matched reference/candidate block.

Output:

- `matched_pixelmatch`: area-weighted pixelmatch over matched block crops only.
- `coverage_score`: the visual block `size` score, so missing/hallucinated blocks still matter.
- `coverage_adjusted_score`: `matched_pixelmatch * coverage_score`; this is the primary score.
- `pair_count`, `scored_pair_count`: pair diagnostics.
- `visual_block`: the underlying visual block score summary.
- `matched_pairs`: included only when `include_pairs=True`; each pair includes its own `pixelmatch` result.

CLI:

```bash
uv run website-design-eval block-pixelmatch \
  test-site/index.html \
  reproductions/claude-attempt-01/index.html \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-01/screenshots/home.desktop.full.png
```

Initial home-page results:

| Reproduction | Coverage-adjusted ↑ | Matched crop pixelmatch ↑ | Block coverage ↑ | Matched pairs |
| --- | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.794 | 0.794 | 1.000 | 49 |
| `claude-attempt-02-bad` | 0.047 | 0.490 | 0.096 | 12 |

Interpretation:

- `matched_pixelmatch` answers "when the paper matcher says these blocks correspond, do their rendered crops actually look alike?"
- `coverage_adjusted_score` is stricter because it also penalizes missing or hallucinated blocks through the visual block coverage score.

### `bbox_geometry_score(reference_html, candidate_html, reference_screenshot, candidate_screenshot, tmp_dir=None, device="cpu", debug=False, include_pairs=False)`

Compares only the geometry of the matched visual blocks.

This is deliberately different from `element_block_pixelmatch_score`:

- Bbox geometry compares box coordinates and sizes: "did the matched text blocks land in similar places and occupy similar shapes?"
- Element block pixelmatch compares rendered pixels inside those boxes: "after matching the blocks, do the crops look alike?"

Output:

- `matched_iou`: area-weighted bbox intersection-over-union over matched pairs.
- `matched_area_similarity`: area-weighted ratio of smaller/larger matched box area.
- `matched_center_similarity`: area-weighted center-position similarity from the visual block matcher.
- `matched_bbox_score`: average of IoU, area similarity, and center similarity.
- `coverage_score`: visual block coverage, so missing or extra blocks still matter.
- `coverage_adjusted_score`: primary score, `matched_bbox_score * coverage_score`.

CLI:

```bash
uv run website-design-eval bbox-geometry \
  test-site/index.html \
  reproductions/claude-attempt-01/index.html \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-01/screenshots/home.desktop.full.png
```

Initial home-page results:

| Reproduction | Coverage-adjusted ↑ | Matched bbox score ↑ | IoU ↑ | Area similarity ↑ | Center similarity ↑ | Coverage ↑ |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.508 | 0.508 | 0.014 | 0.642 | 0.867 | 1.000 |
| `claude-attempt-02-bad` | 0.051 | 0.528 | 0.000 | 0.760 | 0.824 | 0.096 |

Caveat:

- Bbox IoU is very strict on full-page screenshots when page heights differ. The home good reproduction has high coverage and center similarity, but low IoU because full-page vertical normalization shifts text boxes. Treat this as a geometry diagnostic, not as a standalone final reward yet.

### `extract_cssom_snapshot(html_path, screenshot_path=None, viewport=None)`

Extracts rendered DOM/CSSOM facts from the browser with Playwright.

Output:

- `elements`: visible rendered elements with tag, role, type, text, accessible name, state flags, normalized bbox, pixel bbox, and computed styles.
- `controls`: subset of visible controls such as links, buttons, inputs, selects, textareas, role-bearing nodes, and focusable nodes.
- `element_count`, `control_count`, `viewport`, `document`, `normalize_size`.

Computed style groups:

- `typography`: font family, size, weight, line height, letter spacing, text alignment/transform.
- `color`: text, background, and border colors.
- `spacing`: padding, margin, row/column gap.
- `shape`: border width, style, and radius.
- `effects`: opacity, shadow, filter, transform.

This is an extraction primitive, not a score.

### `cssom_block_style_score(reference_html, candidate_html, reference_screenshot, candidate_screenshot, tmp_dir=None, device="cpu", debug=False, include_pairs=False, viewport=None, min_resolution_score=0.35)`

Compares computed CSSOM styles over the matched visual-block pairs.

This does not change `visual_block_score`. It reuses the Design2Code/WebCode2M matched pairs, resolves each block to a rendered DOM node inside its own page, then compares CSSOM style groups for those resolved nodes.

Output:

- `matched_cssom_score`: area-weighted CSSOM similarity over resolved matched pairs.
- `dom_resolution_score`: weighted share of matched visual-block pairs that could be resolved to DOM nodes.
- `visual_block_coverage_score`: underlying visual-block `size` score, including unmatched blocks.
- `resolution_score`, `coverage_score`: backwards-compatible aliases for those two fields.
- `coverage_adjusted_score`: primary score, `matched_cssom_score * resolution_score * coverage_score`.
- `group_scores`: typography, color, spacing, shape, effects, and layout sub-scores.
- `reference_snapshot`, `candidate_snapshot`: element/control counts and render dimensions.
- `visual_block`: unchanged underlying visual-block summary.
- `resolved_pairs`, `unresolved_pairs`: included only when `include_pairs=True`.

CLI:

```bash
uv run website-design-eval cssom-block-style \
  test-site/index.html \
  reproductions/claude-attempt-01/index.html \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-01/screenshots/home.desktop.full.png
```

Initial home-page results:

| Reproduction | Coverage-adjusted ↑ | Matched CSSOM ↑ | Resolution ↑ | Coverage ↑ | Resolved pairs |
| --- | ---: | ---: | ---: | ---: | ---: |
| `claude-attempt-01` | 0.850 | 0.856 | 0.993 | 1.000 | 48 / 49 |
| `claude-attempt-02-bad` | 0.060 | 0.632 | 1.000 | 0.096 | 12 / 12 |

Interpretation:

- `matched_cssom_score` asks whether matched rendered elements have similar browser-resolved styles.
- `coverage_adjusted_score` keeps the missing-block penalty from visual-block coverage, so a page does not score well by styling a small matched subset.
- The block-to-DOM resolution is within-page provenance only; cross-page correspondence still comes from the visual-block matcher.

### `mobile_overflow_tags(html_path, viewport=(390, 844), threshold_px=0, include_elements=False)`

Emits WebCoderBench-style mobile compatibility tags.

Output:

- `tags`: includes `mobile_horizontal_overflow` when document width exceeds viewport width beyond `threshold_px`.
- `horizontal_overflow_px`, `offending_element_count`, `viewport`, `document`.
- `offending_elements`: included only when `include_elements=True`.

CLI:

```bash
uv run website-design-eval mobile-overflow-tags test-site/index.html --threshold-px 4
```

This is a tag/measurement surface. We have not converted it into a reward score yet.

### `accessibility_control_tags(html_path, viewport=(1440, 900), include_elements=False)`

Emits WebCoderBench/Lighthouse-style control accessibility tags from rendered CSSOM.

Current checks:

- Missing accessible names on rendered controls.
- Missing labels/names on form controls.
- Specific tags such as `missing_button_name`, `missing_link_name`, and `missing_form_label` when applicable.

CLI:

```bash
uv run website-design-eval accessibility-control-tags test-site/index.html --include-elements
```

### `webcoderbench_tags(html_path, ...)`

Bundles the currently implemented WebCoderBench-inspired diagnostics:

- `accessibility_control_tags`
- `mobile_overflow_tags`

CLI:

```bash
uv run website-design-eval webcoderbench-tags test-site/index.html
```

This is intentionally small and does not require a screenshot.

### `webcoderbench_component_style_score(html_path, viewport=(1440, 900), card_keywords=("card",), include_components=False)`

Paper-formula fallback for WebCoderBench Component Style Consistency.

It extracts visible elements with card-related identifiers, groups parallel card components by parent container, flags structural/style inconsistency, and applies the paper formula:

```text
score = (1 - log2(1 + (inconsistent_num / (total_num + 1)))) * 100
```

This is not an official upstream implementation. The public artifacts checked expose leaderboard/results code, not evaluator code.

### `webcoderbench_icon_style_score(html_path, viewport=(1440, 900), include_icons=False)`

Paper-formula fallback for WebCoderBench Icon Style Consistency.

It extracts SVG icons, groups them by shared container relationship, checks the paper's style dimensions, and applies:

```text
score = max(0, 100 - 25 * failed_dimension_num)
```

Dimensions checked locally: icon-set consistency, size uniformity, stroke-width uniformity, underlying-shape consistency, background-shape consistency, background-color consistency, and background-padding uniformity.

### `webcoderbench_layout_consistency_score(screenshot, ...)`

Paper-formula fallback for WebCoderBench Layout Consistency.

It uses Canny edges plus morphology to extract layout contours, then counts alignment issues over detected elements. The score uses the paper formula:

```text
score = (1 - log2(1 + (total_errors / (total_elements + 1)))) * 100
```

This is a no-reference page-quality diagnostic. It is not a screenshot-to-reference matching metric.

### `webcoderbench_layout_sparsity_score(screenshot, tolerance=80, max_dimension=1200, ...)`

Paper-formula fallback for WebCoderBench Layout Sparsity.

It buckets grayscale values with tolerance 80, finds the largest continuous homogeneous rectangle with a histogram/monotonic-stack maximal-rectangle pass, computes the blank-space percentage, then applies:

```text
score = min(sqrt(100 - sparsity_rate) * 10, 100)
```

### `webcoderbench_visual_quality_scores(html_path, screenshot, viewport=(1440, 900), include_details=False)`

Bundles the implemented local WebCoderBench visual-quality fallback metrics:

- component style consistency
- icon style consistency
- layout consistency
- layout sparsity

CLI:

```bash
uv run website-design-eval webcoderbench-visual \
  test-site/index.html \
  test-site/screenshots/reference/home.desktop.full.png
```

### `presentation_diff_tags(reference, candidate, threshold=0.1, min_cluster_area=64, resize_candidate=True, include_clusters=True)`

Emits WebSee-style visual-difference tags from two screenshots.

Output:

- `tags`: `visual_diff`, `visual_diff_cluster`, and `large_visual_diff` when applicable.
- `diff_pixels`, `total_pixels`, `diff_ratio`, `cluster_count`.
- `clusters`: bounding boxes and areas for connected visual-diff regions, unless disabled.

CLI:

```bash
uv run website-design-eval presentation-diff-tags \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-02-bad/screenshots/home.desktop.full.png \
  --no-clusters
```

Initial home-page results:

| Reproduction | Diff ratio | Cluster count | Tags |
| --- | ---: | ---: | --- |
| `claude-attempt-01` | 0.114 | 788 | `visual_diff`, `visual_diff_cluster`, `large_visual_diff` |
| `claude-attempt-02-bad` | 0.457 | 448 | `visual_diff`, `visual_diff_cluster`, `large_visual_diff` |

This implements the visual-detection side of WebSee.

### `websee_dom_localization_tags(candidate_html, reference_screenshot, candidate_screenshot, ...)`

Maps WebSee-style visual diff clusters back to rendered candidate DOM/CSSOM boxes.

CLI:

```bash
uv run website-design-eval websee-localize \
  reproductions/claude-attempt-02-bad/index.html \
  test-site/screenshots/reference/home.desktop.full.png \
  reproductions/claude-attempt-02-bad/screenshots/home.desktop.full.png \
  --min-cluster-area 5000
```

This is a local fallback, not the upstream Java WebSee tool. The upstream repo was cloned to `research/source-repos/websee`, but its Maven build is blocked by old dependencies resolved through an HTTP USC Artifactory repository.

### `vlm_judge_score(reference, candidate, model="gpt-5.5", rubric=None)`

Uses an OpenAI vision-capable model to judge screenshot similarity against a Web2Code-style rubric.

Inputs:

- `reference`: reference screenshot path.
- `candidate`: candidate screenshot path.
- `model`: defaults to `gpt-5.5`.
- `rubric`: optional judging prompt. When omitted, the default prompt follows the Web2Code/WCGB ten-question GPT-4V rubric: layout consistency, element alignment, proportional accuracy, visual harmony, color/aesthetic match, aesthetic resemblance, font consistency, textual content, numeric/special-character accuracy, and UI consistency.

Output:

- The model is asked for only ten 0-10 scores. The local code then computes `dimensions`, Web2Code's four grouped averages, and `overall` deterministically.
- `{"raw": ...}` fallback if parsing fails.

Requirements:

- Requires `OPENAI_API_KEY`.
- Uses the OpenAI Responses API.

### `score_screenshot_pair(reference, candidate, include_clip=False)`

Aggregates one screenshot pair.

Output includes:

- `reference_render_sanity`
- `candidate_render_sanity`
- `pixelmatch`
- `mse`
- `mae`
- `ssim`
- Optional `clip`

### `score_capture_set(reference_dir, candidate_dir, include_clip=False)`

Scores all matching `.png` filenames in two directories.

Output includes:

- `summary`: mean metrics plus missing screenshot names.
- `pairs`: per-file metric payloads.

## Metric Interpretation

Pixel metrics are strict. `pixelmatch_score`, `mse_score`, and `mae_score` catch position, spacing, crop, and color errors, but they can over-penalize small layout shifts.

SSIM is more structural. It is better than raw pixel error for image-level similarity, but it still struggles with large vertical shifts, different page heights, and rearranged sections.

CLIP and DreamSim are perceptual. They can recognize semantic/style similarity when pixels are not aligned, but they can miss exact implementation mistakes such as wrong spacing, missing interactions, or incorrect text.

HTML text and DOM scores catch content and structure. They do not prove the visual render is correct.

VLM judging is flexible and rubric-aware. It is also the least deterministic and costs API calls, so it should be used as a final judge or audit signal rather than the only metric.

The intended scorer stack is therefore:

```text
render_sanity -> pixel/SSIM -> HTML/DOM -> optional visual-block/block-pixelmatch/CSSOM -> CLIP/DreamSim -> optional VLM judge
```
