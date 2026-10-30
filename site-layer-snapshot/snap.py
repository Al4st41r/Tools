"""Capture a web page as a layered, editable SVG.

Usage: uv run snap.py <url> -o out.svg --layers

A headless Chromium (Playwright, using the globally installed browser build) loads the page,
extract.js walks the DOM and returns boxes, text lines and images in document coordinates, and
this script emits SVG groups: one per element, with the top-level sections marked as layers.
"""
from __future__ import annotations

import argparse
import base64
import io
import json
import math
import re
import shutil
import subprocess
import sys
from pathlib import Path
from xml.sax.saxutils import escape, quoteattr

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
EXTRACT_JS = (HERE / "extract.js").read_text()
SAFE_IMG = {"image/png", "image/jpeg", "image/gif", "image/svg+xml"}


def warn(msg: str) -> None:
    print(f"snap: {msg}", file=sys.stderr)


# --------------------------------------------------------------------------- colours / numbers

def n(v: float) -> str:
    s = f"{v:.2f}".rstrip("0").rstrip(".")
    return "0" if s in ("-0", "") else s


def paint(c: str | None) -> tuple[str, float]:
    """CSS colour (as normalised by canvas) -> (fill, alpha)."""
    if not c:
        return "none", 1.0
    m = re.match(r"rgba?\(([^)]+)\)", c)
    if m:
        p = [x.strip() for x in m.group(1).replace("/", ",").replace(" ", ",").split(",") if x.strip()]
        r, g, b = (int(float(x)) for x in p[:3])
        a = float(p[3]) if len(p) > 3 else 1.0
        return f"#{r:02x}{g:02x}{b:02x}", a
    return c, 1.0


def fill_attrs(c: str | None, attr: str = "fill") -> str:
    f, a = paint(c)
    s = f' {attr}="{f}"'
    if a < 1:
        s += f' {attr}-opacity="{n(a)}"'
    return s


def transparent(c: str | None) -> bool:
    return not c or paint(c)[1] == 0


# --------------------------------------------------------------------------- shape helpers

def rr_path(x, y, w, h, rad) -> str:
    (tl, tr, br, bl) = rad
    return (
        f"M{n(x + tl[0])} {n(y)}H{n(x + w - tr[0])}"
        f"A{n(tr[0])} {n(tr[1])} 0 0 1 {n(x + w)} {n(y + tr[1])}V{n(y + h - br[1])}"
        f"A{n(br[0])} {n(br[1])} 0 0 1 {n(x + w - br[0])} {n(y + h)}H{n(x + bl[0])}"
        f"A{n(bl[0])} {n(bl[1])} 0 0 1 {n(x)} {n(y + h - bl[1])}V{n(y + tl[1])}"
        f"A{n(tl[0])} {n(tl[1])} 0 0 1 {n(x + tl[0])} {n(y)}Z"
    )


def shape(x, y, w, h, rad, extra: str) -> str:
    """A rect (uniform radii) or path (mixed radii)."""
    if all(r == rad[0] for r in rad):
        rx, ry = rad[0]
        r = f' rx="{n(rx)}"' if rx else ""
        if ry and ry != rx:
            r += f' ry="{n(ry)}"'
        return f'<rect x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}"{r}{extra}/>'
    return f'<path d="{rr_path(x, y, w, h, rad)}"{extra}/>'


def has_radius(rad) -> bool:
    return any(a or b for a, b in rad)


# --------------------------------------------------------------------------- gradients

def split_top(s: str) -> list[str]:
    out, depth, cur = [], 0, ""
    for ch in s:
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
        if ch == "," and depth == 0:
            out.append(cur.strip())
            cur = ""
        else:
            cur += ch
    if cur.strip():
        out.append(cur.strip())
    return out


DIRS = {"top": 0, "right": 90, "bottom": 180, "left": 270}


def linear_gradient(css: str, x, y, w, h, gid: str) -> str | None:
    m = re.match(r"(repeating-)?linear-gradient\((.*)\)$", css.strip(), re.S)
    if not m or m.group(1):
        return None
    parts = split_top(m.group(2))
    angle = 180.0
    first = parts[0]
    if re.match(r"-?[\d.]+(deg|turn|rad|grad)", first):
        v = float(re.match(r"-?[\d.]+", first).group())
        angle = v * {"deg": 1, "turn": 360, "rad": 180 / math.pi, "grad": 0.9}[re.search(r"[a-z]+$", first).group()]
        parts = parts[1:]
    elif first.startswith("to "):
        sides = first[3:].split()
        angle = sum(DIRS[s] for s in sides) / len(sides) if len(sides) == 1 else (
            {"top right": 45, "right top": 45, "bottom right": 135, "right bottom": 135,
             "bottom left": 225, "left bottom": 225, "top left": 315, "left top": 315}[" ".join(sides)])
        parts = parts[1:]
    stops = []
    for p in parts:
        mm = re.match(r"(rgba?\([^)]*\)|#[0-9a-fA-F]+|\w+)\s*([\d.]+%)?", p)
        if not mm:
            return None
        pos = float(mm.group(2)[:-1]) / 100 if mm.group(2) else None
        stops.append([mm.group(1), pos])
    if len(stops) < 2:
        return None
    if stops[0][1] is None:
        stops[0][1] = 0.0
    if stops[-1][1] is None:
        stops[-1][1] = 1.0
    i = 0
    while i < len(stops):  # spread unpositioned stops evenly
        if stops[i][1] is None:
            j = i
            while stops[j][1] is None:
                j += 1
            lo = stops[i - 1][1]
            for k in range(i, j):
                stops[k][1] = lo + (stops[j][1] - lo) * (k - i + 1) / (j - i + 1)
            i = j
        i += 1
    t = math.radians(angle)
    length = abs(w * math.sin(t)) + abs(h * math.cos(t))
    cx, cy = x + w / 2, y + h / 2
    dx, dy = math.sin(t) * length / 2, -math.cos(t) * length / 2
    out = [f'<linearGradient id="{gid}" gradientUnits="userSpaceOnUse" x1="{n(cx - dx)}" y1="{n(cy - dy)}" '
           f'x2="{n(cx + dx)}" y2="{n(cy + dy)}">']
    for c, pos in stops:
        f, a = paint(c if c.startswith(("rgb", "#")) else c)
        op = f' stop-opacity="{n(a)}"' if a < 1 else ""
        out.append(f'<stop offset="{n(pos)}" stop-color="{f}"{op}/>')
    out.append("</linearGradient>")
    return "".join(out)


# --------------------------------------------------------------------------- shadows

def parse_shadows(css: str):
    res = []
    for s in split_top(css):
        inset = "inset" in s
        cm = re.search(r"(rgba?\([^)]*\)|#[0-9a-fA-F]+)", s)
        if not cm:
            continue
        nums = [float(v) for v in re.findall(r"-?[\d.]+(?=px)", s.replace(cm.group(1), ""))]
        nums += [0.0] * (4 - len(nums))
        res.append({"color": cm.group(1), "dx": nums[0], "dy": nums[1], "blur": nums[2], "spread": nums[3], "inset": inset})
    return res


# --------------------------------------------------------------------------- image handling

class Images:
    def __init__(self, ctx, link: bool):
        self.ctx, self.link, self.cache = ctx, link, {}

    def href(self, url: str) -> str | None:
        if not url:
            return None
        if self.link and not url.startswith("data:"):
            return url
        if url in self.cache:
            return self.cache[url]
        val = self._fetch(url)
        self.cache[url] = val
        return val

    def _fetch(self, url: str) -> str | None:
        try:
            if url.startswith("data:"):
                head, _, body = url.partition(",")
                mime = head[5:].split(";")[0] or "text/plain"
                if mime in SAFE_IMG:
                    return url
                raw = base64.b64decode(body) if ";base64" in head else body.encode()
            else:
                resp = self.ctx.request.get(url, timeout=20000)
                if not resp.ok:
                    raise RuntimeError(f"HTTP {resp.status}")
                raw = resp.body()
                mime = resp.headers.get("content-type", "").split(";")[0].strip()
                if not mime.startswith("image/") and url.lower().endswith(".svg"):
                    mime = "image/svg+xml"
            if mime not in SAFE_IMG:
                # webp/avif/bmp etc.: Affinity and Illustrator are unreliable with these inside SVG.
                from PIL import Image
                im = Image.open(io.BytesIO(raw))
                buf = io.BytesIO()
                im.save(buf, "PNG")
                raw, mime = buf.getvalue(), "image/png"
            return f"data:{mime};base64,{base64.b64encode(raw).decode()}"
        except Exception as e:  # noqa: BLE001 - report and fall back to a link
            warn(f"could not embed {url[:90]}: {e}; leaving as link")
            return None if url.startswith("data:") else url


# --------------------------------------------------------------------------- emitter

class Emitter:
    def __init__(self, data, images: Images, args):
        self.d, self.img, self.a = data, images, args
        self.ids: dict[str, int] = {}
        self.defs: list[str] = []
        self.counter = 0
        self.warned: dict[str, int] = {}

    def note(self, key: str) -> None:
        self.warned[key] = self.warned.get(key, 0) + 1

    def uid(self, base: str) -> str:
        base = re.sub(r"[^A-Za-z0-9_-]+", "-", base).strip("-") or "g"
        if not re.match(r"[A-Za-z_]", base):
            base = "g-" + base
        k = self.ids.get(base, 0)
        self.ids[base] = k + 1
        return base if k == 0 else f"{base}-{k + 1}"

    def did(self, prefix: str) -> str:
        self.counter += 1
        return f"{prefix}{self.counter}"

    # ---- painting of one box -------------------------------------------------
    def box(self, node) -> str:
        st, r = node["style"], node["rect"]
        x, y, w, h = r["x"], r["y"], r["w"], r["h"]
        if w <= 0 or h <= 0 or "bg" not in st and not st.get("border"):
            return ""
        rad = st["radii"]
        out: list[str] = []
        if st.get("shadow") and not self.a.no_shadows:
            for sh in parse_shadows(st["shadow"]):
                if sh["inset"]:
                    self.note("inset box-shadow (skipped)")
                    continue
                f, al = paint(sh["color"])
                if al == 0:
                    continue
                s = sh["spread"]
                extra = fill_attrs(sh["color"])
                if sh["blur"] > 0:
                    fid = self.did("blur")
                    pad = sh["blur"] * 1.5 + 2
                    self.defs.append(
                        f'<filter id="{fid}" filterUnits="userSpaceOnUse" x="{n(x - pad + sh["dx"] - s)}" '
                        f'y="{n(y - pad + sh["dy"] - s)}" width="{n(w + 2 * pad + 2 * s)}" height="{n(h + 2 * pad + 2 * s)}">'
                        f'<feGaussianBlur stdDeviation="{n(sh["blur"] / 2)}"/></filter>')
                    extra += f' filter="url(#{fid})"'
                srad = [(max(0, a + s), max(0, b + s)) for a, b in rad]
                out.append(shape(x + sh["dx"] - s, y + sh["dy"] - s, w + 2 * s, h + 2 * s, srad,
                                 extra + ' class="shadow"'))
        bg = st.get("bg")
        if not transparent(bg):
            out.append(shape(x, y, w, h, rad, fill_attrs(bg) + ' class="bg"'))
        if st.get("bgImage"):
            out.extend(self.bg_images(st, x, y, w, h, rad))
        out.extend(self.borders(st, x, y, w, h, rad))
        return "".join(out)

    def bg_images(self, st, x, y, w, h, rad) -> list[str]:
        out = []
        for layer in split_top(st["bgImage"]):
            if "gradient" in layer:
                gid = self.did("grad")
                g = linear_gradient(layer, x, y, w, h, gid)
                if g:
                    self.defs.append(g)
                    out.append(shape(x, y, w, h, rad, f' fill="url(#{gid})" class="bg-gradient"'))
                else:
                    self.note("radial/repeating gradient (skipped)")
            else:
                m = re.match(r'url\(["\']?(.*?)["\']?\)$', layer)
                if not m:
                    continue
                href = self.img.href(m.group(1))
                if not href:
                    continue
                size = st.get("bgSize", "auto")
                par = "xMidYMid slice" if size == "cover" else "xMidYMid meet" if size == "contain" else "none"
                if size not in ("cover", "contain"):
                    self.note("background-image sizing/tiling approximated as stretch")
                cid = self.did("clip")
                self.defs.append(f'<clipPath id="{cid}">{shape(x, y, w, h, rad, "")}</clipPath>')
                out.append(f'<g clip-path="url(#{cid})"><image x="{n(x)}" y="{n(y)}" width="{n(w)}" height="{n(h)}" '
                           f'preserveAspectRatio="{par}" href={quoteattr(href)} class="bg-image"/></g>')
        return out

    def borders(self, st, x, y, w, h, rad) -> list[str]:
        b = st.get("border") or []
        vis = [s for s in b if s["w"] > 0 and s["style"] not in ("none", "hidden") and not transparent(s["color"])]
        if not vis:
            return []
        same = len(vis) == 4 and all((s["w"], s["style"], s["color"]) == (vis[0]["w"], vis[0]["style"], vis[0]["color"]) for s in vis)
        if same:
            bw = vis[0]["w"]
            inner = [(max(0, a - bw / 2), max(0, c - bw / 2)) for a, c in rad]
            dash = {"dashed": f' stroke-dasharray="{n(bw * 3)} {n(bw * 2)}"', "dotted": f' stroke-dasharray="0 {n(bw * 2)}" stroke-linecap="round"'}.get(vis[0]["style"], "")
            extra = ' fill="none"' + fill_attrs(vis[0]["color"], "stroke") + f' stroke-width="{n(bw)}"{dash} class="border"'
            return [shape(x + bw / 2, y + bw / 2, w - bw, h - bw, inner, extra)]
        # Mixed sides: filled strips (corner joins are square; radii ignored).
        if has_radius(rad):
            self.note("per-side borders with border-radius (radius ignored on border)")
        t, rt, bt, lt = b
        out = []
        def strip(s, rx, ry, rw, rh):
            if s in vis:
                out.append(f'<rect x="{n(rx)}" y="{n(ry)}" width="{n(rw)}" height="{n(rh)}"{fill_attrs(s["color"])} class="border"/>')
        strip(t, x, y, w, t["w"]); strip(bt, x, y + h - bt["w"], w, bt["w"])
        strip(lt, x, y + t["w"], lt["w"], h - t["w"] - bt["w"]); strip(rt, x + w - rt["w"], y + t["w"], rt["w"], h - t["w"] - bt["w"])
        return out

    # ---- text / replaced content ---------------------------------------------
    def text(self, k) -> str:
        s = k["style"]
        attrs = (f' font-family={quoteattr(s["family"].replace(chr(34), chr(39)))} font-size="{n(s["size"])}"'
                 f' font-weight="{s["weight"]}"')
        if s["fstyle"] != "normal":
            attrs += f' font-style="{s["fstyle"]}"'
        if s["ls"]:
            attrs += f' letter-spacing="{n(s["ls"])}"'
        if s["deco"]:
            attrs += f' text-decoration="{s["deco"]}"'
        attrs += fill_attrs(s["color"])
        out = []
        for ln in k["lines"]:
            fit = (f' textLength="{n(ln["w"])}" lengthAdjust="spacing"' if self.a.fit_text else "")
            out.append(f'<text x="{n(ln["x"])}" y="{n(ln["y"])}"{attrs}{fit} xml:space="preserve">{escape(ln["text"])}</text>')
        return "".join(out)

    def replaced(self, node) -> str:
        if node.get("svg"):
            return f'<g class="inline-svg">{node["svg"]}</g>'
        if node.get("canvas"):
            r = node["rect"]
            return (f'<image x="{n(r["x"])}" y="{n(r["y"])}" width="{n(r["w"])}" height="{n(r["h"])}" '
                    f'href={quoteattr(node["canvas"])} class="canvas"/>')
        if node.get("canvasError"):
            self.note("tainted canvas (skipped)")
        im = node.get("img")
        if im:
            href = self.img.href(im["src"])
            if not href:
                return ""
            r, fit = im["rect"], im["fit"]
            par = {"cover": "xMidYMid slice", "contain": "xMidYMid meet", "fill": "none", "none": "xMidYMid meet"}.get(fit, "none")
            if fit in ("cover", "none", "scale-down"):
                cid = self.did("clip")
                self.defs.append(f'<clipPath id="{cid}"><rect x="{n(r["x"])}" y="{n(r["y"])}" width="{n(r["w"])}" height="{n(r["h"])}"/></clipPath>')
                pre, post = f'<g clip-path="url(#{cid})">', "</g>"
            else:
                pre = post = ""
            title = f"<title>{escape(im['alt'])}</title>" if im["alt"] else ""
            return (f'{pre}<image x="{n(r["x"])}" y="{n(r["y"])}" width="{n(r["w"])}" height="{n(r["h"])}" '
                    f'preserveAspectRatio="{par}" href={quoteattr(href)} class="img">{title}</image>{post}')
        if node.get("iframe"):
            self.note("iframe (content not captured)")
        return ""

    # ---- recursion ------------------------------------------------------------
    @staticmethod
    def is_wrapper(node) -> bool:
        kids = node["kids"]
        return len(kids) == 1 and "tag" in kids[0] and not node.get("img") and not node.get("svg")

    def group(self, node, level: int) -> str:
        """Emit a node. Single-child wrappers collapse without consuming a layer level."""
        st = node["style"]
        r = node["rect"]
        body_parts = [self.box(node), self.replaced(node)]
        if self.is_wrapper(node) and level == 0:
            # Wrapper: own paint sits in the layer of its child.
            child = self.group(node["kids"][0], level)
            return self.wrap(node, level, "".join(body_parts) + child, wrapper=True)
        for k in node["kids"]:
            body_parts.append(self.text(k) if k.get("t") == "text" else self.group(k, level + 1))
        return self.wrap(node, level, "".join(body_parts))

    def wrap(self, node, level: int, inner: str, wrapper: bool = False) -> str:
        if not inner.strip():
            return ""
        st, r = node["style"], node["rect"]
        attrs = f'id="{self.uid(node["label"])}"'
        if wrapper:
            pass
        is_layer = self.a.layers and 1 <= level <= self.a.layer_depth and not wrapper
        label = node["label"]
        if self.a.layers:
            attrs += f" inkscape:label={quoteattr(label)}"
            if is_layer:
                attrs += ' inkscape:groupmode="layer"'
        if st.get("opacity", 1) < 1:
            attrs += f' opacity="{n(st["opacity"])}"'
        if st.get("overflow") and not self.a.no_clip and node["tag"] not in ("html", "body") and r["w"] > 0 and r["h"] > 0:
            cid = self.did("clip")
            self.defs.append(f'<clipPath id="{cid}">{shape(r["x"], r["y"], r["w"], r["h"], st["radii"], "")}</clipPath>')
            attrs += f' clip-path="url(#{cid})"'
        return f"<g {attrs}>{inner}</g>"

    def document(self) -> str:
        d = self.d
        W, H = d["width"], d["height"]
        # Level 0 = page. html > body collapse as wrappers; first branching element hosts the layers.
        body = self.group(d["root"], 0)
        bg = d.get("canvasBg")
        bgrect = ""
        if bg is not None:
            bgrect = (f'<g id="page-background"' + (' inkscape:label="Page background" inkscape:groupmode="layer"' if self.a.layers else "") +
                      f'><rect x="0" y="0" width="{n(W)}" height="{n(H)}"{fill_attrs(bg)}/></g>')
        defs = f"<defs>{''.join(self.defs)}</defs>" if self.defs else ""
        title = f"<title>{escape(d['title'] or d['url'])}</title>"
        ns = ' xmlns:inkscape="http://www.inkscape.org/namespaces/inkscape"' if self.a.layers else ""
        return (f'<?xml version="1.0" encoding="UTF-8"?>\n'
                f'<svg xmlns="http://www.w3.org/2000/svg" xmlns:xlink="http://www.w3.org/1999/xlink"{ns} '
                f'width="{n(W)}" height="{n(H)}" viewBox="0 0 {n(W)} {n(H)}">\n'
                f'{title}<desc>Captured from {escape(d["url"])} by snap.py</desc>\n{defs}\n{bgrect}\n{body}\n</svg>\n')


# --------------------------------------------------------------------------- browser

def capture(args):
    with sync_playwright() as p:
        browser = p.chromium.launch(args=["--no-sandbox"])
        ctx = browser.new_context(viewport={"width": args.width, "height": args.viewport_height},
                                  device_scale_factor=1, locale="en-GB")
        page = ctx.new_page()
        page.goto(args.url, wait_until="load", timeout=args.timeout)
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:  # noqa: BLE001
            pass
        # Scroll through to trigger lazy loading, then return to the top.
        height = page.evaluate("document.documentElement.scrollHeight")
        pos = 0
        while pos < min(height, args.max_height):
            page.evaluate(f"window.scrollTo(0,{pos})")
            page.wait_for_timeout(120)
            pos += args.viewport_height
            height = page.evaluate("document.documentElement.scrollHeight")
        page.evaluate("window.scrollTo(0,0)")
        page.evaluate("document.fonts && document.fonts.ready")
        page.wait_for_timeout(args.wait)
        data = page.evaluate(EXTRACT_JS, {})
        images = Images(ctx, args.link_images)
        em = Emitter(data, images, args)
        svg = em.document()
        browser.close()
    return data, em, svg


def font_report(families: list[str]) -> None:
    if not shutil.which("fc-match"):
        return
    generic = {"serif", "sans-serif", "monospace", "system-ui", "cursive", "fantasy", "-apple-system", "ui-sans-serif",
               "ui-serif", "ui-monospace", "blinkmacsystemfont"}
    missing = []
    for fam in sorted(set(families)):
        if not fam or fam.lower() in generic:
            continue
        out = subprocess.run(["fc-match", "-f", "%{family}", fam], capture_output=True, text=True).stdout
        if fam.lower() not in out.lower():
            missing.append(fam)
    if missing:
        warn("fonts used by the page that are not installed on this machine (the SVG names them, but "
             "your editor will substitute unless you install them): " + ", ".join(missing))


def main() -> int:
    ap = argparse.ArgumentParser(description="Capture a web page as a layered, editable SVG.")
    ap.add_argument("url")
    ap.add_argument("-o", "--output", default="out.svg")
    ap.add_argument("--layers", action="store_true", help="mark top-level sections as named layers")
    ap.add_argument("--layer-depth", type=int, default=1, help="how many nesting levels become layers (default 1)")
    ap.add_argument("--width", type=int, default=1440, help="viewport width in px (default 1440)")
    ap.add_argument("--viewport-height", type=int, default=900)
    ap.add_argument("--max-height", type=int, default=30000, help="stop scrolling for lazy content beyond this")
    ap.add_argument("--wait", type=int, default=500, help="extra settle time in ms")
    ap.add_argument("--timeout", type=int, default=45000)
    ap.add_argument("--link-images", action="store_true", help="reference images by URL instead of embedding")
    ap.add_argument("--fit-text", action="store_true", help="add textLength so substituted fonts keep line widths")
    ap.add_argument("--no-shadows", action="store_true")
    ap.add_argument("--no-clip", action="store_true", help="do not clip overflow:hidden boxes")
    args = ap.parse_args()

    data, em, svg = capture(args)
    out = Path(args.output)
    out.write_text(svg, encoding="utf-8")
    st = data["stats"]
    warn(f"wrote {out} ({len(svg) / 1024:.0f} KiB, {data['width']}x{data['height']} px)")
    for key, label in [("transforms", "elements with CSS transform (placed by bounding box; rotation/skew lost)"),
                       ("filters", "elements with CSS filter/backdrop-filter (not reproduced)"),
                       ("blend", "elements with mix-blend-mode (not reproduced)"),
                       ("pseudo", "::before/::after with generated content (not captured)")]:
        if st[key]:
            warn(f"{st[key]} {label}")
    for k, v in em.warned.items():
        warn(f"{v} x {k}")
    font_report(data["fonts"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
