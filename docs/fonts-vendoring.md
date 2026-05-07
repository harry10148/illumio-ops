# Font Vendoring

All web fonts are self-hosted to satisfy C1 (offline bundle) and avoid CSP/CDN issues.

## Current fonts

| File | License | Source | Size | Used by |
|---|---|---|---|---|
| NotoSansCJKtc-Regular.otf | OFL | https://github.com/notofonts/noto-cjk | 15.7 MB | CJK fallback (PDF, GUI when CJK glyphs needed) |
| Montserrat-latin.woff2 | OFL | https://github.com/JulietaUla/Montserrat | 37 KB | Legacy email/report inline styles (`reporter.py`, `report_generator.py`, `report_css.py`, `chart_renderer.py`) — removed from GUI CSS fallback chains (Track A Task 9); woff2 retained until report layer migrated |
| SpaceGrotesk-VF.woff2 | OFL | https://github.com/floriankarsten/space-grotesk | 48 KB | GUI heading (post Track A) |
| Inter-VF.woff2 | OFL | https://github.com/fontsource/font-files/tree/main/fonts/variable/inter (latin subset) | 48 KB | GUI body (post Track A); Report body |
| JetBrainsMono-VF.woff2 | OFL | https://github.com/fontsource/font-files/tree/main/fonts/variable/jetbrains-mono (latin subset) | 40 KB | Code / table figures (tnum) |

## How to update

1. Download new variable woff2 from the Source URL above. For Inter and JetBrains Mono, the canonical source is the @fontsource-variable npm package's latin subset, NOT the upstream repo (which yields a much larger file with all languages).
2. Verify with `fontTools.ttLib.TTFont(...).flavor == 'woff2'` and `'fvar' in font`.
3. Replace file in `src/static/fonts/`.
4. Update this doc with new size.
5. No build step needed — files served directly by Flask static.

## Why variable fonts

- One file covers all weights 100-900 (avoids 4 separate files for Regular/Medium/SemiBold/Bold)
- Smaller total bundle (~40-52 KB per file vs 4 × 30-40 KB = 120-160 KB)
- Smoother weight interpolation in HTML

## Sourcing notes

- **SpaceGrotesk-VF.woff2**: downloaded from `fonts/woff2/SpaceGrotesk[wght].woff2` in the floriankarsten/space-grotesk GitHub repo (wght 300-700)
- **Inter-VF.woff2**: latin-subset variable font from `@fontsource-variable/inter` v5.2.8 (`inter-latin-wght-normal.woff2`); covers wght 100-900. The full `InterVariable.woff2` from the rsms/inter v4.0 release is 340 KB (all scripts) — the fontsource latin subset was used instead to meet the <280 KB total target.
- **JetBrainsMono-VF.woff2**: latin-subset variable font from `@fontsource-variable/jetbrains-mono` v5.2.8 (`jetbrains-mono-latin-wght-normal.woff2`); covers wght 100-800. The JetBrains/JetBrainsMono v2.304 release zip only includes static woff2 + variable ttf (no variable woff2), so fontsource was used.
