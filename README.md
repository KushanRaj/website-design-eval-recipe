# website-design-eval-recipe

## Scoring Functions

Full documentation is in [docs/scoring-functions.md](docs/scoring-functions.md). WebSight-specific recipe notes are in [docs/websight-recipe-notes.md](docs/websight-recipe-notes.md).

Run a screenshot pair:

```bash
uv run website-design-eval pair test-site/screenshots/reference/home.desktop.full.png reproductions/claude-attempt-01/screenshots/home.desktop.full.png
```

Run all matching PNG names in two capture directories:

```bash
uv run website-design-eval directory test-site/screenshots/reference reproductions/claude-attempt-01/screenshots
```

Add `--clip` to include local CLIP image-embedding similarity. The CLIP model is loaded lazily through `open-clip-torch`; the first call downloads weights. In this workspace the checked download used `.cache/open_clip`.

Implemented in `website_design_eval`:

- `render_sanity_score`: screenshot health check for blank/failed renders.
- `screenshot_size_match_score`: compares raw screenshot canvas dimensions before resizing.
- `pixelmatch_score`: faithful Python port of Mapbox pixelmatch mismatch counting, including YIQ thresholding, anti-alias exclusion, and alpha/checkerboard handling.
- `mse_score`, `ssim_score`: WebCode2M-style image metrics, including OpenCV Lanczos4 candidate resizing.
- `mae_score`: DesignBench-style MAE with its pad-to-shared-size and resize preprocessing.
- `html_text_score`, `webcode2m_text_score`: WebCode2M visible-text BLEU-1 and ROUGE-1 recall.
- `webcode2m_dom_score`: faithful local mirror of WebCode2M `dom_sim` without importing the full optional dependency stack.
- `extract_webcode2m_bbox_tree`: faithful local mirror of WebCode2M's rendered bbox-tree extraction/serialization surface.
- `clip_similarity`: local CLIP cosine similarity using `ViT-B-32-quickgelu/openai`; this replaces the older `clip` package used upstream.
- `dreamsim_distance`: DreamSim wrapper using the full ensemble by default; first use downloads weights.
- `visual_block_score`: optional WebCode2M/Design2Code OCR-free visual block metric adapter using the checked-in research code.
- `element_block_pixelmatch_score`: crop-level pixelmatch over the matched visual blocks from `visual_block_score`.
- `bbox_geometry_score`: local geometry-only metric over matched visual block bounding boxes.
- `cssom_block_style_score`: computed-style comparison over the matched visual blocks from `visual_block_score`.
- `mobile_overflow_tags`, `accessibility_control_tags`, `webcoderbench_tags`: WebCoderBench-inspired diagnostic tag surfaces.
- `webcoderbench_component_style_score`, `webcoderbench_icon_style_score`, `webcoderbench_layout_consistency_score`, `webcoderbench_layout_sparsity_score`: paper-formula WebCoderBench visual-quality fallback metrics.
- `webcoderbench_visual_quality_scores`: bundles the implemented local WebCoderBench visual-quality fallback metrics.
- `presentation_diff_tags`, `websee_dom_localization_tags`: WebSee-inspired visual diff clustering and local DOM localization.
- `cw_ssim_score`: explicit not-yet-wired surface for future Complex Wavelet SSIM.
- `vlm_judge_score`: optional OpenAI vision judge using a Web2Code-style ten-dimension rubric; requires `OPENAI_API_KEY`.
