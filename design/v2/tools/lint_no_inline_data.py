"""mockup 禁手寫資料：陣列裡的物件字面值、>4 屬性的物件字面值都算違規。
豁免：檔案該行前一行有 `// lint-allow-inline-data: <理由>`。"""
import pathlib, re, sys

ALLOW = "lint-allow-inline-data"

def _strip_comments_and_strings(src: str) -> str:
    """Strip line comments, block comments, and string/template literals.
    Keeps newlines and structure so line numbers remain correct.
    Handles escapes minimally (\\, \", \', backtick)."""
    result = []
    i = 0
    while i < len(src):
        # Block comment
        if i + 1 < len(src) and src[i:i+2] == '/*':
            j = src.find('*/', i + 2)
            if j != -1:
                # Replace content with spaces, keep newlines
                block = src[i:j+2]
                replacement = ''
                for c in block:
                    replacement += '\n' if c == '\n' else ' '
                result.append(replacement)
                i = j + 2
                continue
            else:
                i += 1
                continue

        # Line comment
        if i + 1 < len(src) and src[i:i+2] == '//':
            j = src.find('\n', i)
            if j != -1:
                result.append(' ' * (j - i) + '\n')
                i = j + 1
            else:
                result.append(' ' * (len(src) - i))
                i = len(src)
            continue

        # String with double quotes
        if src[i] == '"':
            start = i
            i += 1
            while i < len(src):
                if src[i] == '\\' and i + 1 < len(src):
                    i += 2
                elif src[i] == '"':
                    i += 1
                    break
                else:
                    i += 1
            result.append(' ' * (i - start))
            continue

        # String with single quotes
        if src[i] == "'":
            start = i
            i += 1
            while i < len(src):
                if src[i] == '\\' and i + 1 < len(src):
                    i += 2
                elif src[i] == "'":
                    i += 1
                    break
                else:
                    i += 1
            result.append(' ' * (i - start))
            continue

        # Template literal with backticks
        if src[i] == '`':
            start = i
            i += 1
            while i < len(src):
                if src[i] == '\\' and i + 1 < len(src):
                    i += 2
                elif src[i] == '`':
                    i += 1
                    break
                else:
                    i += 1
            result.append(' ' * (i - start))
            continue

        result.append(src[i])
        i += 1

    return ''.join(result)

def _is_object_literal(stripped: str, pos: int) -> bool:
    """Check if the { at pos is an object literal (not a code block or destructuring pattern).

    Object literal indicators: follows = ( , [ : or keyword 'return'.
    Destructuring patterns: follows const/let/var (never object literals).
    Code blocks: follow ) > } { ; or keywords like if/for/while/switch/function/else/do/try.
    Unknown predecessors (throw, yield, etc.) default to object literal."""

    # Find previous non-whitespace character
    j = pos - 1
    while j >= 0 and stripped[j] in ' \t\n\r':
        j -= 1

    if j < 0:
        # Start of file is a code block
        return False

    prev_char = stripped[j]

    # Object literal indicators: = ( , [ :
    if prev_char in '=([,:':
        return True

    # Code block indicators: ) > } { ;
    if prev_char in ')>}{;':
        return False

    # Check for keyword before the brace
    # Extract the word before position
    k = j
    while k >= 0 and (stripped[k].isalnum() or stripped[k] == '_'):
        k -= 1

    if k < j:
        keyword = stripped[k+1:j+1]

        # Destructuring patterns: const/let/var always bind, never object literals
        if keyword in {'const', 'let', 'var'}:
            return False

        # Code block keywords
        code_block_keywords = {'if', 'for', 'while', 'switch', 'function', 'else', 'do', 'try', 'catch', 'finally'}
        if keyword in code_block_keywords:
            return False

        # Arrow function with code block: => {
        if keyword == '' and prev_char == '>':  # Check for =>
            if j >= 1 and stripped[j-1] == '=':
                return False

    # Default: unknown predecessors (throw, yield, etc.) → assume object literal
    return True

def lint_source(src: str) -> list[str]:
    """Scan source for inline data violations using object-literal detection and comma counting."""
    out = []
    original_lines = src.splitlines()
    stripped = _strip_comments_and_strings(src)

    # Violation A: array-of-objects - look for [ followed by { across newlines
    # Only flag if the [ would create an object literal context
    i = 0
    while i < len(stripped):
        if stripped[i] == '[':
            # Find next non-whitespace char
            j = i + 1
            while j < len(stripped) and stripped[j] in ' \t\n\r':
                j += 1
            if j < len(stripped) and stripped[j] == '{':
                # Found potential array of objects
                line_num = src[:i].count('\n') + 1
                # Check allow marker in original lines
                if line_num > 1 and ALLOW in original_lines[line_num - 2]:
                    i += 1
                    continue
                out.append(f"L{line_num}: array-of-objects literal")
        i += 1

    # Violation B: big objects - use object-literal detection and count top-level commas
    i = 0
    while i < len(stripped):
        if stripped[i] == '{':
            # Check if this is an object literal
            if not _is_object_literal(stripped, i):
                i += 1
                continue

            line_num = src[:i].count('\n') + 1

            # Check allow marker in original lines
            if line_num > 1 and ALLOW in original_lines[line_num - 2]:
                i += 1
                continue

            # Count top-level commas and colons (at this brace's depth level)
            # Bare destructuring patterns {a, b, c} have 0 colons and won't be flagged
            # Real data objects {a: 1, b: 2, c: 3} have colons and will be flagged if properties > 4
            depth = 0
            comma_count = 0
            colon_count = 0
            paren_depth = 0
            bracket_depth = 0
            j = i
            trailing_comma = False

            while j < len(stripped):
                if stripped[j] == '{':
                    if j == i:
                        depth = 1
                    else:
                        depth += 1
                elif stripped[j] == '}':
                    if depth == 1:
                        # Check for trailing comma before }
                        k = j - 1
                        while k >= i and stripped[k] in ' \t\n\r':
                            k -= 1
                        if k >= i and stripped[k] == ',':
                            trailing_comma = True
                        break
                    else:
                        depth -= 1
                elif stripped[j] == '(':
                    paren_depth += 1
                elif stripped[j] == ')':
                    paren_depth -= 1
                elif stripped[j] == '[':
                    bracket_depth += 1
                elif stripped[j] == ']':
                    bracket_depth -= 1
                elif stripped[j] == ',' and depth == 1 and paren_depth == 0 and bracket_depth == 0:
                    comma_count += 1
                elif stripped[j] == ':' and depth == 1 and paren_depth == 0 and bracket_depth == 0:
                    colon_count += 1
                j += 1

            # Properties = top-level commas + 1 (unless empty or trailing comma)
            if comma_count > 0:
                properties = comma_count + (0 if trailing_comma else 1)
            else:
                properties = 0

            # Violation: >4 properties AND at least one top-level colon (real data, not bindings)
            if properties > 4 and colon_count > 0:
                out.append(f"L{line_num}: object literal with >4 keys")

        i += 1

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
