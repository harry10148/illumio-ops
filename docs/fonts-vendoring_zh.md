# 字型自帶化(Font Vendoring)

> [English](fonts-vendoring.md) | [繁體中文](fonts-vendoring_zh.md)

所有 web 字型都改為自帶,以滿足 C1(離線安裝包)需求,並避開 CSP / CDN 的問題。

## 目前使用的字型

| 檔案 | License | 來源 | 大小 | 使用位置 |
|---|---|---|---|---|
| NotoSansCJKtc-Regular.otf | OFL | https://github.com/notofonts/noto-cjk | 15.7 MB | CJK 後備字型(PDF、GUI 需 CJK 字符時)|
| Montserrat-latin.woff2 | OFL | https://github.com/JulietaUla/Montserrat | 37 KB | 舊版 email/report inline styles(`reporter.py`、`report_generator.py`、`report_css.py`、`chart_renderer.py`)— 已從 GUI CSS 後備鏈移除(Track A Task 9);woff2 檔保留至 report 層完成遷移 |
| SpaceGrotesk-VF.woff2 | OFL | https://github.com/floriankarsten/space-grotesk | 48 KB | GUI 標題(Track A 後)|
| Inter-VF.woff2 | OFL | https://github.com/fontsource/font-files/tree/main/fonts/variable/inter(latin subset)| 48 KB | GUI body(Track A 後);Report body |
| JetBrainsMono-VF.woff2 | OFL | https://github.com/fontsource/font-files/tree/main/fonts/variable/jetbrains-mono(latin subset)| 40 KB | 程式碼 / 表格數字(tnum)|

## 如何更新

1. 從上表的 Source URL 下載新版 variable woff2。Inter 與 JetBrains Mono 的正規來源是 `@fontsource-variable` npm 套件的 latin subset,**不是**上游 repo(後者會給你包含所有語系、檔案大很多的版本)。
2. 用 `fontTools.ttLib.TTFont(...).flavor == 'woff2'` 與 `'fvar' in font` 驗證。
3. 取代 `src/static/fonts/` 內的對應檔案。
4. 把新檔案大小更新到本文件。
5. 不需要 build step — Flask static 直接服務檔案。

## 為什麼用 variable fonts

- 一個檔案就涵蓋 100-900 全部字重(避免 Regular / Medium / SemiBold / Bold 4 個獨立檔案)
- 整體 bundle 較小(~40-52 KB/檔 vs 4 × 30-40 KB = 120-160 KB)
- HTML 上字重切換更平滑

## 來源備註

- **SpaceGrotesk-VF.woff2**:從 floriankarsten/space-grotesk GitHub repo 的 `fonts/woff2/SpaceGrotesk[wght].woff2` 下載(wght 300-700)
- **Inter-VF.woff2**:`@fontsource-variable/inter` v5.2.8 的 latin-subset variable font(`inter-latin-wght-normal.woff2`);涵蓋 wght 100-900。rsms/inter v4.0 release 的完整 `InterVariable.woff2` 是 340 KB(包含所有 scripts)— 為了壓在 <280 KB 的 bundle 目標內,改用 fontsource latin subset。
- **JetBrainsMono-VF.woff2**:`@fontsource-variable/jetbrains-mono` v5.2.8 的 latin-subset variable font(`jetbrains-mono-latin-wght-normal.woff2`);涵蓋 wght 100-800。JetBrains/JetBrainsMono v2.304 release 的 zip 只內含 static woff2 + variable ttf(沒 variable woff2),所以採用 fontsource。
