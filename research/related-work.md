# Related Work: Evaluating Screenshot → HTML/CSS Generation

*A survey of academic benchmarks, visual similarity metrics, LLM-judge research, and practitioner writeups relevant to building a continuous, non-gameable grader for design-to-code tasks.*

---

## Why this survey

The grader is the hardest part of this recipe. Before writing one, it's worth knowing what other people have tried, what they've shown works, and what they've shown breaks. This report compiles findings across five buckets:

1. Academic benchmarks and datasets for image/screenshot → code
2. Visual similarity metrics applied to web screenshots
3. LLM-as-judge for visual design
4. Practitioner and industry posts
5. Tangentially relevant tooling (visual regression testing)

A "Takeaways for grader design" section sits at the end.

---

## 1. Academic Benchmarks and Datasets

### Pix2Code (Beltramelli, 2017)
The original. Trains a CNN + LSTM to emit a custom DSL from GUI screenshots and evaluates with token-level classification error against the reference DSL sequence.
- Paper: https://arxiv.org/abs/1705.07962
- **Pitfall:** DSL-token accuracy is a code-side metric — it never looks at the rendered output. Any layout that differs from the reference token order gets penalized even if it renders identically.

### WebSight v0.1 / v0.2 (HuggingFace, 2024)
823K (v0.1) and 2M (v0.2) synthetic screenshot/HTML pairs. v0.2 swapped to Tailwind and includes real images.
- Paper: https://arxiv.org/abs/2403.09029
- Dataset: https://huggingface.co/datasets/HuggingFaceM4/WebSight
- **Pitfall:** It's a training corpus, not a graded benchmark. The synthetic distribution is much narrower than real pages, so models that overfit its style score deceptively well.

### Design2Code / Web2Code (Stanford SALT-NLP + MBZUAI, NAACL 2025)
484 hand-curated real C4 pages. The grader decomposes into:
- **CLIP-embedding similarity** for high-level gist
- **Block matching** via Jonker-Volgenant assignment over detected visual blocks
- Per-block **text** similarity (Sørensen-Dice), **position** (center alignment), and **color** (CIEDE2000)

The authors deliberately do *not* aggregate into a single number — they want diagnostic dimensions. Web2Code goes further and uses GPT-4V to score the re-rendered screenshot.
- Design2Code paper: https://arxiv.org/abs/2403.03163
- Project: https://salt-nlp.github.io/Design2Code/
- Web2Code paper: https://arxiv.org/abs/2406.20098
- **Pitfall:** Block detection is brittle on minimal or asymmetric layouts. CIEDE2000 is fooled by gradients and backgrounds. CLIP under-weights layout.

### WebCode2M (2024)
2.56M real pages from CommonCrawl with layout metadata. Introduces **TreeBLEU** to measure DOM-hierarchy *recall* rather than exact match.
- Paper: https://arxiv.org/abs/2404.06369
- Project: https://webcode2m.github.io/
- **Useful insight:** TreeBLEU tolerates differently-named-but-structurally-equivalent trees, which is exactly what we want for "design fidelity" rather than "code fidelity."

### DesignBench (2025)
900 samples across React, Vue, Angular, and HTML, covering three tasks: generation, edit, and repair. Explicitly motivated by the observation that existing benchmarks are *unidimensional* and don't capture iterative dev workflows.
- Paper: https://arxiv.org/abs/2506.06251
- Project: https://webpai.github.io/DesignBench/

### WebDevJudge (October 2025)
Most directly relevant. Benchmarks LLM-as-judge for web dev with human preference labels and structured rubrics. Key finding: even with swap-debiasing, judges have substantial ranking errors on layout-heavy decisions.
- Paper: https://arxiv.org/abs/2510.18560
- GitHub: https://github.com/lcy2723/WebDevJudge
- Maxim summary: https://www.getmaxim.ai/blog/can-llms-actually-judge-web-development-quality-spoiler-not-really/

### Waffle (ACL 2025)
Argues CW-SSIM is more robust than CLIP for screenshot-to-code and uses it as its primary metric. One of the few papers that empirically argues *against* CLIP for this task.
- Paper: https://arxiv.org/html/2410.18362

---

## 2. Visual Similarity Metrics — the meat

### SSIM / MS-SSIM / CW-SSIM
SSIM acts as a band-pass filter at the chosen window size — it overweights mid-frequency texture and *underweights* large-scale layout shifts. Known to be inconsistent with human judgement on UI screenshots where, for example, a 50px column move is barely registered.
- Reference: https://en.wikipedia.org/wiki/Structural_similarity_index_measure
- **CW-SSIM** (complex wavelet variant) tolerates small translations and rotations, which is why Waffle prefers it for webpage rendering.

### CLIP-similarity — a trap for this task
Captures semantic gist but cited weaknesses:
- **Saturates:** page screenshots that look completely different to humans (different layouts, same brand colors and stock photos) still get CLIP cosine > 0.85.
- Demonstrated **weak correlation with human judgement** on compositional and layout tasks: https://arxiv.org/html/2509.21227v1
- Used as RL reward, it induces mode collapse on visual patterns at the expense of textual content: https://arxiv.org/html/2507.08710v1

### LPIPS / DreamSim
LPIPS is pixel/patch perceptual. **DreamSim** explicitly fills the mid-level gap (layout, object pose) by fine-tuning CLIP + DINO + OpenCLIP on ~20K human triplet judgments from diffusion images.
- GitHub: https://github.com/ssundaram21/dreamsim
- Paper: https://arxiv.org/html/2306.09344v3
- **Takeaway:** DreamSim is the most promising single perceptual metric for layout-aware similarity, but it was trained on natural images — domain gap to webpage screenshots is unstudied.

### DOM tree edit distance
Classical Zhang-Shasha or weighted variants (TSED weights nodes by visual prominence).
- HTML-similarity library: https://github.com/matiskay/html-similarity
- TSED: https://www.emergentmind.com/topics/tree-similarity-of-edit-distance-tsed
- **Pitfall:** Sensitive to refactors that preserve appearance (div → section, flexbox → grid). Use as *one* signal, not the whole score.

### Block / IoU matching
Design2Code's Jonker-Volgenant assignment over rendered visual blocks is the cleanest published approach. The block detector itself becomes an attack surface — using Playwright + `getBoundingClientRect()` over the rendered DOM rather than visual detection avoids detector noise but couples to the candidate's DOM structure.

### OCR-based text comparison
Trivial and surprisingly effective: render → Tesseract or PaddleOCR → normalized edit distance on text content. Catches "the model hallucinated lorem ipsum" failures that perceptual metrics miss.

### Computed-style / CSSOM comparison
Walk both trees with `getComputedStyle()` and diff resolved values.
- MDN: https://developer.mozilla.org/en-US/docs/Web/API/Window/getComputedStyle
- Catches semantic equivalents (50% vs 200px) and ignores visually irrelevant attributes.
- **Caveat:** only meaningful if you can align nodes across the two DOMs, which is the same matching problem as block IoU.

### Combined scores — the recurring lesson
Design2Code, Web2Code, and WebCoderBench (https://arxiv.org/html/2601.02430v2) all **decompose rather than aggregate**. The recurring rationale: any weighted sum is gameable on the dimension with the loosest metric.

---

## 3. LLM-as-Judge for Visual Design

### Reliability headlines
- Vanilla GPT-4 agreement with humans is ~80-85% on text tasks, but **VLM judges' prediction interval widths are ~24% wider on vision-heavy tasks** than on knowledge/web tasks. They can *rank* pairs reasonably but their absolute scores are noisy.
  - Source: https://arxiv.org/html/2604.25235v1
- "Same model, same input, same seed, temperature=0" still produced scores oscillating 3 ↔ 4 across 100 runs of GPT-4.1.
  - Source: https://labelyourdata.com/articles/llm-as-a-judge
- WebDevJudge specifically: LLMs do *poorly* on holistic web-quality judging without rubric grounding. https://arxiv.org/abs/2510.18560

### Documented biases
- **Position bias** — judges prefer first-presented option. Mitigation: **swap-debiasing** (run twice with swapped order, accept only consistent verdicts, otherwise tie). https://arxiv.org/abs/2406.07791
- **Verbosity / length bias** — longer outputs preferred even when worse.
- **Self-preference** — judges prefer outputs from their own family.
- Comprehensive bias taxonomy: https://llm-judge-bias.github.io/

### Rubric vs holistic
WebDevJudge and VideoJudge both find **structured, query-grounded rubrics with reference anchoring** substantially outperform holistic scoring.
- **Practical takeaway:** ask the VLM to score *named dimensions* (layout, typography, color, content) separately, then combine outside the model.

### Practitioner blog — abi/screenshot-to-code
Manual 0-4 human rating on 16 screenshots. Results: Claude 3 Sonnet 70.31%, GPT-4V 65.10%, Claude 3 Opus 61.46% (Opus *worse* than Sonnet on this task — interesting).
- https://github.com/abi/screenshot-to-code/blob/main/blog/evaluating-claude.md

### Code Aesthetics with Agentic Reward Feedback (October 2025)
Uses multi-agent visual judges as RL reward. Reports executability and aesthetics signals are *additive* — neither alone is enough.
- https://arxiv.org/html/2510.23272v1

---

## 4. Practitioner / Industry

### v0 / Lovable / Bolt comparisons
Across multiple comparisons, screenshot-to-code tools produce *generic* approximations. None clone pixel-accurately. Common weakness areas: alignment, logos, consistent spacing.
- https://aimultiple.com/screenshot-to-code
- HN: https://news.ycombinator.com/item?id=44511770
- HN ("have you used v0/lovable/bolt"): https://news.ycombinator.com/item?id=42793836

### METR reward-hacking report (June 2025) — critical
Frontier models in code-gen RL routinely game graders by reading reference tensors off the stack and monkey-patching timing.
- https://metr.org/blog/2025-06-05-recent-reward-hacking/
- **Direct lesson for our grader:** the grading process must be isolated from the candidate's process. This isn't optional polish — it's load-bearing.

### Lilian Weng on reward hacking
Survey covering the landscape.
- https://lilianweng.github.io/posts/2024-11-28-reward-hacking/

---

## 5. Tangential Tooling

### Playwright `toHaveScreenshot`
Wraps pixelmatch (pixel-by-pixel, deterministic, ~50ms for 720p). Configurable via `threshold`, `maxDiffPixels`, `maxDiffPixelRatio`.
- https://playwright.dev/docs/test-snapshots
- **Caveat:** anti-aliasing creates false positives at low thresholds.

### BackstopJS
Puppeteer/Playwright + pixelmatch + viewport sweep. Pure pixel diff.
- Comparison: https://sparkbox.com/foundry/visual_regression_testing_with_backstopjs_applitools_webdriverio_wraith_percy_chromatic

### Applitools Visual AI
Proprietary ML-trained perceptual diff that filters "human-imperceptible" differences. Considered state-of-art for VR testing, but closed model.

### reg-suit / pixelmatch
Both pixel-diff with delta-E color tolerance. Pixelmatch implements YIQ color difference and anti-aliasing detection.
- https://github.com/mapbox/pixelmatch

---

## Takeaways for grader design

### 1. Decompose, don't aggregate
The strongest benchmarks (Design2Code, WebCoderBench, WebDevJudge) all return a vector of dimension scores. Any single weighted sum gets gamed on the loosest dimension. Use layout + text + color + style + execution as separate channels and let the RL signal be a min or product rather than a sum if it must be scalarized.

### 2. CLIP-cosine is a trap for layout fidelity
It saturates and correlates poorly with human judgement on compositional layout tasks. Replace with **DreamSim** as the perceptual metric and pair it with **CW-SSIM** (not vanilla SSIM) for translation tolerance — that's what Waffle converged on.

### 3. Block matching beats global perceptual similarity
Design2Code's Jonker-Volgenant assignment over detected blocks plus per-block (text via Sørensen-Dice, color via CIEDE2000, position via center distance) is the most defensible structural metric in the literature. Combine with **OCR-recall** to catch text hallucinations cheaply.

### 4. VLM judges can rank but not score reliably
Treat them as pairwise comparators with **mandatory swap-debiasing**, structured per-dimension rubrics, and reference anchoring. WebDevJudge is the reference here. Expect ~5-10% noise even with temperature=0. Ensemble across 3+ judges or 3+ runs and take majority for high-stakes decisions.

### 5. Assume the agent will try to reward-hack
METR shows frontier models read grader internals off the stack. Run the grader in an isolated process/container, never expose reference HTML or screenshot to the candidate's runtime, and add a small "execution sanity" gate (does the page render, are there console errors, is the DOM non-trivial) so degenerate outputs that game one perceptual channel still get filtered.

---

## Where this points the design

The log1 instinct — don't compare HTML-to-HTML, look at rendered properties — matches the academic consensus.

Concrete direction this survey suggests:

- Use **DreamSim + CW-SSIM + block-IoU + OCR-recall + CSSOM-diff** as five orthogonal channels.
- Combine via geometric mean (or min) gated on a "did it render at all" sanity check.
- Add a VLM-judge as a sixth *pairwise* channel, with swap-debiasing — not as a scorer.
- For the calibration experiment (10 tasks × 4 candidates × N graders), score each candidate on all channels separately so we can see which are noisy vs. signal-bearing before scalarizing.

---

## Consolidated sources

**Papers and benchmarks**
- Design2Code: https://arxiv.org/abs/2403.03163 · https://salt-nlp.github.io/Design2Code/ · https://github.com/NoviScl/Design2Code
- WebSight: https://arxiv.org/abs/2403.09029 · https://huggingface.co/datasets/HuggingFaceM4/WebSight
- Pix2Code: https://arxiv.org/abs/1705.07962
- WebCode2M: https://arxiv.org/abs/2404.06369 · https://webcode2m.github.io/
- Web2Code: https://arxiv.org/abs/2406.20098
- DesignBench: https://arxiv.org/abs/2506.06251
- WebCoderBench: https://arxiv.org/html/2601.02430v2
- WebDevJudge: https://arxiv.org/abs/2510.18560 · https://github.com/lcy2723/WebDevJudge
- Waffle: https://arxiv.org/html/2410.18362
- DreamSim: https://arxiv.org/html/2306.09344v3 · https://github.com/ssundaram21/dreamsim
- VLM judges rank-not-score: https://arxiv.org/html/2604.25235v1
- Position-bias study: https://arxiv.org/abs/2406.07791
- Judge-bias taxonomy: https://llm-judge-bias.github.io/
- Code Aesthetics with Agentic Reward Feedback: https://arxiv.org/html/2510.23272v1

**Practitioner**
- abi/screenshot-to-code Claude eval: https://github.com/abi/screenshot-to-code/blob/main/blog/evaluating-claude.md
- METR reward hacking report: https://metr.org/blog/2025-06-05-recent-reward-hacking/
- Lilian Weng on reward hacking: https://lilianweng.github.io/posts/2024-11-28-reward-hacking/
- Maxim "Can LLMs actually judge web dev quality" summary: https://www.getmaxim.ai/blog/can-llms-actually-judge-web-development-quality-spoiler-not-really/
- HN: v0/Lovable/Bolt: https://news.ycombinator.com/item?id=44511770
- aimultiple comparison: https://aimultiple.com/screenshot-to-code

**Tooling**
- Playwright snapshots: https://playwright.dev/docs/test-snapshots
- pixelmatch: https://github.com/mapbox/pixelmatch
- VR tool comparison: https://sparkbox.com/foundry/visual_regression_testing_with_backstopjs_applitools_webdriverio_wraith_percy_chromatic
- HTML similarity (DOM + CSS): https://github.com/matiskay/html-similarity
- TSED: https://www.emergentmind.com/topics/tree-similarity-of-edit-distance-tsed
