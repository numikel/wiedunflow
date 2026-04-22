# Visual regression baselines

Golden PNG snapshots captured on **Ubuntu Linux** (per Sprint 5 plan decision
#2) comparing the rendered `tutorial.html` against 4 combinations:

| Viewport | Theme | Filename |
|---|---|---|
| Desktop 1440×900 | light | `linux/desktop_1440x900_light.png` |
| Desktop 1440×900 | dark | `linux/desktop_1440x900_dark.png` |
| Mobile 375×812 | light | `linux/mobile_375x812_light.png` |
| Mobile 375×812 | dark | `linux/mobile_375x812_dark.png` |

Tolerance: **1 %** of differing pixels (ADR-0011 anti-aliasing envelope).

## Regenerating baselines

Baselines must be captured on Ubuntu. The GitHub Actions workflow
`.github/workflows/visual.yml` runs the suite on every PR that touches the
renderer; when an intentional visual change is being merged, regenerate via:

```bash
# Ubuntu / WSL / Linux CI
CODEGUIDE_VISUAL_UPDATE=1 uv run pytest tests/visual/
```

Then commit the updated `linux/*.png` files in the same PR as the change. The
diff tool will surface any stray unintended visual drift.

## Why Linux-only

Anti-aliasing differs meaningfully between OSes (Windows ClearType vs Linux
FreeType vs macOS Core Text). Comparing against a single OS baseline keeps the
signal-to-noise ratio useful — Windows / macOS runners still run the Playwright
**functional** suite in `tests/integration/test_track_c_navigation.py`.
