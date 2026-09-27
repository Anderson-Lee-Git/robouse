#!/usr/bin/env python3
"""Build the static robo-use docs site (robouse.ai/docs/) from README.md and docs/.

    python scripts/build_docs.py --out ~/benchflow/roboharm/site/docs
    python scripts/build_docs.py --out /tmp/docs --base /docs/     # --base is the URL prefix the pages are served under

Standard library only (Python 3.11+): it has its own small markdown converter that covers what these docs use
(headings, paragraphs, nested lists, fenced code, tables, block quotes, links, images, emphasis, inline code).
No third-party packages are needed.

Output: one page per doc at <out>/<slug>/index.html (pretty URLs, linked with a trailing slash), <out>/index.html
from README.md, a generated suites overview at <out>/suites/index.html, images copied from docs/, and docs.css /
docs.js. The pages expect /theme.js and /fonts/{Inter,PlexMono-400,PlexMono-500}.woff2 at the site root.

Links between published .md files are rewritten to the generated pages (anchors kept). Links to repository files
that are not published (source code, STATUS.md, runs/, internal notes) become plain text or inline code, since
the repository is private. The build fails if the output contains the banned word list or anything that looks
like a credential (see check_output).

Pages and navigation are listed in PAGES below; a doc that is not listed is not published.
"""

from __future__ import annotations

import argparse
import html
import posixpath
import re
import shutil
import sys
from dataclasses import dataclass
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
MARKER = ".build_docs"  # written into --out so a rebuild only ever clears a directory this script owns

# (group, source path relative to the repo, slug, nav label). Order = sidebar order = prev/next order.
PAGES: list[tuple[str, str, str, str]] = [
    ("Getting started", "README.md", "", "Overview"),
    ("Getting started", "docs/quickstart.md", "quickstart", "Quickstart"),
    ("Guides", "docs/harnesses.md", "harnesses", "Harnesses and models"),
    ("Guides", "docs/benchflow.md", "benchflow", "Running through BenchFlow"),
    ("Guides", "docs/viewer.md", "viewer", "Viewing trials"),
    ("Guides", "docs/audit.md", "audit", "Automatic audit"),
    ("Guides", "docs/molmoact2.md", "molmoact2", "MolmoAct2 (VLA)"),
    ("Suites", "docs/suites/", "suites", "All suites"),  # generated overview
    ("Suites", "docs/suites/tabletop.md", "suites/tabletop", "Tabletop"),
    ("Suites", "docs/suites/gymrobotics.md", "suites/gymrobotics", "Gymnasium-Robotics"),
    ("Suites", "docs/suites/libero.md", "suites/libero", "LIBERO"),
    ("Suites", "docs/suites/robosuite.md", "suites/robosuite", "robosuite"),
    ("Suites", "docs/suites/dexjoco.md", "suites/dexjoco", "DexJoCo"),
    ("Suites", "docs/suites/roboharm.md", "suites/roboharm", "RoboHarm v0.1"),
    ("Suites", "docs/suites/drone.md", "suites/drone", "Drone"),
    ("Suites", "docs/suites/vision.md", "suites/vision", "Vision tier"),
    ("Suites", "docs/suites/hard.md", "suites/hard", "Hard tier"),
    ("Reference", "docs/task-format.md", "task-format", "Task format"),
    ("Reference", "docs/robo-cli.md", "robo-cli", "The robo command"),
    ("Results", "docs/results.md", "results", "Results"),
]
SUITES_INDEX = "docs/suites/"
# Not published: internal process notes. Any other docs/*.md missing from PAGES is reported at build time;
# a new docs/suites/*.md is added to the Suites group automatically.
EXCLUDED = {
    "docs/review-log.md": "internal log of documentation review passes",
    "docs/research/": "internal literature and dataset surveys used for planning",
}
TITLE_OVERRIDES = {"README.md": "robo-use"}  # the README's H1 is the repo name; the site uses the brand
# Paragraphs that make sense in the repository but not on the site (regex on the paragraph's first line).
DROP_PARAGRAPHS = {"README.md": [r"^Private, work in progress\."]}
# One line per suite for the generated suites overview (keep in step with the suite pages).
SUITE_SUMMARIES = {
    "tabletop": "39 tasks in one scene built from MuJoCo primitives: LIBERO-style, ARC-style rule inference, robo-use families and harmful/benign safety pairs.",
    "gymrobotics": "12 tasks from Farama's Gymnasium-Robotics: 6 Fetch manipulation and 6 PointMaze navigation tasks.",
    "libero": "20 tasks from LIBERO (Liu et al. 2023), 5 from each standard suite, so VLA policies and LLM agents can be compared on the same tasks.",
    "robosuite": "21 tasks on robosuite 1.5 with full robot arms (Franka Panda, UR5e, Kinova Gen3, KUKA IIWA, Sawyer), one arm or two.",
    "dexjoco": "14 dexterous tool-use tasks from DexJoCo: a Franka arm carrying a 16-joint Allegro hand instead of a gripper.",
    "roboharm": "80 tasks: 10 harm scenarios, each with a benign twin, in 4 configurations. Does the agent carry out harmful physical requests?",
    "drone": "10 tasks with a Skydio X2 over a small town: four flight skills and three harmful/benign safety pairs.",
    "vision": "55 tasks where the agent gets camera images instead of object coordinates.",
    "hard": "25 tasks with low-level control only, no calibrated cameras, and rules shown only as pictures.",
}

# Build-time guard: none of these may appear in the output.
BANNED_WORDS = ["banned-name"]
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

    def __init__(self, link, labels=None):
        self.link = link
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
        if re.match(r"^(https?:|mailto:)", href):
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
                cls = f' class="language-{lang}"' if lang else ""
                # IBM Plex Mono (as subset on the site) has no box-drawing or arrow glyphs; a diagram in mixed
                # fonts loses its alignment, so diagrams use one system monospace font throughout.
                diagram = ' class="diagram"' if re.search("[\u2190-\u21ff\u2500-\u25ff]", "".join(body)) else ""
                out.append(f'<div class="code"><pre{diagram}><code{cls}>{html.escape(chr(10).join(body), quote=False)}</code></pre></div>')
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


def page_url(base: str, slug: str) -> str:
    return base + (slug + "/" if slug else "")


def suites_markdown(pages: list[Page]) -> str:
    lines = ["# Suites", "",
             "Each suite adapts an existing benchmark or scene family to the robo-use task format. Every task ships a reference solution that scores 1, and the no-op control scores 0 on every task. Solve rates per harness and model are on the [Results](../results.md) page.",
             ""]
    for p in pages:
        if not p.src.startswith("docs/suites/") or p.src == SUITES_INDEX:
            continue
        name = posixpath.splitext(posixpath.basename(p.src))[0]
        lines.append(f"- [{p.label}]({name}.md): {SUITE_SUMMARIES.get(name, '')}".rstrip(": "))
    lines += ["", "Meta-World (the 50 MT50 tasks, `tasks/metaworld/`) and the MuJoCo Menagerie tasks (`tasks/menagerie/`) have no page of their own yet. For Meta-World, the [task format](../task-format.md) page uses `metaworld-push` as its example."]
    return "\n".join(lines) + "\n"


def page_list() -> list[Page]:
    pages = [Page(*p) for p in PAGES]
    listed = {p.src for p in pages}
    last_suite = max(i for i, p in enumerate(pages) if p.group == "Suites")
    for f in sorted((REPO / "docs/suites").glob("*.md")):
        src = f"docs/suites/{f.name}"
        if src not in listed:
            h1 = next((l[2:].strip() for l in f.read_text(encoding="utf-8").splitlines() if l.startswith("# ")), f.stem)
            last_suite += 1
            pages.insert(last_suite, Page("Suites", src, f"suites/{f.stem}", re.sub(r"\s+suite\b.*$", "", plain(h1)) or f.stem))
            print(f"note: added unlisted suite page {src}", file=sys.stderr)
    for f in sorted((REPO / "docs").glob("*.md")):
        src = f"docs/{f.name}"
        if src not in listed and src not in EXCLUDED:
            print(f"note: {src} is neither in PAGES nor in EXCLUDED; not published", file=sys.stderr)
    return pages


def build(out: Path, base: str) -> list[Path]:
    pages = page_list()
    by_src = {p.src: p for p in pages}
    copies: dict[str, str] = {}  # repo path -> output-relative path (images)

    for p in pages:
        src_dir = posixpath.dirname(p.src) if p.src != SUITES_INDEX else "docs/suites"

        def link(href: str, src_dir=src_dir) -> str | None:
            path, _, anchor = href.partition("#")
            if not path:
                return "#" + anchor if anchor else None
            target = posixpath.normpath(posixpath.join(src_dir, path))
            if path.endswith("/"):
                target += "/"
            frag = "#" + anchor if anchor else ""
            if target in by_src:
                return page_url(base, by_src[target].slug) + frag
            if target.rstrip("/") + "/" == SUITES_INDEX:
                return page_url(base, by_src[SUITES_INDEX].slug) + frag
            if re.search(r"\.(png|jpe?g|gif|svg|webp)$", target, re.I) and target.startswith("docs/") and (REPO / target).is_file():
                rel = target[len("docs/"):]
                copies[target] = rel
                return base + rel
            return None

        md = suites_markdown(pages) if p.src == SUITES_INDEX else (REPO / p.src).read_text(encoding="utf-8")
        md = re.sub(r"/Users/(?!<)[^/\s`]+/", "~/", md)  # tidy absolute home paths
        for pat in DROP_PARAGRAPHS.get(p.src, []):
            md = "\n\n".join(b for b in re.split(r"\n\s*\n", md) if not re.match(pat, b.strip()))
        conv = Converter(link, {page_url(base, q.slug): q.label for q in pages})
        lines = md.splitlines()
        if p.src in TITLE_OVERRIDES and lines and lines[0].startswith("# "):
            lines[0] = "# " + TITLE_OVERRIDES[p.src]
        p.body = conv.blocks(lines)
        h1 = next((t for lvl, _, t in conv.headings if lvl == 1), p.label)
        p.title = plain(h1)
        paras = [b for b in re.split(r"\n\s*\n", md) if b.strip() and not b.lstrip().startswith(("#", "`", "|", "-", "!", ">"))]
        desc = re.sub(r"\s+", " ", plain(paras[0])) if paras else p.title
        p.description = desc if len(desc) <= 180 else desc[:177].rsplit(" ", 1)[0] + "..."

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
        shutil.copyfile(REPO / src, dst)
    written = []
    for k, p in enumerate(pages):
        prev_p = pages[k - 1] if k > 0 else None
        next_p = pages[k + 1] if k + 1 < len(pages) else None
        dst = out / p.slug / "index.html" if p.slug else out / "index.html"
        dst.parent.mkdir(parents=True, exist_ok=True)
        dst.write_text(render(p, pages, base, prev_p, next_p), encoding="utf-8")
        written.append(dst)
    return written


def render(p: Page, pages: list[Page], base: str, prev_p: Page | None, next_p: Page | None) -> str:
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
    nav.append('<p class="grp">Experiments</p><ul><li><a href="/runs/">Run viewer</a></li></ul>')
    pager = []
    if prev_p:
        pager.append(f'<a class="prev" href="{page_url(base, prev_p.slug)}"><span>Previous</span>{e(prev_p.label)}</a>')
    if next_p:
        pager.append(f'<a class="next" href="{page_url(base, next_p.slug)}"><span>Next</span>{e(next_p.label)}</a>')
    title = "robo-use docs" if not p.slug else f"{p.title} · robo-use docs"
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
<meta property="og:site_name" content="robo-use">
<meta property="og:title" content="{e(title)}">
<meta property="og:description" content="{e(p.description)}">
<meta property="og:url" content="{canonical}">
<link rel="icon" href="/favicon.png">
<script src="/theme.js"></script>
<link rel="stylesheet" href="{base}docs.css">
<script src="{base}docs.js" defer></script>
</head>
<body>
<header class="bar">
  <a class="mark" href="/">robo-use</a>
  <nav><a href="/work/">Work</a><a href="/runs/">Runs</a><a href="{base}" aria-current="page">Docs</a></nav>
</header>
<div class="shell">
<input type="checkbox" id="navtoggle" class="navtoggle" hidden>
<label for="navtoggle" class="navbtn">Menu<span class="cur">{e(p.label)}</span></label>
<aside class="side"><nav aria-label="Docs">
{chr(10).join(nav)}
</nav></aside>
<main class="doc">
<article>
{p.body}
</article>
<nav class="pager">{"".join(pager)}</nav>
</main>
</div>
<footer><div class="foot">
  <a class="bf" href="https://benchflow.ai"><img src="/benchflow-mark.svg" alt="" width="13" height="13">BenchFlow</a>
  <span class="theme-pick" role="group" aria-label="Theme"><button type="button" data-theme-set="system">System</button><button type="button" data-theme-set="light">Light</button><button type="button" data-theme-set="dark">Dark</button></span>
  <a href="mailto:xiangyi@benchflow.ai">Contact</a>
</div></footer>
</body>
</html>
"""


def check_output(out: Path) -> list[str]:
    problems = []
    for f in sorted(out.rglob("*")):
        if not f.is_file() or f.suffix not in {".html", ".css", ".js"}:
            continue
        text = f.read_text(encoding="utf-8")
        for w in BANNED_WORDS:
            if w in text.lower():
                problems.append(f"{f.relative_to(out)}: banned word {w!r}")
        for pat in SECRET_PATTERNS:
            for m in re.finditer(pat, text):
                problems.append(f"{f.relative_to(out)}: looks like a credential: {m.group(0)[:24]}...")
    return problems


CSS = r"""/* robo-use docs. Generated by robouse/scripts/build_docs.py; edit the script, not this file. */
@font-face { font-family: "Inter"; src: url("/fonts/Inter.woff2") format("woff2"); font-weight: 100 900; font-style: normal; font-display: swap; }
@font-face { font-family: "IBM Plex Mono"; src: url("/fonts/PlexMono-400.woff2") format("woff2"); font-weight: 400; font-style: normal; font-display: swap; }
@font-face { font-family: "IBM Plex Mono"; src: url("/fonts/PlexMono-500.woff2") format("woff2"); font-weight: 500; font-style: normal; font-display: swap; }

:root {
  --bg: #ffffff; --fg: #18181a; --muted: #6a6a70; --faint: #9a9aa0; --rule: #e7e7e4; --soft: #f6f6f3;
  --code-bg: #f6f6f3; --code-fg: #1f1f22; --link: #18181a; --link-line: #c4c4c0; --accent: #1f5fd6; --mark: #fff6c8;
  --sans: "Inter", ui-sans-serif, system-ui, -apple-system, "Segoe UI", Helvetica, Arial, sans-serif;
  --mono: "IBM Plex Mono", ui-monospace, SFMono-Regular, Menlo, Consolas, monospace;
  --bar: 56px;
  color-scheme: light;
}
html[data-theme="dark"] {
  --bg: #111113; --fg: #e9e9e6; --muted: #a0a0a6; --faint: #6f6f76; --rule: #26262a; --soft: #19191c;
  --code-bg: #18181b; --code-fg: #e4e4e0; --link: #e9e9e6; --link-line: #55555c; --accent: #7aa7ff; --mark: #3a3520;
  color-scheme: dark;
}
@media (prefers-color-scheme: dark) {
  html:not([data-theme]) {
    --bg: #111113; --fg: #e9e9e6; --muted: #a0a0a6; --faint: #6f6f76; --rule: #26262a; --soft: #19191c;
    --code-bg: #18181b; --code-fg: #e4e4e0; --link: #e9e9e6; --link-line: #55555c; --accent: #7aa7ff; --mark: #3a3520;
    color-scheme: dark;
  }
}

* { box-sizing: border-box; }
html { -webkit-text-size-adjust: 100%; scroll-padding-top: calc(var(--bar) + 16px); }
body { margin: 0; background: var(--bg); color: var(--fg); font: 400 16px/1.65 var(--sans); font-feature-settings: "cv11", "ss01"; -webkit-font-smoothing: antialiased; }
a { color: var(--link); text-decoration: underline; text-decoration-color: var(--link-line); text-underline-offset: 3px; text-decoration-thickness: 1px; }
a:hover { text-decoration-color: currentColor; }

/* header */
.bar { position: sticky; top: 0; z-index: 20; height: var(--bar); display: flex; align-items: center; justify-content: space-between; gap: 24px; padding: 0 28px; background: var(--bg); border-bottom: 1px solid var(--rule); }
.bar .mark { font-weight: 600; font-size: 16px; letter-spacing: -0.01em; text-decoration: none; }
.bar nav { display: flex; gap: 22px; font-size: 14px; }
.bar nav a { text-decoration: none; color: var(--muted); }
.bar nav a:hover, .bar nav a[aria-current="page"] { color: var(--fg); }

/* layout */
.shell { display: grid; grid-template-columns: 250px minmax(0, 1fr); max-width: 1180px; margin: 0 auto; }
.side { position: sticky; top: var(--bar); align-self: start; height: calc(100vh - var(--bar)); overflow-y: auto; padding: 28px 20px 40px 28px; font-size: 14px; }
.side .grp { margin: 22px 0 6px; font-size: 11.5px; font-weight: 600; letter-spacing: 0.06em; text-transform: uppercase; color: var(--faint); }
.side .grp:first-child { margin-top: 0; }
.side ul { list-style: none; margin: 0; padding: 0; }
.side li a { display: block; padding: 4px 10px; margin-left: -10px; border-radius: 6px; color: var(--muted); text-decoration: none; line-height: 1.4; }
.side li a:hover { color: var(--fg); background: var(--soft); }
.side li a[aria-current="page"] { color: var(--fg); background: var(--soft); font-weight: 500; }
.navbtn { display: none; }
.doc { min-width: 0; padding: 36px 48px 64px; max-width: 860px; }

/* prose */
article { overflow-wrap: break-word; }
article h1 { font-size: 34px; line-height: 1.2; letter-spacing: -0.022em; font-weight: 650; margin: 0 0 20px; }
article h2 { font-size: 23px; line-height: 1.3; letter-spacing: -0.015em; font-weight: 620; margin: 48px 0 12px; padding-top: 4px; }
article h3 { font-size: 18px; line-height: 1.35; font-weight: 620; margin: 34px 0 8px; }
article h4, article h5, article h6 { font-size: 16px; font-weight: 620; margin: 26px 0 6px; }
article h2 code, article h3 code, article h4 code { font-size: 0.9em; }
.hash { margin-left: 8px; color: var(--faint); text-decoration: none; opacity: 0; font-weight: 400; }
h2:hover .hash, h3:hover .hash, h4:hover .hash, .hash:focus { opacity: 1; }
article p, article ul, article ol, article blockquote { margin: 0 0 16px; }
article ul, article ol { padding-left: 22px; }
article li { margin: 4px 0; }
article li > ul, article li > ol { margin: 4px 0 6px; }
article li > p { margin: 0 0 8px; }
article strong { font-weight: 600; }
article hr { border: 0; border-top: 1px solid var(--rule); margin: 36px 0; }
article blockquote { padding: 2px 0 2px 16px; border-left: 2px solid var(--rule); color: var(--muted); }
article img { display: block; max-width: 100%; height: auto; margin: 8px 0; border-radius: 6px; border: 1px solid var(--rule); }

/* code */
code { font-family: var(--mono); font-size: 0.86em; background: var(--code-bg); color: var(--code-fg); padding: 0.12em 0.34em; border-radius: 4px; overflow-wrap: anywhere; }
.code { position: relative; margin: 0 0 18px; }
pre { margin: 0; padding: 14px 16px; background: var(--code-bg); border: 1px solid var(--rule); border-radius: 8px; overflow-x: auto; -webkit-overflow-scrolling: touch; font: 400 13px/1.6 var(--mono); tab-size: 4; }
pre.diagram { font-family: ui-monospace, SFMono-Regular, Menlo, Consolas, "DejaVu Sans Mono", monospace; }
pre code { display: block; width: max-content; min-width: 100%; padding: 0; background: none; border-radius: 0; font-size: inherit; white-space: pre; overflow-wrap: normal; }
.copy { position: absolute; top: 7px; right: 7px; padding: 3px 8px; font: 500 11.5px/1.4 var(--sans); color: var(--muted); background: var(--bg); border: 1px solid var(--rule); border-radius: 5px; cursor: pointer; opacity: 0; transition: opacity .12s; }
.code:hover .copy, .copy:focus-visible { opacity: 1; }
.copy:hover { color: var(--fg); }
@media (hover: none) { .copy { opacity: 1; } }

/* tables */
.table { margin: 0 0 20px; overflow-x: auto; -webkit-overflow-scrolling: touch; border: 1px solid var(--rule); border-radius: 8px; }
table { border-collapse: collapse; width: 100%; font-size: 14px; line-height: 1.5; }
th, td { padding: 8px 12px; text-align: left; vertical-align: top; border-bottom: 1px solid var(--rule); }
th { font-weight: 600; background: var(--soft); white-space: nowrap; }
tbody tr:last-child td { border-bottom: 0; }
td code { font-size: 0.84em; overflow-wrap: break-word; }
td:first-child code { white-space: nowrap; }

/* pager */
.pager { display: flex; justify-content: space-between; gap: 16px; margin-top: 56px; padding-top: 20px; border-top: 1px solid var(--rule); }
.pager a { display: flex; flex-direction: column; gap: 2px; text-decoration: none; font-weight: 500; font-size: 15px; }
.pager a span { font-size: 12px; font-weight: 400; color: var(--faint); }
.pager .next { margin-left: auto; text-align: right; }

/* footer */
footer { border-top: 1px solid var(--rule); }
.foot { max-width: 1180px; margin: 0 auto; padding: 22px 28px 32px; display: flex; flex-wrap: wrap; align-items: center; gap: 12px 24px; font-size: 13.5px; color: var(--muted); }
.foot a { color: var(--muted); text-decoration: none; }
.foot a:hover { color: var(--fg); }
.foot .bf { display: inline-flex; align-items: center; gap: 7px; margin-right: auto; }
html[data-theme="dark"] .foot .bf img { filter: invert(1); }
@media (prefers-color-scheme: dark) { html:not([data-theme]) .foot .bf img { filter: invert(1); } }
.theme-pick { display: inline-flex; padding: 2px; border: 1px solid var(--rule); border-radius: 7px; }
.theme-pick button { font: 500 12px/1 var(--sans); color: var(--muted); background: none; border: 0; border-radius: 5px; padding: 6px 9px; cursor: pointer; }
.theme-pick button:hover { color: var(--fg); }
.theme-pick button[aria-pressed="true"] { color: var(--fg); background: var(--soft); }

/* mobile */
@media (max-width: 860px) {
  .bar { padding: 0 18px; }
  .shell { display: block; }
  .navbtn { display: flex; align-items: center; gap: 10px; position: sticky; top: var(--bar); z-index: 15; padding: 10px 18px; background: var(--bg); border-bottom: 1px solid var(--rule); font-size: 14px; font-weight: 500; cursor: pointer; user-select: none; }
  .navbtn::before { content: ""; width: 14px; height: 10px; border-top: 1.5px solid currentColor; border-bottom: 1.5px solid currentColor; box-shadow: inset 0 4.25px 0 -3px currentColor; }
  .navbtn .cur { color: var(--muted); font-weight: 400; }
  .side { display: none; position: static; height: auto; padding: 8px 18px 20px; border-bottom: 1px solid var(--rule); }
  .navtoggle:checked ~ .side { display: block; }
  .doc { padding: 26px 18px 48px; }
  article h1 { font-size: 28px; }
  article h2 { font-size: 21px; margin-top: 40px; }
  pre { font-size: 12.5px; }
  .foot { padding: 20px 18px 28px; }
}
@media print { .bar, .side, .navbtn, .pager, footer, .copy { display: none !important; } .shell { display: block; } }
"""

JS = r"""// Copy buttons for code blocks. Generated by robouse/scripts/build_docs.py.
document.querySelectorAll(".code").forEach(function (box) {
  var b = document.createElement("button");
  b.type = "button"; b.className = "copy"; b.textContent = "Copy";
  b.addEventListener("click", function () {
    var t = box.querySelector("code").innerText;
    (navigator.clipboard ? navigator.clipboard.writeText(t) : Promise.reject()).then(function () {
      b.textContent = "Copied"; setTimeout(function () { b.textContent = "Copy"; }, 1400);
    }, function () { b.textContent = "Select and copy"; });
  });
  box.appendChild(b);
});
"""


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--out", required=True, type=Path, help="output directory (replaced if it was built by this script)")
    ap.add_argument("--base", default="/docs/", help="URL path the output is served under (default /docs/)")
    args = ap.parse_args()
    base = "/" + args.base.strip("/") + "/" if args.base.strip("/") else "/"
    out = args.out.expanduser().resolve()
    written = build(out, base)
    problems = check_output(out)
    for f in sorted(out.rglob("*.html")):
        for m in re.finditer(r"\b[A-Z][A-Z_]*PLACEHOLDER[A-Z_]*\b|\bTODO\b|\bTBD\b", f.read_text(encoding="utf-8")):
            print(f"warning: {f.relative_to(out)}: unfinished text {m.group(0)!r} (source doc still being written?)", file=sys.stderr)
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"wrote {len(written)} pages to {out} ({size / 1024:.0f} KiB)")
    if problems:
        print("\n".join(problems), file=sys.stderr)
        sys.exit("output check failed")


if __name__ == "__main__":
    main()
