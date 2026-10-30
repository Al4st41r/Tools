# site-layer-snapshot

Captures a web page as a layered, editable SVG. Text stays as text, images become separate
`<image>` elements, boxes become rectangles and paths, and each top-level section becomes a named layer.

```bash
uv run snap.py https://www.python.org -o python.svg --layers
uv run tests/smoke.py          # offline smoke test against tests/fixture.html
```

It uses Playwright's Python API against the Chromium build already installed for `shot-scraper`
(`playwright==1.49.1` is pinned to match `chromium-1148` in `~/.cache/ms-playwright`). No browser is installed.

## Options

| Option | Effect |
| --- | --- |
| `-o FILE` | Output path (default `out.svg`). |
| `--layers` | Label groups and mark the top-level sections as layers (`inkscape:groupmode="layer"`). Without it the same group structure is written with no layer metadata. |
| `--layer-depth N` | Nesting levels that become layers (default 1). Single-child wrappers such as `html > body > #app` are collapsed first. |
| `--width PX` | Viewport width (default 1440). The page is captured at this width, full height. |
| `--link-images` | Reference images by URL instead of embedding them as data URIs. |
| `--fit-text` | Adds `textLength` per line so substituted fonts keep the original line widths (letter spacing is adjusted; slightly less natural to edit). |
| `--no-shadows`, `--no-clip` | Skip drop shadows, or skip `overflow` clipping. |
| `--wait MS` | Extra settling time after load and lazy-load scrolling. |

Warnings about anything that could not be reproduced are printed to stderr, including a list of fonts the
page uses that are not installed on the machine.

## Feasibility: approaches considered

| Approach | Result | Verdict |
| --- | --- | --- |
| **Headless Chromium DOM walk, emit SVG groups** (this tool) | Measured: `python.org` rendered back in Chromium is visually close to the original (layout, colours, gradients, borders, radii, images, live text). | Chosen. Only route that gives real layers, live text and per-element control. |
| **Chromium print-to-PDF** (`shot-scraper pdf`) | Measured: text is real and vector, but the PDF contains no `/OCProperties` or `/OCG`, so there are no layers. Uses print CSS and paginates. | Rejected for layers. Useful as a flat reference only. |
| **dom-to-svg** (npm) | Desk research, not run here. Similar idea to this tool (DOM to SVG with text as text, stacking-context groups), implemented as an in-page library. | Reasonable alternative; this tool adds embedded-image handling, font reporting and layer naming in Python. |
| **foreignObject approaches** (html-to-image, dom-to-image) | Desk research, not run here. The SVG wraps HTML inside `<foreignObject>`. | Rejected. Illustrator and Affinity do not render or edit `foreignObject`. |
| **SingleFile** | Desk research, not run here. Produces a self-contained HTML archive, not a vector. | Not applicable to this goal. |
| **SVG to PDF with optional content groups (OCGs)** | Not built. Needs a custom PDF writer (or a converter that maps SVG layers to OCGs; the common converters I know of flatten groups). | Left as future work (see below). |

## What the SVG contains

- **Layers.** A "Page background" layer, then one layer per top-level section (for example `header.main-header`,
  `div#content`, `footer#site-map`). Every element is its own named `<g>`, nested inside its layer, so sections
  can be hidden, moved or restyled.
- **Text.** One `<text>` per rendered line, positioned from the browser's own line boxes, with font family, size,
  weight, style, colour, letter spacing and underline. `text-transform` is applied to the string. Input values
  and placeholders are included.
- **Images.** `<img>`, `<picture>` and CSS `url()` backgrounds become `<image>` elements, embedded by default.
  `webp`/`avif` are converted to PNG with Pillow, as editors handle them poorly inside SVG. `object-fit` and
  `background-size: cover|contain` map to `preserveAspectRatio`.
- **Vector content.** Inline `<svg>` is nested with its computed fills and strokes inlined, `currentColor`
  resolved. `<canvas>` is rasterised to an image.
- **Boxes.** Backgrounds, linear gradients, uniform and per-side borders, rounded corners, drop shadows
  (blurred copies using `feGaussianBlur`), opacity and `overflow` clipping.

## Limitations

- **Fonts.** The SVG names the page's fonts but does not embed them. Web fonts (for example Source Sans on
  python.org) will fall back to whatever your editor has, so widths change and lines may collide or gap.
  Install the fonts locally, or use `--fit-text`. Icon fonts (Font Awesome, Pythonicon and the like) are drawn
  with `::before`/`::after` content, which is not captured, so icons disappear.
- **Pseudo-elements.** `::before` and `::after` (generated content, decorative shapes, many icons) are not captured.
  The count is reported.
- **CSS transforms.** Elements are placed by their bounding box, so rotation and skew are lost and rotated
  elements will be the wrong shape. `filter`, `backdrop-filter` and `mix-blend-mode` are not reproduced.
- **Backgrounds.** Radial and repeating gradients are skipped. Background tiling, `background-position`
  and multi-value sizes are approximated as a stretch. Inset shadows and `text-shadow` are skipped.
- **Borders.** Per-side borders with differing styles are drawn as square-cornered strips; radius is ignored on those.
- **Text edge cases.** A word that wraps mid-word keeps only its first fragment. Vertical writing modes, text on
  a path and `-webkit-text-stroke` are not handled. Shaping (ligatures, kerning) depends on the editor's font.
- **Page content not reached.** Content inside iframes, closed or open shadow roots, and `<video>` is not
  captured. Pages behind a login are not supported, and animations are captured at whatever state they
  are in after the wait (python.org's slideshow was mid-fade in testing).
- **Dynamic and fixed layout.** The capture is a single viewport width at scroll position 0. Sticky and fixed
  elements appear where they sit at the top. Lazy content is triggered by scrolling; infinite-scroll pages
  stop at `--max-height`.
- **File size.** Embedded images are base64, so image-heavy pages produce large files. `--link-images` avoids that
  but the file then depends on the network.
- **Paint order.** Order follows the DOM with a stable sort on `z-index`. Full stacking-context rules
  are not implemented.

## Editor compatibility (not tested)

No Affinity or Illustrator is available on this machine, so layer behaviour there is **unverified**. Expectations
from general knowledge of those apps:

- **Inkscape** reads the `inkscape:groupmode="layer"` markers directly as layers.
- **Illustrator** typically converts top-level SVG groups into layers and keeps nested groups as groups.
- **Affinity Designer/Publisher** import SVG groups as groups; whether the top-level ones become layers depends on
  the version. If they do not, the named groups still appear in the Layers panel and can be moved or hidden.
- Shadows rely on SVG filters, which some editors rasterise or ignore. Use `--no-shadows` if they cause trouble.

Please report what your editor does with the output of `tests/fixture.html` so this section can be corrected.

## Future work

- PDF output with real OCGs, generated from the same node tree rather than from the SVG.
- Capture of `::before`/`::after` content, and rotation via the element's transform matrix.
- Embedding or outlining of fonts as an option.
