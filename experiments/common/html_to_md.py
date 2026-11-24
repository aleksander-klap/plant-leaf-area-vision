"""Turn the experiments' HTML reports into Markdown, so GitHub shows them.

    python common/html_to_md.py REPORT.html [...]      # writes REPORT.md and REPORT_files/, removes REPORT.html

The reports are written by 00_evaluation/evaluate.py and a few experiment scripts, with a small set of tags:
headings, paragraphs, lists, tables, figures, <details>, and the summary cards. Embedded pictures (data: URLs) are
saved as files next to the report; links to page sections are pointed at GitHub's heading anchors.
"""
import base64
import re
import shutil
import sys
from html.parser import HTMLParser
from pathlib import Path

VOID = {"img", "meta", "br", "hr", "link", "input", "source"}
SKIP = {"head", "style", "script", "title"}
BLOCK = {"p", "div", "nav", "figure", "figcaption", "table", "ul", "ol", "li", "details", "summary",
         "h1", "h2", "h3", "h4", "body", "html", "section"}


class Node:
    def __init__(self, tag, attrs=None, parent=None):
        self.tag, self.attrs, self.parent, self.children = tag, dict(attrs or {}), parent, []

    def cls(self):
        return self.attrs.get("class", "").split()


class Tree(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.root = self.cur = Node("root")

    def handle_starttag(self, tag, attrs):
        n = Node(tag, attrs, self.cur)
        self.cur.children.append(n)
        if tag not in VOID:
            self.cur = n

    def handle_startendtag(self, tag, attrs):
        self.cur.children.append(Node(tag, attrs, self.cur))

    def handle_endtag(self, tag):
        n = self.cur
        while n is not self.root and n.tag != tag:      # tolerate unclosed tags
            n = n.parent
        if n is not self.root:
            self.cur = n.parent

    def handle_data(self, data):
        self.cur.children.append(data)


def text_of(n):
    return "".join(c if isinstance(c, str) else text_of(c) for c in n.children)


SQUARES = {"🟥": (220, 40, 40), "🟧": (255, 140, 0), "🟨": (250, 210, 0), "🟩": (60, 190, 60),
           "🟦": (30, 120, 230), "🟪": (150, 60, 200), "🟫": (130, 80, 40), "⬛": (20, 20, 20), "⬜": (240, 240, 240)}


def swatch(style):
    """A colour square for a legend swatch (<span style='background:rgb(...)'>): the nearest coloured emoji."""
    m = re.search(r"background:\s*rgb\((\d+),\s*(\d+),\s*(\d+)\)", style or "")
    if not m:
        return None
    rgb = tuple(int(v) for v in m.groups())
    return min(SQUARES, key=lambda k: sum((a - b) ** 2 for a, b in zip(SQUARES[k], rgb)))


def slug(title):
    """GitHub's heading anchor."""
    s = re.sub(r"[^\w\- ]", "", title.strip().lower())
    return s.replace(" ", "-")


class Renderer:
    def __init__(self, files_dir, files_rel):
        self.files_dir, self.files_rel = files_dir, files_rel
        self.n_img, self.anchors = 0, {}

    # --- pictures -----------------------------------------------------------------------------------------------
    def image(self, n):
        src, alt = n.attrs.get("src", ""), n.attrs.get("alt", "") or "picture"
        m = re.match(r"data:image/(\w+);base64,(.*)", src, re.S)
        if m:
            ext = {"jpeg": "jpg"}.get(m.group(1), m.group(1))
            self.n_img += 1
            name = f"{self.n_img:02d}_{re.sub(r'[^A-Za-z0-9]+', '_', alt).strip('_')[:40] or 'picture'}.{ext}"
            self.files_dir.mkdir(parents=True, exist_ok=True)
            (self.files_dir / name).write_bytes(base64.b64decode(m.group(2)))
            src = f"{self.files_rel}/{name}"
        return f"![{alt}]({src})"

    # --- inline -------------------------------------------------------------------------------------------------
    def inline(self, n):
        out = []
        for c in n.children:
            if isinstance(c, str):
                out.append(re.sub(r"\s+", " ", c))
                continue
            t = c.tag
            if t in SKIP:
                continue
            if t == "span" and swatch(c.attrs.get("style")):
                out.append(swatch(c.attrs.get("style")) + " ")
            elif t == "br":
                out.append("<br>")
            elif t == "img":
                out.append(self.image(c))
            elif t in ("b", "strong"):
                s = self.inline(c).strip()
                out.append(f"**{s}**" if s else "")
            elif t in ("i", "em"):
                s = self.inline(c).strip()
                out.append(f"*{s}*" if s else "")
            elif t == "code":
                out.append(f"`{text_of(c).strip()}`")
            elif t == "a":
                href = c.attrs.get("href", "")
                if href.startswith("#"):
                    href = "#" + self.anchors.get(href[1:], href[1:])
                s = self.inline(c).strip()
                out.append(f"[{s}]({href})" if href else s)
            elif t in ("ul", "ol", "table"):
                out.append(" " + self.block(c).strip().replace("\n", " ") + " ")
            else:
                out.append(self.inline(c))
        return "".join(out)

    # --- blocks -------------------------------------------------------------------------------------------------
    def table(self, n):
        rows = []

        def walk(x):
            for c in x.children:
                if isinstance(c, str):
                    continue
                if c.tag == "tr":
                    cells = [(d.tag, self.inline(d).strip().replace("|", "\\|") or " ")
                             for d in c.children if not isinstance(d, str) and d.tag in ("td", "th")]
                    rows.append(cells)
                else:
                    walk(c)
        walk(n)
        if not rows:
            return ""
        width = max(len(r) for r in rows)
        rows = [[t for _, t in r] + [" "] * (width - len(r)) for r in rows]
        lines = ["| " + " | ".join(rows[0]) + " |", "|" + "---|" * width]
        lines += ["| " + " | ".join(r) + " |" for r in rows[1:]]
        return "\n\n" + "\n".join(lines) + "\n\n"

    def lst(self, n, ordered):
        items, k = [], 0
        for c in n.children:
            if isinstance(c, str) or c.tag != "li":
                continue
            k += 1
            body = self.block_children(c).strip()
            body = re.sub(r"\n{2,}", "\n", body)
            mark = f"{k}. " if ordered else "- "
            items.append(mark + body.replace("\n", "\n" + " " * len(mark)))
        return "\n\n" + "\n".join(items) + "\n\n"

    def block_children(self, n):
        out, run = [], []

        def flush():
            s = "".join(run).strip()
            if s:
                out.append(s)
            run.clear()
        for c in n.children:
            if isinstance(c, str) or c.tag not in BLOCK:
                run.append(self.inline(_wrap(c, n)))
            else:
                flush()
                out.append(self.block(c))
        flush()
        return "\n\n".join(o.strip("\n") for o in out if o.strip())

    def block(self, n):
        t = n.tag
        if t in SKIP:
            return ""
        if t in ("h1", "h2", "h3", "h4"):
            return "\n\n" + "#" * int(t[1]) + " " + self.inline(n).strip() + "\n\n"
        if t == "p":
            return "\n\n" + self.inline(n).strip() + "\n\n"
        if t == "table":
            return self.table(n)
        if t in ("ul", "ol"):
            return self.lst(n, t == "ol")
        if t == "figure":
            return "\n\n" + self.block_children(n) + "\n\n"
        if t == "figcaption":
            return "\n\n*" + self.inline(n).strip() + "*\n\n"
        if t == "details":
            summ = next((c for c in n.children if not isinstance(c, str) and c.tag == "summary"), None)
            rest = Node("div", parent=n)
            rest.children = [c for c in n.children if c is not summ]
            head = self.inline(summ).strip() if summ else "Details"
            return f"\n\n<details><summary>{head}</summary>\n\n{self.block_children(rest)}\n\n</details>\n\n"
        if "cards" in n.cls():
            items = []
            for c in n.children:
                if isinstance(c, str) or "card" not in c.cls():
                    continue
                parts = [x for x in c.children if not isinstance(x, str)]
                v = next((self.inline(x).strip() for x in parts if "v" in x.cls()), "")
                lab = next((self.inline(x).strip() for x in parts if "l" in x.cls()), "")
                items.append(f"- **{v}** {lab}")
            return "\n\n" + "\n".join(items) + "\n\n"
        return "\n\n" + self.block_children(n) + "\n\n"


def _wrap(c, parent):
    """A single inline child (text or tag) as a node, so inline() can render it."""
    w = Node("span", parent=parent)
    w.children = [c]
    return w


def convert(path):
    path = Path(path)
    tree = Tree()
    tree.feed(path.read_text(encoding="utf-8"))
    files_dir = path.with_name(path.stem + "_files")
    shutil.rmtree(files_dir, ignore_errors=True)            # no pictures left over from an earlier version
    r = Renderer(files_dir, files_dir.name)

    def collect(n):        # id -> GitHub anchor of the heading with that id
        for c in n.children:
            if isinstance(c, str):
                continue
            if c.tag in ("h1", "h2", "h3", "h4") and "id" in c.attrs:
                r.anchors[c.attrs["id"]] = slug(text_of(c))
            collect(c)
    collect(tree.root)
    body = next((c for c in _all(tree.root) if c.tag == "body"), tree.root)
    md = r.block_children(body)
    md = re.sub(r"[ \t]+\n", "\n", md)
    md = re.sub(r"\n{3,}", "\n\n", md).strip() + "\n"
    out = path.with_suffix(".md")
    out.write_text(md, encoding="utf-8")
    return out


def save(page, md_path):
    """Write an HTML page as Markdown: md_path, and its pictures in <name>_files/."""
    tmp = Path(md_path).with_suffix(".html")
    tmp.write_text(page, encoding="utf-8")
    out = convert(tmp)
    tmp.unlink()
    return out


def _all(n):
    for c in n.children:
        if not isinstance(c, str):
            yield c
            yield from _all(c)


if __name__ == "__main__":
    for a in sys.argv[1:]:
        print(convert(a))
        Path(a).unlink()
