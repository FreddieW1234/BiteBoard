"""Customer feed docs as a web page, rendered from docs/customer-feed-api.md.

Served on the feed host (FEED_API_HOST) at / and /docs. The Markdown file stays
the single source; this handles only the subset it uses: headings, paragraphs,
bullet lists, fenced code, tables, inline code, bold and links.
"""

from __future__ import annotations

import html
import re
import threading
from pathlib import Path

_DOC_PATH = Path(__file__).resolve().parent.parent / "docs" / "customer-feed-api.md"
_LOCK = threading.Lock()
_CACHE: dict = {}


def _inline(text: str) -> str:
    parts = re.split(r"(`[^`]+`)", text)
    out = []
    for part in parts:
        if part.startswith("`") and part.endswith("`") and len(part) > 1:
            out.append(f"<code>{html.escape(part[1:-1])}</code>")
            continue
        s = html.escape(part, quote=False)
        s = re.sub(r"\*\*(.+?)\*\*", r"<strong>\1</strong>", s)
        s = re.sub(r"\[([^\]]+)\]\((https?://[^)\s]+)\)", r'<a href="\2">\1</a>', s)
        out.append(s)
    return "".join(out)


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", re.sub(r"`", "", text.lower())).strip("-")


def markdown_to_html(md: str) -> tuple[str, str, list[tuple[str, str]]]:
    """Returns (title, body html, [(anchor, heading)] for level-2 headings)."""
    lines = md.replace("\r\n", "\n").split("\n")
    out: list[str] = []
    toc: list[tuple[str, str]] = []
    title = "Product feed API"
    i = 0
    para: list[str] = []

    def flush_para():
        if para:
            out.append(f"<p>{_inline(' '.join(para))}</p>")
            para.clear()

    while i < len(lines):
        line = lines[i]
        stripped = line.strip()
        if stripped.startswith("```"):
            flush_para()
            code = []
            i += 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                code.append(lines[i])
                i += 1
            out.append(f"<pre><code>{html.escape(chr(10).join(code))}</code></pre>")
            i += 1
            continue
        m = re.match(r"^(#{1,3})\s+(.*)$", stripped)
        if m:
            flush_para()
            level, text = len(m.group(1)), m.group(2).strip()
            if level == 1:
                title = re.sub(r"`", "", text)
                out.append(f"<h1>{_inline(text)}</h1>")
            else:
                anchor = _slug(text)
                if level == 2:
                    toc.append((anchor, re.sub(r"`", "", text)))
                out.append(f'<h{level} id="{anchor}">{_inline(text)}</h{level}>')
            i += 1
            continue
        if stripped.startswith("|") and stripped.endswith("|"):
            flush_para()
            rows = []
            while i < len(lines) and lines[i].strip().startswith("|"):
                rows.append([c.strip() for c in lines[i].strip().strip("|").split("|")])
                i += 1
            head, body = rows[0], [r for r in rows[1:] if not all(re.fullmatch(r":?-+:?", c) for c in r)]
            t = ["<div class=\"table-wrap\"><table><thead><tr>"]
            t += [f"<th>{_inline(c)}</th>" for c in head]
            t.append("</tr></thead><tbody>")
            for r in body:
                t.append("<tr>" + "".join(f"<td>{_inline(c)}</td>" for c in r) + "</tr>")
            t.append("</tbody></table></div>")
            out.append("".join(t))
            continue
        if re.match(r"^[-*]\s+", stripped):
            flush_para()
            items: list[str] = []
            while i < len(lines):
                cur = lines[i]
                if re.match(r"^\s*[-*]\s+", cur):
                    items.append(re.sub(r"^\s*[-*]\s+", "", cur).strip())
                elif cur.strip() and cur.startswith((" ", "\t")) and items:
                    items[-1] += " " + cur.strip()
                else:
                    break
                i += 1
            out.append("<ul>" + "".join(f"<li>{_inline(x)}</li>" for x in items) + "</ul>")
            continue
        if not stripped:
            flush_para()
            i += 1
            continue
        para.append(stripped)
        i += 1
    flush_para()
    return title, "\n".join(out), toc


_PAGE = """<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<meta name="robots" content="noindex">
<style>
:root {{ --bg:#fff; --fg:#1f2328; --muted:#59636e; --line:#d1d9e0; --code-bg:#f6f8fa; --accent:#4f46e5; }}
@media (prefers-color-scheme: dark) {{
  :root {{ --bg:#0d1117; --fg:#e6edf3; --muted:#9198a1; --line:#30363d; --code-bg:#161b22; --accent:#8b8cf6; }}
}}
* {{ box-sizing: border-box; }}
body {{ margin:0; background:var(--bg); color:var(--fg);
  font:16px/1.6 system-ui, -apple-system, "Segoe UI", Roboto, sans-serif; }}
.wrap {{ max-width: 860px; margin: 0 auto; padding: 32px 16px 80px; }}
header.top {{ border-bottom:1px solid var(--line); margin-bottom: 8px; padding-bottom: 12px;
  display:flex; justify-content:space-between; align-items:baseline; flex-wrap:wrap; gap:8px; }}
header.top .brand {{ font-weight:700; letter-spacing:.2px; }}
header.top .host {{ color:var(--muted); font-size:.9rem; }}
nav.toc {{ margin: 16px 0 8px; padding: 12px 16px; border:1px solid var(--line); border-radius:8px; }}
nav.toc strong {{ display:block; font-size:.8rem; text-transform:uppercase; color:var(--muted); margin-bottom:6px; }}
nav.toc a {{ display:inline-block; margin: 2px 14px 2px 0; }}
h1 {{ font-size: 1.9rem; line-height:1.25; margin: 24px 0 8px; }}
h2 {{ font-size: 1.35rem; margin: 40px 0 8px; padding-top:8px; border-top:1px solid var(--line); }}
h3 {{ font-size: 1.05rem; margin: 28px 0 6px; }}
a {{ color: var(--accent); }}
code {{ font: .88em/1.5 ui-monospace, SFMono-Regular, Consolas, monospace; background:var(--code-bg);
  padding: .1em .35em; border-radius:4px; }}
pre {{ background:var(--code-bg); border:1px solid var(--line); border-radius:8px; padding:14px 16px; overflow-x:auto; }}
pre code {{ background:none; padding:0; font-size:.85rem; }}
ul {{ padding-left: 1.3em; }}
li {{ margin: 4px 0; }}
.table-wrap {{ overflow-x:auto; }}
table {{ border-collapse: collapse; width:100%; margin: 8px 0; font-size:.95rem; }}
th, td {{ border:1px solid var(--line); padding: 6px 10px; text-align:left; vertical-align:top; }}
th {{ background: var(--code-bg); }}
footer {{ margin-top: 48px; color:var(--muted); font-size:.85rem; }}
</style>
</head>
<body>
<div class="wrap">
<header class="top"><span class="brand">Bite Promotions</span><span class="host">Product feed API</span></header>
{toc}
{body}
<footer>Questions or a new key: contact your Bite Promotions account manager.</footer>
</div>
</body>
</html>
"""


def render_docs_page() -> str:
    """The docs page HTML; re-rendered only when the Markdown file changes."""
    try:
        mtime = _DOC_PATH.stat().st_mtime
    except OSError:
        mtime = None
    with _LOCK:
        if _CACHE.get("mtime") == mtime and "html" in _CACHE:
            return _CACHE["html"]
    md = _DOC_PATH.read_text(encoding="utf-8") if mtime is not None else "# Product feed API\n\nDocs unavailable."
    title, body, toc = markdown_to_html(md)
    toc_html = ""
    if toc:
        links = "".join(f'<a href="#{a}">{html.escape(t)}</a>' for a, t in toc)
        toc_html = f'<nav class="toc"><strong>On this page</strong>{links}</nav>'
    page = _PAGE.format(title=html.escape(title), toc=toc_html, body=body)
    with _LOCK:
        _CACHE.update(mtime=mtime, html=page)
    return page
