"""A rendered report as a small tree, so a test reads what a reader would: the text of the element with a given
role, not the presence of a class name in the source."""
from __future__ import annotations

from html.parser import HTMLParser

VOID = frozenset({"meta", "col", "br", "hr", "img", "input", "link"})
SKIP = frozenset({"style", "script"})
INLINE = frozenset({"a", "span", "strong", "b", "em", "small", "code"})  # no break in the text around these


class Node:
    def __init__(self, tag: str, attrs: dict[str, str]) -> None:
        self.tag, self.attrs, self.children = tag, attrs, []

    def walk(self):
        for c in self.children:
            if isinstance(c, Node):
                yield c
                yield from c.walk()

    def text(self) -> str:
        """The element's text as one line (runs of whitespace are one space)."""
        def parts(n):
            for c in n.children:
                if isinstance(c, Node):
                    if c.tag in INLINE:
                        yield from parts(c)
                    elif c.tag not in SKIP:
                        yield " "
                        yield from parts(c)
                        yield " "
                else:
                    yield c
        return " ".join("".join(parts(self)).split())

    def find(self, tag: str) -> list[Node]:
        return [n for n in self.walk() if n.tag == tag]

    def find_attr(self, name: str, value: str) -> list[Node]:
        """Elements whose attribute holds the value (for class: as one of its words)."""
        return [n for n in self.walk() if value in (n.attrs.get(name, "").split() if name == "class"
                                                    else [n.attrs.get(name)])]

    def one(self, name: str, value: str) -> Node:
        found = self.find_attr(name, value)
        assert len(found) == 1, f"{len(found)} elements with {name}={value!r}"
        return found[0]

    def text_of(self, name: str, value: str) -> str:
        return self.one(name, value).text()


class _Builder(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.root = Node("#root", {})
        self.stack = [self.root]

    def handle_starttag(self, tag, attrs):
        node = Node(tag, {k: v or "" for k, v in attrs})
        self.stack[-1].children.append(node)
        if tag not in VOID:
            self.stack.append(node)

    def handle_endtag(self, tag):
        for i in range(len(self.stack) - 1, 0, -1):
            if self.stack[i].tag == tag:
                del self.stack[i:]
                return

    def handle_data(self, data):
        self.stack[-1].children.append(data)


def dom(html: str) -> Node:
    b = _Builder()
    b.feed(html)
    return b.root
