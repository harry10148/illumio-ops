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


def test_an_unreleased_section_sits_above_the_releases():
    """`## [Unreleased]` 若存在，必須在最新版本標題**之上**。

    這條原本寫反了：它斷言 Unreleased 必須在版本標題之下，等於禁止本 repo
    （以及 Keep a Changelog）一直以來的作法——開發期間把新條目累積在最上面
    的 Unreleased 區，發版時才改成版本號。5.1.0 之前每一版都是這樣寫的，
    這條卻在下一次要寫 changelog 時才擋住人。

    它原本想守的是「發版時忘了把 Unreleased 改成版本號」，而那件事
    `test_version_matches_the_changelogs_newest_release` 已經守住了：版本號
    一旦升上去，最新的 `## [x.y.z]` 就對不上，測試直接紅。所以這裡改成守
    真正還沒人守的那件事——Unreleased 不可以掉到已發布的版本中間去。
    """
    text = CHANGELOG.read_text(encoding="utf-8")
    first_release = re.search(r"^## \[\d+\.\d+\.\d+\]", text, flags=re.M)
    unreleased = re.search(r"^## \[Unreleased\]", text, flags=re.M)
    if unreleased is None:
        return
    assert first_release is not None, "CHANGELOG 裡找不到任何已發布的版本標題"
    assert unreleased.start() < first_release.start(), (
        "`## [Unreleased]` 掉到已發布的版本之間了；它只能待在最上面。")
