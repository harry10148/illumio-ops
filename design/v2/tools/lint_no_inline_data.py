"""mockup 禁手寫資料：陣列裡的物件字面值、>4 屬性的物件字面值都算違規。
豁免：檔案該行前一行有 `// lint-allow-inline-data: <理由>`。"""
import pathlib, re, sys

ARRAY_OF_OBJ = re.compile(r"\[\s*\{")
BIG_OBJ = re.compile(r"\{(?:[^{}]*?[:][^{}]*?,){4,}")   # ≥5 個 key 的物件
ALLOW = "lint-allow-inline-data"

def lint_source(src: str) -> list[str]:
    out, lines = [], src.splitlines()
    for i, line in enumerate(lines):
        if i > 0 and ALLOW in lines[i - 1]:
            continue
        if ARRAY_OF_OBJ.search(line):
            out.append(f"L{i+1}: array-of-objects literal")
        elif BIG_OBJ.search(line):
            out.append(f"L{i+1}: object literal with >4 keys")
    return out

def main():
    root = pathlib.Path(__file__).resolve().parents[1]
    bad = False
    for p in sorted(list((root / "mockup").rglob("*.mjs")) + list((root / "mockup").rglob("*.js"))
                    + list((root / "pitch").rglob("*.html"))):
        for msg in lint_source(p.read_text()):
            print(f"{p.relative_to(root)}: {msg}"); bad = True
    sys.exit(1 if bad else 0)

if __name__ == "__main__":
    main()
