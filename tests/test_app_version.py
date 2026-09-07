import re
from pathlib import Path

import src

CHANGELOG = Path(__file__).resolve().parent.parent / "CHANGELOG.md"


def test_version_is_pure_semver():
    assert re.fullmatch(r"\d+\.\d+\.\d+", src.__version__), src.__version__


def test_version_matches_the_changelogs_newest_release():
    """`src.__version__` 必須等於 CHANGELOG 最上面那個版本標題。

    這條原本是 `assert src.__version__ == "5.0.0"`——一個寫死的值。它確實逼人在
    改版本號時做一次刻意的動作，但它管不到真正會出事的那一半：**版本號與
    CHANGELOG 不同步**。發版時把 `__version__` 改了卻忘了改 CHANGELOG 標題
    （或反過來），寫死值的版本照樣綠，而使用者拿到的是一個版本號對不上發行
    紀錄的產物。

    改成比對兩者之後，「刻意」的要求沒有放寬——要讓它綠，仍然得動手寫下新的
    版本標題——而且多守住一件事。
    """
    heads = re.findall(r"^## \[(\d+\.\d+\.\d+)\]", CHANGELOG.read_text(encoding="utf-8"),
                       flags=re.M)
    assert heads, "CHANGELOG 裡找不到任何 `## [x.y.z]` 版本標題"
    assert src.__version__ == heads[0], (
        f"src.__version__ 是 {src.__version__}，但 CHANGELOG 最新的版本是 "
        f"{heads[0]}。發版時兩邊要一起改。")


def test_the_newest_release_is_not_still_called_unreleased():
    """`## [Unreleased]` 不得出現在最新版本標題之上。

    發版時忘了把 Unreleased 改成版本號，是這個檔案最常見的漏法——上面那條比對
    的是「最新的**版本**標題」，一個還掛著 Unreleased 的 CHANGELOG 照樣能過。
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    first_release = re.search(r"^## \[\d+\.\d+\.\d+\]", text, flags=re.M)
    unreleased = re.search(r"^## \[Unreleased\]", text, flags=re.M)
    if unreleased is None:
        return
    assert unreleased.start() > first_release.start(), (
        "CHANGELOG 最上面還是 `## [Unreleased]`；發版時要把它改成版本號與日期。")
