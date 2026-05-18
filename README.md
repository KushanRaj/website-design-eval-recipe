# website-design-eval-recipe

## Scoring Functions

Full documentation is in [docs/scoring-functions.md](docs/scoring-functions.md).

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
- `pixelmatch_score`: pixelmatch-style YIQ threshold diff; it does not yet implement pixelmatch anti-aliasing or alpha handling.
- `mse_score`, `ssim_score`: WebCode2M-style image metrics, including OpenCV Lanczos4 candidate resizing.
- `mae_score`: DesignBench-style MAE with its pad-to-shared-size and resize preprocessing.
- `html_text_score`, `webcode2m_text_score`: WebCode2M visible-text BLEU-1 and ROUGE-1 recall.
- `webcode2m_dom_score`: faithful local mirror of WebCode2M `dom_sim` without importing the full optional dependency stack.
- `clip_similarity`: local CLIP cosine similarity using `ViT-B-32-quickgelu/openai`; this replaces the older `clip` package used upstream.
- `dreamsim_distance`: DreamSim wrapper using the local research repo; first use downloads weights.
- `visual_block_score`: optional WebCode2M/Design2Code OCR-free visual block metric adapter using the checked-in research code.
- `element_block_pixelmatch_score`: crop-level pixelmatch over the matched visual blocks from `visual_block_score`.
- `bbox_geometry_score`: local geometry-only metric over matched visual block bounding boxes.
- `cssom_block_style_score`: computed-style comparison over the matched visual blocks from `visual_block_score`.
- `cw_ssim_score`: explicit not-yet-wired surface for future Complex Wavelet SSIM.
- `vlm_judge_score`: optional OpenAI vision judge using `gpt-5.5`; requires `OPENAI_API_KEY`.
