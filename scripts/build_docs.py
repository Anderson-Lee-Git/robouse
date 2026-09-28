#!/usr/bin/env python3
"""Build the static Robo Use docs site (robouse.ai/docs/) from docs/.

    python scripts/build_docs.py --out ~/benchflow/roboharm/site/docs
    python scripts/build_docs.py --out /tmp/docs --base /docs/     # --base is the URL prefix the pages are served under

Standard library only (Python 3.11+): it has its own small markdown converter that covers what these docs use
(headings, paragraphs, nested lists, fenced code, tables, block quotes, links, images, emphasis, inline code).

Output: one page per doc at <out>/<slug>/index.html (pretty URLs), plus docs.css and docs.js. Every page uses the
site's shared header and footer from the site repository's tools/chrome.py (found next to --out, or --chrome) and
expects /theme.js, /surface.css, /bridge.css, /chrome.css, /prose.css (the site's one type system) and /fonts/ at the site root.

Only the pages in PAGES are published. Links between them are rewritten to the generated pages (anchors kept);
links to repository files that are not published become plain text or inline code, since the repository is
private; site links starting with "/" are kept. The build fails if a link between pages is broken, or if the
output contains a banned word or anything that looks like a credential (see check_output).

Sources are read from git HEAD by default (--ref REV for another revision, --worktree for uncommitted edits), so
the site matches the repository.
"""

from __future__ import annotations

import argparse
import codecs
import importlib.util
import html
import posixpath
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
GITHUB = "https://github.com/benchflow-ai/robouse"
# Absolute links to docs in the repository (README uses them so they work on PyPI) map to the generated pages.
GITHUB_DOC_RE = re.compile(re.escape(GITHUB) + r"/(?:blob|tree)/main/((?:docs/|README\.md).*)$")
MARKER = ".build_docs"  # written into --out so a rebuild only ever clears a directory this script owns

class Source:
    """Reads docs from a git revision (default HEAD, so the site matches the repository) or the working tree."""

    def __init__(self, ref: str | None):
        self.ref = ref
        if ref:
            out = subprocess.run(["git", "-C", str(REPO), "ls-tree", "-r", "--name-only", ref], check=True,
                                 capture_output=True, text=True).stdout
            self.paths = set(out.splitlines())
        else:
            self.paths = {str(f.relative_to(REPO)) for f in REPO.rglob("*") if f.is_file() and ".git" not in f.parts}

    def exists(self, path: str) -> bool:
        return path in self.paths

    def list(self, folder: str, suffix: str) -> list[str]:
        return sorted(q for q in self.paths if posixpath.dirname(q) == folder.rstrip("/") and q.endswith(suffix))

    def read_bytes(self, path: str) -> bytes:
        if self.ref:
            return subprocess.run(["git", "-C", str(REPO), "show", f"{self.ref}:{path}"], check=True,
                                  capture_output=True).stdout
        return (REPO / path).read_bytes()

    def read(self, path: str) -> str:
        return self.read_bytes(path).decode("utf-8")


# (group, source path relative to the repo, slug, nav label). Order = sidebar order = prev/next order.
PAGES: list[tuple[str, str, str, str]] = [
    ("Get started", "docs/index.md", "", "Overview"),
    ("Get started", "docs/quickstart.md", "quickstart", "Quickstart"),
    ("Get started", "docs/supported.md", "supported", "Supported"),
    ("Concepts", "docs/tasks.md", "tasks", "Tasks and scoring"),
    ("Concepts", "docs/episodes.md", "episodes", "Episodes and robo"),
    ("Concepts", "docs/harnesses.md", "harnesses", "Harnesses"),
    ("Guides", "docs/run-an-agent.md", "run-an-agent", "Run an agent"),
    ("Guides", "docs/write-a-task.md", "write-a-task", "Write a task"),
    ("Guides", "docs/run-a-suite.md", "run-a-suite", "Run a suite"),
    ("Guides", "docs/datasets.md", "datasets", "Datasets"),
    ("Reference", "docs/cli.md", "cli", "robouse CLI"),
    ("Reference", "docs/robo-cli.md", "robo-cli", "robo CLI"),
    ("Reference", "docs/task-format.md", "task-format", "task.md"),
    ("Reference", "docs/suites.md", "suites", "Suites"),
]
# Extra sidebar links to other parts of the site: (group, label, url).
SIDEBAR_LINKS = [("Results", "Runs and videos", "/runs/")]
# Docs kept in the repository but not published: internal notes, run logs and machine-specific setup.
EXCLUDED = {
    "docs/review-log.md": "internal log of documentation review passes",
    "docs/research/": "internal literature and dataset surveys",
    "docs/dogfood.md": "log of the commands run to check the public docs",
    "docs/results.md": "generated table for the repository; the public results are robouse.ai/runs/",
    "docs/audit.md": "the maintainers' audit script over local runs",
    "docs/viewer.md": "the maintainers' viewer setup and viewer formats",
    "docs/benchflow.md": "validation log of the BenchFlow export; the public part is in run-a-suite.md",
    "docs/molmoact2.md": "GPU server setup notes; the public part is in harnesses.md",
    "docs/suites/": "per-suite design notes; the public part is the table in suites.md",
}
# Build-time guard: none of these may appear in the output. Stored rot13-encoded so the word itself never
# appears in the repository either.
BANNED_WORDS = [codecs.decode(w, "rot13") for w in ["uneobe"]]
SECRET_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{16,}", r"sk-ant-[A-Za-z0-9_-]+", r"pypi-[A-Za-z0-9_-]{16,}", r"npm_[A-Za-z0-9]{20,}",
    r"gh[pousr]_[A-Za-z0-9]{20,}", r"github_pat_[A-Za-z0-9_]{20,}", r"hf_[A-Za-z0-9]{20,}", r"AKIA[0-9A-Z]{16}",
    r"(?i)(?:api[_-]?key|token|secret|password)\s*[=:]\s*['\"]?[A-Za-z0-9_\-]{16,}",
    r"(?i)bearer\s+[A-Za-z0-9._\-]{20,}",
]


# ---------------------------------------------------------------------------------------------------------------
# markdown -> html


def slugify(text: str, seen: dict[str, int]) -> str:
    """GitHub-style heading id: lowercase, drop punctuation, spaces to hyphens, -1/-2 for duplicates."""
    s = re.sub(r"[^\w\- ]", "", text.strip().lower()).replace(" ", "-")
    n = seen.get(s, 0)
    seen[s] = n + 1
    return s if n == 0 else f"{s}-{n}"


def plain(md: str) -> str:
    """Rough markdown -> plain text, for heading ids, titles and descriptions."""
    s = re.sub(r"!\[([^\]]*)\]\([^)]*\)", r"\1", md)
    s = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", s)
    s = re.sub(r"`+([^`]*)`+", r"\1", s)
    s = re.sub(r"(\*\*|__)(.+?)\1", r"\2", s)
    s = re.sub(r"(?<!\w)[*_](.+?)[*_](?!\w)", r"\1", s)
    return s.strip()


class Converter:
    """Converts one markdown document. `link` maps (href) -> (url or None); None means 'not published'."""

    def __init__(self, link, labels=None, svg=None):
        self.link = link
        self.svg = svg  # href -> inline SVG markup (or None), for figures that follow the page's theme
        self.labels = labels or {}  # page url -> nav label, for links whose text is just the file path
        self.seen: dict[str, int] = {}
        self.headings: list[tuple[int, str, str]] = []

    # ---- inline

    def inline(self, text: str) -> str:
        slots: list[str] = []

        def keep(h: str) -> str:
            slots.append(h)
            return f"\x00{len(slots) - 1}\x00"

        # code spans (any run of backticks), then <autolinks>
        text = re.sub(r"(`+)(.+?)\1", lambda m: keep(f"<code>{html.escape(m.group(2).strip() if m.group(1) != '`' else m.group(2), quote=False)}</code>"), text)
        text = re.sub(r"<(https?://[^>\s]+)>", lambda m: keep(self._a(m.group(1), html.escape(m.group(1)))), text)
        text = html.escape(text, quote=False)
        text = re.sub(r"!\[([^\]]*)\]\(([^)\s]+)\)", lambda m: keep(self._img(m.group(2), m.group(1))), text)
        text = re.sub(r'\[((?:[^\[\]]|\[[^\]]*\])*)\]\(([^)\s]+)(?:\s+"[^)]*")?\)',
                      lambda m: keep(self._link(m.group(2), self.emph(m.group(1)))), text)
        text = re.sub(r"(?<![\w/\"'=])(https?://[^\s<>()\]]*[^\s<>()\].,;:!?'\"])",
                      lambda m: keep(self._a(m.group(1), m.group(1))), text)
        text = self.emph(text)
        text = re.sub(r"  $", "<br>", text)
        while "\x00" in text:
            text = re.sub(r"\x00(\d+)\x00", lambda m: slots[int(m.group(1))], text)
        return text

    @staticmethod
    def emph(s: str) -> str:
        s = re.sub(r"\*\*(?=\S)(.+?)(?<=\S)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"(?<![\w*])\*(?=\S)(.+?)(?<=\S)\*(?![\w*])", r"<em>\1</em>", s)
        s = re.sub(r"(?<![\w_])_(?=\S)(.+?)(?<=\S)_(?![\w_])", r"<em>\1</em>", s)
        return s

    @staticmethod
    def _a(href: str, inner: str) -> str:
        return f'<a href="{html.escape(href)}">{inner}</a>'

    def _link(self, href: str, inner: str) -> str:
        href = html.unescape(href)
        if re.match(r"^(https?:|mailto:)", href) and not GITHUB_DOC_RE.match(href):
            return self._a(href, inner)
        url = self.link(href)
        if url:
            text = html.unescape(re.sub(r"<[^>]+>", "", inner))
            if "\x00" not in inner and re.fullmatch(r"[\w./\-]+\.md(#[\w\-]*)?|(docs/)?suites/", text):
                inner = html.escape(self.labels.get(url.split("#")[0], text), quote=False)
            return self._a(url, inner)
        # not published: keep the words; a bare path becomes inline code
        text = re.sub(r"<[^>]+>", "", inner)
        if "\x00" in inner or "<code>" in inner or not re.fullmatch(r"[\w./#\-]+", html.unescape(text)):
            return inner
        return f"<code>{inner}</code>"

    def _img(self, src: str, alt: str) -> str:
        src = html.unescape(src)
        url = src if re.match(r"^https?:", src) else self.link(src)
        if not url:
            return alt
        return f'<img src="{html.escape(url)}" alt="{alt}" loading="lazy">'

    # ---- blocks

    LIST_RE = re.compile(r"^( *)([-*+]|\d{1,9}[.)])( +|$)")
    FENCE_RE = re.compile(r"^( *)(`{3,}|~{3,})\s*([\w+-]*)")
    HEAD_RE = re.compile(r"^(#{1,6})\s+(.*?)\s*#*\s*$")
    SEP_RE = re.compile(r"^\s*\|?\s*:?-{2,}:?\s*(\|\s*:?-{2,}:?\s*)*\|?\s*$")

    def starts_block(self, line: str, lines: list[str], i: int) -> bool:
        return bool(self.FENCE_RE.match(line) or self.HEAD_RE.match(line) or line.startswith(">")
                    or self.LIST_RE.match(line) or re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line)
                    or (line.lstrip().startswith("|") and i + 1 < len(lines) and self.SEP_RE.match(lines[i + 1])))

    def blocks(self, lines: list[str]) -> str:
        out: list[str] = []
        i, n = 0, len(lines)
        while i < n:
            line = lines[i]
            if not line.strip():
                i += 1
                continue
            m = self.FENCE_RE.match(line)
            if m:
                ind, fence, lang = len(m.group(1)), m.group(2), m.group(3)
                body, i = [], i + 1
                while i < n and not (lines[i].strip().startswith(fence[0] * len(fence)) and not lines[i].strip().strip(fence[0])):
                    body.append(lines[i][ind:] if lines[i][:ind].strip() == "" else lines[i])
                    i += 1
                i += 1
                if lang == "gallery":  # one "image | caption" per line: a strip of small figures
                    items = []
                    for row in body:
                        if "|" not in row:
                            continue
                        src, cap = (s.strip() for s in row.split("|", 1))
                        items.append(f"<figure>{self._img(src, plain(cap))}<figcaption>{self.inline(cap)}</figcaption></figure>")
                    out.append('<div class="gallery">' + "".join(items) + "</div>")
                    continue
                cls = f' class="language-{lang}"' if lang else ""
                out.append(f'<div class="code"><pre><code{cls}>{html.escape(chr(10).join(body), quote=False)}</code></pre></div>')
                continue
            m = self.HEAD_RE.match(line)
            if m:
                level, text = len(m.group(1)), m.group(2)
                hid = slugify(plain(text), self.seen)
                self.headings.append((level, hid, text))
                inner = self.inline(text)
                if level == 1:
                    out.append(f"<h1 id=\"{hid}\">{inner}</h1>")
                else:
                    out.append(f'<h{level} id="{hid}">{inner}<a class="hash" href="#{hid}" aria-label="Link to this section">#</a></h{level}>')
                i += 1
                continue
            if re.match(r"^\s*(-{3,}|\*{3,}|_{3,})\s*$", line):
                out.append("<hr>")
                i += 1
                continue
            if line.lstrip().startswith("|") and i + 1 < n and self.SEP_RE.match(lines[i + 1]):
                rows = [line]
                sep = lines[i + 1]
                i += 2
                while i < n and lines[i].lstrip().startswith("|"):
                    rows.append(lines[i])
                    i += 1
                out.append(self.table(rows[0], sep, rows[1:]))
                continue
            if line.startswith(">"):
                body = []
                while i < n and lines[i].strip() and lines[i].startswith(">"):
                    body.append(re.sub(r"^> ?", "", lines[i]))
                    i += 1
                out.append(f"<blockquote>{self.blocks(body)}</blockquote>")
                continue
            if self.LIST_RE.match(line):
                i = self.list_block(lines, i, out)
                continue
            fm = re.fullmatch(r"!\[([^\]]+)\]\(([^)\s]+)\)", line.strip())
            if fm and (i + 1 >= n or not lines[i + 1].strip()):  # an image alone in its paragraph: a figure
                cap, src = fm.group(1), fm.group(2)
                svg = self.svg(src) if self.svg and src.endswith(".svg") else None
                body = svg.replace("<svg ", f'<svg role="img" aria-label="{html.escape(plain(cap))}" ', 1) if svg else self._img(src, html.escape(plain(cap)))
                out.append(f'<figure class="figure">{body}<figcaption>{self.inline(cap)}</figcaption></figure>')
                i += 1
                continue
            para = [line.strip()]
            i += 1
            while i < n and lines[i].strip() and not self.starts_block(lines[i], lines, i):
                para.append(lines[i].strip())
                i += 1
            out.append(f"<p>{self.inline(chr(10).join(para))}</p>")
        return "\n".join(out)

    def list_block(self, lines: list[str], i: int, out: list[str]) -> int:
        n = len(lines)
        m = self.LIST_RE.match(lines[i])
        base = len(m.group(1))
        ordered = m.group(2)[0].isdigit()
        start = int(m.group(2)[:-1]) if ordered else 1
        items: list[list[str]] = []
        loose = False
        while i < n:
            m = self.LIST_RE.match(lines[i])
            if not m or len(m.group(1)) != base or m.group(2)[0].isdigit() != ordered:
                break
            content_ind = len(m.group(0)) if m.group(3) else len(m.group(0)) + 1
            item = [lines[i][len(m.group(0)):]]
            i += 1
            while i < n:
                ln = lines[i]
                if not ln.strip():
                    # blank: the item continues only if the next non-blank line is indented under it
                    j = i
                    while j < n and not lines[j].strip():
                        j += 1
                    if j < n and len(lines[j]) - len(lines[j].lstrip()) > base and not (
                            self.LIST_RE.match(lines[j]) and len(self.LIST_RE.match(lines[j]).group(1)) == base):
                        item.extend([""] * (j - i))
                        i = j
                        loose = loose or not self.LIST_RE.match(lines[j])
                        continue
                    break
                indent = len(ln) - len(ln.lstrip())
                lm = self.LIST_RE.match(ln)
                if indent > base:
                    item.append(ln[min(indent, content_ind):])
                elif lm or self.starts_block(ln, lines, i):
                    break
                else:
                    item.append(ln.strip())  # lazy continuation of the item's paragraph
                i += 1
            items.append(item)
            # blank lines between items make the list loose
            j = i
            while j < n and not lines[j].strip():
                j += 1
            nm = self.LIST_RE.match(lines[j]) if j < n else None
            if j > i and nm and len(nm.group(1)) == base and nm.group(2)[0].isdigit() == ordered:
                loose = True
                i = j
        tag = "ol" if ordered else "ul"
        attr = f' start="{start}"' if ordered and start != 1 else ""
        lis = []
        for item in items:
            body = self.blocks(item)
            if not loose:
                body = re.sub(r"^<p>(.*?)</p>", r"\1", body, count=1, flags=re.S)
            lis.append(f"<li>{body}</li>")
        out.append(f"<{tag}{attr}>\n" + "\n".join(lis) + f"\n</{tag}>")
        return i

    def table(self, head: str, sep: str, rows: list[str]) -> str:
        def cells(row: str) -> list[str]:
            row = row.strip()
            row = row[1:] if row.startswith("|") else row
            row = row[:-1] if row.endswith("|") and not row.endswith("\\|") else row
            parts, cur, in_code = [], "", False
            k = 0
            while k < len(row):
                c = row[k]
                if c == "\\" and k + 1 < len(row) and row[k + 1] == "|":
                    cur += "|"
                    k += 2
                    continue
                if c == "`":
                    in_code = not in_code
                if c == "|" and not in_code:
                    parts.append(cur)
                    cur = ""
                else:
                    cur += c
                k += 1
            parts.append(cur)
            return [p.strip() for p in parts]

        aligns = []
        for s in cells(sep):
            aligns.append("center" if s.startswith(":") and s.endswith(":") else "right" if s.endswith(":") else "left" if s.startswith(":") else "")
        def row_html(r: list[str], tag: str) -> str:
            tds = []
            for k, c in enumerate(r):
                a = aligns[k] if k < len(aligns) and aligns[k] else ""
                style = f' style="text-align:{a}"' if a else ""
                tds.append(f"<{tag}{style}>{self.inline(c)}</{tag}>")
            return "<tr>" + "".join(tds) + "</tr>"
        body = "\n".join(row_html(cells(r), "td") for r in rows)
        return (f'<div class="table"><table>\n<thead>{row_html(cells(head), "th")}</thead>\n'
                f"<tbody>\n{body}\n</tbody>\n</table></div>")


# ---------------------------------------------------------------------------------------------------------------
# site


@dataclass
class Page:
    group: str
    src: str
    slug: str
    label: str
    title: str = ""
    body: str = ""
    description: str = ""
    toc: list = field(default_factory=list)
    ids: set = field(default_factory=set)


def page_url(base: str, slug: str) -> str:
    return base + (slug + "/" if slug else "")


def load_chrome(path: Path):
    """The site's shared header and footer (tools/chrome.py in the site repository)."""
    if not path.exists():
        sys.exit(f"shared chrome not found: {path} (pass --chrome /path/to/tools/chrome.py)")
    spec = importlib.util.spec_from_file_location("site_chrome", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def page_list(source: Source) -> list[Page]:
    pages = []
    for p in PAGES:
        if not source.exists(p[1]):
            sys.exit(f"{p[1]} is listed in PAGES but not in {source.ref or 'the working tree'}")
        pages.append(Page(*p))
    listed = {p.src for p in pages}
    for src in source.list("docs", ".md"):
        if src not in listed and src not in EXCLUDED:
            print(f"note: {src} is neither in PAGES nor in EXCLUDED; not published", file=sys.stderr)
    return pages


def build(out: Path, base: str, source: Source, chrome) -> list[Path]:
    pages = page_list(source)
    by_src = {p.src: p for p in pages}
    copies: dict[str, str] = {}  # repo path -> output-relative path (images)
    broken: list[str] = []

    for p in pages:
        src_dir = posixpath.dirname(p.src)

        def link(href: str, src_dir=src_dir, p=p) -> str | None:
            if href.startswith("/"):
                return href  # another part of the site (/runs/, ...)
            gh = GITHUB_DOC_RE.match(href)
            path, _, anchor = (gh.group(1) if gh else href).partition("#")
            if not path:
                return "#" + anchor if anchor else None
            target = posixpath.normpath(path if gh else posixpath.join(src_dir, path))
            frag = "#" + anchor if anchor else ""
            if target in by_src:
                return page_url(base, by_src[target].slug) + frag
            if re.search(r"\.(png|jpe?g|gif|svg|webp)$", target, re.I) and target.startswith("docs/") and source.exists(target):
                rel = target[len("docs/"):]
                copies[target] = rel
                return base + rel
            if target.endswith(".md") and target.startswith("docs/"):
                broken.append(f"{p.src}: link to unpublished page {href}")
            return href if gh else None  # other GitHub links stay as they are

        md = source.read(p.src)
        md = re.sub(r"/Users/(?!<)[^/\s`]+/", "~/", md)  # tidy absolute home paths
        def svg(href: str, src_dir=src_dir) -> str | None:
            target = posixpath.normpath(posixpath.join(src_dir, href))
            if not (target.startswith("docs/") and source.exists(target)):
                broken.append(f"{p.src}: missing figure {href}")
                return None
            s = source.read(target)
            s = re.sub(r"<\?xml[^>]*>\s*|<!--.*?-->", "", s, flags=re.S).strip()
            uid = posixpath.splitext(posixpath.basename(target))[0]
            return re.sub(r'id="ah-([\w-]+)"', lambda m: f'id="{uid}-{m.group(1)}"', s).replace("url(#ah-", f"url(#{uid}-")

        conv = Converter(link, {page_url(base, q.slug): q.label for q in pages}, svg)
        p.body = conv.blocks(md.splitlines())
        p.toc = [(hid, plain(text)) for lvl, hid, text in conv.headings if lvl == 2]
        p.ids = {hid for _, hid, _ in conv.headings}
        h1 = next((t for lvl, _, t in conv.headings if lvl == 1), p.label)
        p.title = plain(h1)
        paras = [b for b in re.split(r"\n\s*\n", md) if b.strip() and not b.lstrip().startswith(("#", "`", "|", "-", "!", ">"))]
        desc = re.sub(r"\s+", " ", plain(paras[0])) if paras else p.title
        p.description = desc if len(desc) <= 180 else desc[:177].rsplit(" ", 1)[0] + "..."

    # every in-docs link must hit a page, and every #anchor a heading on it
    by_url = {page_url(base, q.slug): q for q in pages}
    for p in pages:
        for href in re.findall(r'href="([^"]+)"', p.body):
            href = html.unescape(href)
            if href.startswith("#"):
                if href[1:] not in p.ids:
                    broken.append(f"{p.src}: missing anchor {href}")
            elif href.startswith(base):
                path, _, anchor = href.partition("#")
                q = by_url.get(path)
                if q is None and not re.search(r"\.(png|jpe?g|gif|svg|webp)$", path):
                    broken.append(f"{p.src}: link to missing page {href}")
                elif q is not None and anchor and anchor not in q.ids:
                    broken.append(f"{p.src}: missing anchor {href}")
    if broken:
        sys.exit("broken links:\n  " + "\n  ".join(broken))

    # write
    if out.exists():
        if any(out.iterdir()) and not (out / MARKER).exists():
            sys.exit(f"refusing to clear {out}: not empty and not created by build_docs.py (no {MARKER})")
        shutil.rmtree(out)
    out.mkdir(parents=True)
    (out / MARKER).write_text("generated by robouse/scripts/build_docs.py; the whole directory is replaced on rebuild\n")
    (out / "docs.css").write_text(CSS, encoding="utf-8")
    (out / "docs.js").write_text(JS, encoding="utf-8")
    for src, rel in copies.items():
        dst = out / rel
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_bytes(source.read_bytes(src))
    written = []
    for k, p in enumerate(pages):
        prev_p = pages[k - 1] if k > 0 else None
        next_p = pages[k + 1] if k + 1 < len(pages) else None
        dst = out / p.slug / "index.html" if p.slug else out / "index.html"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(render(p, pages, base, prev_p, next_p, chrome), encoding="utf-8")
        written.append(dst)
    return written


def render(p: Page, pages: list[Page], base: str, prev_p: Page | None, next_p: Page | None, chrome) -> str:
    e = html.escape
    nav, group = [], None
    for q in pages:
        if q.group != group:
            if group is not None:
                nav.append("</ul>")
            group = q.group
            nav.append(f'<p class="grp">{e(group)}</p><ul>')
        cur = ' aria-current="page"' if q is p else ""
        nav.append(f'<li><a href="{page_url(base, q.slug)}"{cur}>{e(q.label)}</a></li>')
    nav.append("</ul>")
    for grp, label, url in SIDEBAR_LINKS:
        nav.append(f'<p class="grp">{e(grp)}</p><ul><li><a href="{e(url)}">{e(label)}</a></li></ul>')
    toc = ""
    if len(p.toc) >= 2:
        items = "".join(f'<li><a href="#{e(hid)}">{e(text)}</a></li>' for hid, text in p.toc)
        toc = f'<aside class="toc"><nav aria-label="On this page"><p class="grp">On this page</p><ul>{items}</ul></nav></aside>'
    pager = []
    if prev_p:
        pager.append(f'<a class="prev" href="{page_url(base, prev_p.slug)}"><span>Previous</span>{e(prev_p.label)}</a>')
    if next_p:
        pager.append(f'<a class="next" href="{page_url(base, next_p.slug)}"><span>Next</span>{e(next_p.label)}</a>')
    title = "Robo Use docs" if not p.slug else f"{p.title} · Robo Use docs"
    canonical = "https://robouse.ai" + page_url(base, p.slug)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>{e(title)}</title>
<meta name="description" content="{e(p.description)}">
<link rel="canonical" href="{canonical}">
<meta property="og:type" content="article">
<meta property="og:site_name" content="Robo Use">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(p.description)}">
<meta property="og:url" content="{canonical}">
<link rel="icon" href="/favicon.png">
<script src="/theme.js"></script>
{chrome.LINK}
<link rel="stylesheet" href="{base}docs.css">
{getattr(chrome, "BRIDGE", '<link rel="stylesheet" href="/surface.css">')}
<script src="{base}docs.js" defer></script>
</head>
<body>
{chrome.header("/docs/")}
<div class="shell{'' if toc else ' no-toc'}">
<input type="checkbox" id="navtoggle" class="navtoggle" hidden>
<label for="navtoggle" class="navbtn">Menu<span class="cur">{e(p.label)}</span></label>
<aside class="side"><nav aria-label="Docs">
{chr(10).join(nav)}
</nav></aside>
<main class="doc">
<article class="prose">
{title_block(p.body)}
</article>
<nav class="pager">{"".join(pager)}</nav>
</main>
{toc}
</div>
{chrome.FOOTER}
</body>
</html>
"""


def title_block(body: str) -> str:
    """The page's h1 and its first paragraph as the site's shared title block (<header class="page-head">, .lede)."""
    m = re.match(r"\s*(<h1\b[^>]*>.*?</h1>)\s*(?:<p>(.*?)</p>)?", body, re.S)
    if not m:
        return body
    lede = f'<p class="lede">{m.group(2)}</p>' if m.group(2) is not None else ""
    return f'<header class="page-head">{m.group(1)}{lede}</header>\n' + body[m.end():]


def check_output(out: Path) -> list[str]:
    problems = []
    for f in sorted(out.rglob("*")):
        if not f.is_file() or f.suffix not in {".html", ".css", ".js"}:
            continue
        text = f.read_text(encoding="utf-8")
        for w in BANNED_WORDS:
            if w in text.lower():
                problems.append(f"{f.relative_to(out)}: banned word (see BANNED_WORDS)")
        for pat in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                problems.append(f"{f.relative_to(out)}: looks like a credential: {m.group(0)[:24]}...")
    return problems


CSS = r"""/* Robo Use docs. Generated by robouse/scripts/build_docs.py; edit the script, not this file.
   Palette and all type (headings, body text, links, code blocks and the copy button, tables, lists, quotes, captions,
   the title block) come from the site's /prose.css, shared by every robouse.ai page; this file is the docs layout only:
   sidebar, page, on-this-page, pager, figures. Header and footer: /chrome.css. Page surface: /surface.css. */
html { scroll-padding-top: 20px; }

/* layout: sidebar, page, on-this-page, on the site's 1120px grid with 24px gutters */
.shell { display: grid; grid-template-columns: 210px minmax(0, 1fr) 190px; gap: 0 48px; max-width: var(--wide); margin: 0 auto; padding: 72px var(--gutter) 0; }
.shell.no-toc { grid-template-columns: 210px minmax(0, 1fr); }
.side, .toc { position: sticky; top: 24px; align-self: start; max-height: calc(100vh - 48px); overflow-y: auto; font: 400 var(--fs-small)/1.45 var(--sans); }
.grp { margin: 28px 0 6px; font: 600 var(--fs-small)/1.4 var(--sans); color: var(--ink); }
.side .grp:first-child, .toc .grp { margin-top: 4px; }
.side ul, .toc ul { list-style: none; margin: 0; padding: 0; }
.side a, .toc a, .pager a, .hash { text-decoration: none; }
.side li a { display: block; padding: 3px 0; color: var(--muted); }
.side li a:hover { color: var(--ink); }
.side li a[aria-current="page"] { color: var(--ink); font-weight: 500; }
.toc li a { display: block; padding: 3px 0 3px 12px; border-left: 1px solid var(--line); color: var(--muted); line-height: 1.4; }
.toc li a:hover { color: var(--ink); }
.toc li a.on { color: var(--ink); border-left-color: var(--ink); }
.navbtn { display: none; }
.doc { min-width: 0; max-width: var(--measure); padding-bottom: 24px; }

/* headings get a hover anchor */
.hash { margin-left: 8px; color: var(--faint); opacity: 0; font: 400 .7em var(--sans); }
h2:hover .hash, h3:hover .hash, .hash:focus { opacity: 1; }
article img { display: block; max-width: 100%; height: auto; margin: 8px 0; border-radius: 6px; border: 1px solid var(--line); }

/* figures: inline SVG diagrams take the page's colours and type; stills are small webp images */
.figure { margin: 22px 0 26px; overflow-x: auto; -webkit-overflow-scrolling: touch; }
.figure > svg { display: block; width: 100%; min-width: 500px; height: auto; overflow: visible; }  /* small screens scroll rather than shrink the type */
.figure img { margin: 0; }
.fig { color: var(--ink); }
.fig text { font-family: var(--sans); font-size: 13px; fill: var(--ink2); }
.fig .t { font-family: var(--serif); font-size: 17px; fill: var(--ink); }
.fig .s { fill: var(--ink2); }
.fig .k { font-size: 12px; fill: var(--muted); }
.fig .c { font-size: 12px; fill: var(--muted); text-anchor: middle; }
.fig .end { text-anchor: end; }
.fig .m, .fig tspan.m { font-family: var(--mono); font-size: 12px; fill: var(--ink); white-space: pre; }
.fig .m.o { fill: var(--muted); font-size: 11.5px; }
.fig .m.b { font-weight: 500; }
.fig .box { fill: var(--paper); stroke: var(--line-strong); stroke-width: 1; }
.fig .box.trusted { stroke: var(--ink); }
.fig .box2 { fill: var(--panel); stroke: var(--line); stroke-width: 1; }
.fig .ln { stroke: var(--ink2); stroke-width: 1.3; fill: none; }
.fig .ln.thin { stroke: var(--muted); stroke-width: 1; }
.fig .ln.dash { stroke-dasharray: 4 4; stroke: var(--muted); }
.fig .fill { fill: var(--ink2); }
.gallery { display: grid; grid-template-columns: repeat(auto-fill, minmax(118px, 1fr)); gap: 16px 12px; margin: 18px 0 26px; }
.gallery figure { margin: 0; }
.gallery img { display: block; width: 100%; aspect-ratio: 1; object-fit: cover; margin: 0; border-radius: 6px; border: 1px solid var(--line); }
.gallery figcaption { margin-top: 6px; line-height: 1.35; }

/* pager */
.pager { display: flex; justify-content: space-between; gap: 16px; margin-top: 56px; padding-top: 18px; border-top: 1px solid var(--line); }
.pager a { display: flex; flex-direction: column; gap: 4px; color: var(--ink); font-size: var(--fs-body); }
.pager a:hover { color: var(--accent); }
.pager a span { font: 400 var(--fs-small)/1 var(--sans); color: var(--muted); }
.pager .next { margin-left: auto; text-align: right; }

@media (max-width: 1080px) { .shell { grid-template-columns: 200px minmax(0, 1fr); } .toc { display: none; } }
@media (max-width: 760px) {
  .shell, .shell.no-toc { display: block; padding: 24px var(--gutter) 0; }
  .navbtn { display: flex; align-items: center; gap: 10px; padding: 10px 0; margin-bottom: 24px; border-bottom: 1px solid var(--line); font: 400 var(--fs-small)/1.2 var(--sans); color: var(--muted); cursor: pointer; user-select: none; }
  .navbtn .cur { color: var(--ink); font-weight: 500; }
  .side { display: none; position: static; max-height: none; padding-bottom: 12px; }
  .navtoggle:checked ~ .side { display: block; }
}
@media print { .side, .toc, .navbtn, .pager, .copy { display: none !important; } .shell { display: block; } }
"""

JS = r"""// Copy buttons for code blocks, prompt styling for console blocks, and the on-this-page highlight.
// Generated by robouse/scripts/build_docs.py.
document.querySelectorAll(".code").forEach(function (box) {
  var code = box.querySelector("code");
  var text = code.textContent;
  var console = code.classList.contains("language-console");
  if (console) {  // "$ cmd" lines are commands, the rest is output; copy only the commands
    code.innerHTML = text.split("\n").map(function (l) {
      var esc = l.replace(/&/g, "&amp;").replace(/</g, "&lt;");
      return l.indexOf("$ ") === 0 ? '<span class="p">$ </span>' + esc.slice(2) : '<span class="o">' + esc + "</span>";
    }).join("\n");
  }
  var copyText = console ? text.split("\n").filter(function (l) { return l.indexOf("$ ") === 0; }).map(function (l) { return l.slice(2); }).join("\n") : text;
  var b = document.createElement("button");
  b.type = "button"; b.className = "copy"; b.textContent = "Copy";
  b.addEventListener("click", function () {
    (navigator.clipboard ? navigator.clipboard.writeText(copyText) : Promise.reject()).then(function () {
      b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1400);
    }, function () { b.textContent = "Select and copy"; });
  });
  box.appendChild(b);
});
(function () {
  var links = [].slice.call(document.querySelectorAll(".toc a"));
  if (!links.length) return;
  var heads = links.map(function (a) { return document.getElementById(a.getAttribute("href").slice(1)); });
  function update() {
    var cur = 0;
    heads.forEach(function (h, i) { if (h && h.getBoundingClientRect().top < 120) cur = i; });
    links.forEach(function (a, i) { a.classList.toggle("on", i === cur); });
  }
  document.addEventListener("scroll", update, { passive: true });
  update();
})();
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="output directory (replaced if it was built by this script)")
    ap.add_argument("--base", default="/docs/", help="URL path the output is served under (default /docs/)")
    ap.add_argument("--chrome", type=Path, help="the site's tools/chrome.py (default: ../../tools/chrome.py from --out)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--ref", default="HEAD", help="git revision to read docs/ from (default HEAD)")
    src.add_argument("--worktree", action="store_true", help="read the working tree instead (uncommitted edits included)")
    args = ap.parse_args()
    base = "/" + args.base.strip("/") + "/" if args.base.strip("/") else "/"
    out = args.out.expanduser().resolve()
    chrome = load_chrome((args.chrome or out.parent.parent / "tools" / "chrome.py").expanduser().resolve())
    written = build(out, base, Source(None if args.worktree else args.ref), chrome)
    problems = check_output(out)
    for f in sorted(out.rglob("*.html")):
        for m in re.finditer(r"\b[A-Z][A-Z_]*PLACEHOLDER[A-Z_]*\b|\bTODO\b|\bTBD\b", f.read_text(encoding="utf-8")):
            print(f"warning: {f.relative_to(out)}: unfinished text {m.group(0)!r}", file=sys.stderr)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"wrote {len(written)} pages to {out} ({size / 1024:.0f} KiB)")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit("output check failed")


if __name__ == "__main__":
    main()
