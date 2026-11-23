"""Generate backend/static/dark-auto.css: dark-mode overrides for page styles
that set light backgrounds, dark text or light borders without a dark rule.

Run after changing page styles:  python scripts/gen_dark_auto.py
"""
import re, glob, os, colorsys
B = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "backend")
NAMED = {"white": "#ffffff", "black": "#000000"}


def parse_color(v):
    v = v.strip().lower()
    m = re.search(r"#([0-9a-f]{6}|[0-9a-f]{3})(?![0-9a-f])", v)
    if m:
        h = m.group(1)
        if len(h) == 3:
            h = "".join(c * 2 for c in h)
        return tuple(int(h[i:i + 2], 16) / 255 for i in (0, 2, 4)), 1.0
    m = re.search(r"rgba?\(\s*(\d+)\s*,\s*(\d+)\s*,\s*(\d+)\s*(?:,\s*([\d.]+))?\s*\)", v)
    if m:
        return tuple(int(m.group(i)) / 255 for i in (1, 2, 3)), float(m.group(4) or 1)
    m = re.search(r"\b(white|black)\b", v)
    if m:
        return parse_color(NAMED[m.group(1)])
    return None, None


def hexify(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c * 255))):02x}" for c in rgb)


def dark_bg(rgb):
    h, l, s = colorsys.rgb_to_hls(*rgb)
    if s < 0.35 or l > 0.985:
        return "#161b22" if l >= 0.975 else "#21262d"
    return hexify(colorsys.hls_to_rgb(h, 0.17, min(s, 0.6) * 0.55))


def light_text(rgb):
    h, l, s = colorsys.rgb_to_hls(*rgb)
    if s < 0.35:
        return "#e6edf3" if l < 0.22 else ("#c9d1d9" if l < 0.38 else "#8b949e")
    return hexify(colorsys.hls_to_rgb(h, 0.72, min(1.0, s)))


def rules(css):
    css = re.sub(r"/\*.*?\*/", "", css, flags=re.S)
    css = re.sub(r"@media\s+print[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    css = re.sub(r"@(?:-webkit-)?keyframes[^{]*\{(?:[^{}]*\{[^{}]*\})*[^{}]*\}", "", css)
    for m in re.finditer(r"([^{}]+)\{([^{}]*)\}", css):
        sel = m.group(1).strip()
        sel = re.sub(r"^@media[^{]*$", "", sel).strip()
        if sel.startswith("@") or not sel:
            continue
        yield sel, m.group(2)


theme = open(os.path.join(B, "static", "theme.css"), encoding="utf-8").read()


def already_dark(sel_part, file_text):
    classes = re.findall(r"\.([A-Za-z][\w-]*)", sel_part)
    ids = re.findall(r"#([A-Za-z][\w-]*)", sel_part)
    key = classes[-1] if classes else (ids[-1] if ids else None)
    if not key:
        return True  # bare tags (body, th, input...) are handled in theme.css
    sym = "." if classes else "#"
    pat = re.compile(r'data-theme="dark"\][^{]*' + re.escape(sym + key) + r'(?![\w-])')
    return bool(pat.search(theme) or pat.search(file_text))


files = glob.glob(os.path.join(B, "templates", "**", "*.html"), recursive=True) + \
    [f for f in glob.glob(os.path.join(B, "static", "*.css")) if not f.endswith(("theme.css", "dark-auto.css"))]
skip = ("Production_Note", "Art_Job_Sheet", "Sage_Info", "Client_Register", "maintenance", "Feed_Preview")
out, seen = [], set()
for f in sorted(files):
    if any(s in f for s in skip):
        continue
    text = open(f, encoding="utf-8").read()
    blocks = re.findall(r"<style[^>]*>(.*?)</style>", text, re.S) if f.endswith(".html") else [text]
    chunk = []
    for blk in blocks:
        for sel, body in rules(blk):
            if "data-theme" in sel:
                continue
            decls = []
            for prop, val in re.findall(r"(?:^|;)\s*([a-z-]+)\s*:\s*([^;]+)", body):
                val_l = val.lower()
                if prop in ("background", "background-color"):
                    if "url(" in val_l:
                        continue
                    if "gradient" in val_l:
                        stops = [parse_color(x)[0] for x in re.findall(r"#[0-9a-f]{3,6}|rgba?\([^)]*\)|\bwhite\b", val_l)]
                        if stops and all(s and colorsys.rgb_to_hls(*s)[1] >= 0.85 for s in stops):
                            decls.append("background: #161b22")
                        continue
                    rgb, a = parse_color(val)
                    if rgb and a >= 0.5 and colorsys.rgb_to_hls(*rgb)[1] >= 0.85:
                        decls.append(f"background-color: {dark_bg(rgb)}")
                elif prop == "color":
                    rgb, a = parse_color(val)
                    if rgb:
                        _h, _l, _s = colorsys.rgb_to_hls(*rgb)
                        # greys up to mid-grey; coloured text (links, status) up to brand indigo
                        if _l <= 0.45 or (_s >= 0.35 and _l <= 0.62):
                            decls.append(f"color: {light_text(rgb)}")
                elif prop in ("border", "border-color", "border-top", "border-bottom", "border-left", "border-right"):
                    rgb, a = parse_color(val)
                    if rgb and colorsys.rgb_to_hls(*rgb)[1] >= 0.8:
                        side = "" if prop in ("border", "border-color") else prop.split("-")[1] + "-"
                        decls.append(f"border-{side}color: #30363d")
            if not decls:
                continue
            parts = [p.strip() for p in sel.split(",") if p.strip()]
            parts = [p for p in parts if not already_dark(p, text)]
            parts = [p for p in parts if not re.match(r"^(html|body|:root)\b", p)]
            if not parts:
                continue
            dsel = ",\n".join(f'html[data-theme="dark"] {p}' for p in parts)
            key = (dsel, tuple(decls))
            if key in seen:
                continue
            seen.add(key)
            chunk.append(dsel + " { " + "; ".join(decls) + "; }")
    if chunk:
        out.append(f"/* ---- {os.path.relpath(f, B)} ---- */\n" + "\n".join(chunk))

INLINE = '''/* Inline styles set in page scripts (no class to target). */
html[data-theme="dark"] [style*="background:#fff"], html[data-theme="dark"] [style*="background: #fff"],
html[data-theme="dark"] [style*="background:white"], html[data-theme="dark"] [style*="background: white"],
html[data-theme="dark"] [style*="background-color:#fff"], html[data-theme="dark"] [style*="background-color: #fff"],
html[data-theme="dark"] [style*="background:#f8fafc"], html[data-theme="dark"] [style*="background: #f8fafc"],
html[data-theme="dark"] [style*="background:#f9fafb"], html[data-theme="dark"] [style*="background: #f9fafb"] { background-color: #161b22 !important; }
html[data-theme="dark"] [style*="color:#333"], html[data-theme="dark"] [style*="color: #333"],
html[data-theme="dark"] [style*="color:#374151"], html[data-theme="dark"] [style*="color: #374151"],
html[data-theme="dark"] [style*="color:#1f2937"], html[data-theme="dark"] [style*="color: #1f2937"],
html[data-theme="dark"] [style*="color:#111827"], html[data-theme="dark"] [style*="color: #111827"] { color: #e6edf3 !important; }
html[data-theme="dark"] [style*="color:#555"], html[data-theme="dark"] [style*="color: #555"],
html[data-theme="dark"] [style*="color:#666"], html[data-theme="dark"] [style*="color: #666"],
html[data-theme="dark"] [style*="color:#64748b"], html[data-theme="dark"] [style*="color: #64748b"],
html[data-theme="dark"] [style*="color:#6b7280"], html[data-theme="dark"] [style*="color: #6b7280"] { color: #8b949e !important; }
html[data-theme="dark"] [style*="border:1px solid #eee"], html[data-theme="dark"] [style*="border: 1px solid #eee"],
html[data-theme="dark"] [style*="border:1px solid #e5e7eb"], html[data-theme="dark"] [style*="border: 1px solid #e5e7eb"],
html[data-theme="dark"] [style*="border:1px solid #e2e8f0"], html[data-theme="dark"] [style*="border: 1px solid #e2e8f0"] { border-color: #30363d !important; }
'''

HEADER = """/* BiteBoard dark mode - generated overrides for page styles that set light
   backgrounds, dark text or light borders. Each rule mirrors the original
   selector (so hover/active states follow) and keeps the colour's hue.
   Regenerate rather than hand-edit; hand-tuned overrides live in theme.css,
   which wins wherever it already covers a class. */

"""
dst = os.path.join(B, "static", "dark-auto.css")
open(dst, "w", encoding="utf-8").write(HEADER + INLINE + "\n" + "\n\n".join(out) + "\n")
print("rules:", sum(c.count("{") for c in out), "->", dst)
