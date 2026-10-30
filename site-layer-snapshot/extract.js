// In-page DOM walker. Returns a JSON-serialisable tree of boxes, text lines and
// replaced content in document coordinates. Evaluated by snap.py via Playwright.
(opts) => {
  const SX = window.scrollX, SY = window.scrollY;
  const stats = { transforms: 0, filters: 0, pseudo: 0, blend: 0, clipped: 0 };
  const cv = document.createElement('canvas').getContext('2d');
  const colCache = new Map();

  // Normalise any CSS colour (including modern colour spaces) to #rrggbb / rgba().
  function col(c) {
    if (!c) return null;
    if (colCache.has(c)) return colCache.get(c);
    cv.fillStyle = '#000'; cv.fillStyle = c;
    const v = cv.fillStyle;
    colCache.set(c, v);
    return v;
  }
  const px = (v) => parseFloat(v) || 0;
  const SKIP = new Set(['SCRIPT', 'STYLE', 'NOSCRIPT', 'HEAD', 'META', 'LINK', 'TEMPLATE', 'TITLE', 'BASE']);

  function rectOf(el) {
    const r = el.getBoundingClientRect();
    return { x: r.left + SX, y: r.top + SY, w: r.width, h: r.height };
  }

  function radii(cs, w, h) {
    const names = ['TopLeft', 'TopRight', 'BottomRight', 'BottomLeft'];
    const out = names.map((n) => {
      const parts = cs['border' + n + 'Radius'].split(' ');
      const f = (s, ref) => (s.endsWith('%') ? (parseFloat(s) / 100) * ref : px(s));
      return [f(parts[0], w), f(parts[1] || parts[0], h)];
    });
    // Scale down as CSS does when radii overlap.
    const k = Math.min(1,
      w / Math.max(1e-6, out[0][0] + out[1][0]), w / Math.max(1e-6, out[3][0] + out[2][0]),
      h / Math.max(1e-6, out[0][1] + out[3][1]), h / Math.max(1e-6, out[1][1] + out[2][1]));
    return out.map(([a, b]) => [a * k, b * k]);
  }

  function boxStyle(el, cs, r) {
    const sides = ['Top', 'Right', 'Bottom', 'Left'];
    const border = sides.map((s) => ({
      w: px(cs['border' + s + 'Width']),
      style: cs['border' + s + 'Style'],
      color: col(cs['border' + s + 'Color']),
    }));
    const bgImg = cs.backgroundImage !== 'none' ? cs.backgroundImage : null;
    return {
      bg: col(cs.backgroundColor),
      bgImage: bgImg,
      bgSize: cs.backgroundSize,
      bgPos: cs.backgroundPosition,
      bgRepeat: cs.backgroundRepeat,
      border,
      radii: radii(cs, r.w, r.h),
      shadow: cs.boxShadow !== 'none' ? cs.boxShadow : null,
      opacity: parseFloat(cs.opacity),
      overflow: cs.overflowX !== 'visible' || cs.overflowY !== 'visible',
      z: cs.zIndex === 'auto' ? 0 : parseInt(cs.zIndex, 10) || 0,
      positioned: cs.position !== 'static',
    };
  }

  function textLines(node, cs) {
    const out = [];
    const data = node.data;
    const re = /\S+/g;
    let m;
    const words = [];
    const range = document.createRange();
    while ((m = re.exec(data))) {
      range.setStart(node, m.index);
      range.setEnd(node, m.index + m[0].length);
      const rects = range.getClientRects();
      if (!rects.length) continue;
      // A word split over lines yields several rects; keep the first (limitation).
      const r = rects[0];
      if (r.width === 0 && r.height === 0) continue;
      words.push({ s: m[0], x: r.left + SX, y: r.top + SY, w: r.width, h: r.height, r2: rects.length > 1 });
    }
    if (!words.length) return out;

    const fam = cs.fontFamily;
    cv.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${fam}`;
    const mm = cv.measureText('Hg');
    const asc = mm.fontBoundingBoxAscent, desc = mm.fontBoundingBoxDescent;
    const tt = cs.textTransform;
    const tf = (s) => (tt === 'uppercase' ? s.toUpperCase() : tt === 'lowercase' ? s.toLowerCase()
      : tt === 'capitalize' ? s.replace(/(^|\s)\S/g, (c) => c.toUpperCase()) : s);

    let cur = null;
    for (const w of words) {
      if (cur && Math.abs(w.y - cur.top) < Math.max(2, w.h * 0.4)) {
        cur.parts.push(w.s); cur.right = w.x + w.w;
      } else {
        if (cur) out.push(cur);
        cur = { x: w.x, top: w.y, h: w.h, right: w.x + w.w, parts: [w.s] };
      }
    }
    if (cur) out.push(cur);
    return out.map((l) => ({
      x: l.x,
      y: l.top + (l.h - (asc + desc)) / 2 + asc,
      w: l.right - l.x,
      text: tf(l.parts.join(' ')),
    }));
  }

  function textStyle(cs) {
    return {
      family: cs.fontFamily,
      size: px(cs.fontSize),
      weight: cs.fontWeight,
      fstyle: cs.fontStyle,
      color: col(cs.color),
      ls: cs.letterSpacing === 'normal' ? 0 : px(cs.letterSpacing),
      deco: cs.textDecorationLine === 'none' ? null : cs.textDecorationLine,
    };
  }

  function serialiseSvg(el, r, cs) {
    const clone = el.cloneNode(true);
    const origAll = [el, ...el.querySelectorAll('*')];
    const cloneAll = [clone, ...clone.querySelectorAll('*')];
    const props = ['fill', 'stroke', 'stroke-width', 'stroke-linecap', 'stroke-linejoin', 'stroke-dasharray',
      'fill-opacity', 'stroke-opacity', 'opacity', 'fill-rule', 'clip-rule', 'stop-color', 'stop-opacity',
      'font-family', 'font-size', 'font-weight'];
    origAll.forEach((o, i) => {
      const c = cloneAll[i];
      if (!(o instanceof SVGElement) || !c) return;
      const ocs = getComputedStyle(o);
      for (const p of props) {
        const v = ocs.getPropertyValue(p);
        if (v && !/^(none|normal)$/.test(v) || p === 'fill' || p === 'stroke') {
          let val = v;
          if (p === 'fill' || p === 'stroke' || p === 'stop-color') {
            if (val.startsWith('url(')) { c.setAttribute(p, val); continue; }
            if (val === 'none') { c.setAttribute(p, 'none'); continue; }
            val = col(val);
          }
          c.setAttribute(p, val);
        }
      }
      c.removeAttribute('class');
      c.removeAttribute('style');
    });
    if (!clone.getAttribute('viewBox')) {
      const aw = px(el.getAttribute('width')) || r.w, ah = px(el.getAttribute('height')) || r.h;
      clone.setAttribute('viewBox', `0 0 ${aw} ${ah}`);
    }
    clone.setAttribute('x', r.x); clone.setAttribute('y', r.y);
    clone.setAttribute('width', r.w); clone.setAttribute('height', r.h);
    clone.removeAttribute('class'); clone.removeAttribute('style');
    return new XMLSerializer().serializeToString(clone).replace(/currentColor/g, col(cs.color));
  }

  function label(el) {
    let s = el.tagName.toLowerCase();
    if (el.id) s += '#' + el.id;
    else if (typeof el.className === 'string' && el.className.trim()) {
      s += '.' + el.className.trim().split(/\s+/).slice(0, 2).join('.');
    }
    return s.slice(0, 48);
  }

  function walk(el) {
    if (SKIP.has(el.tagName)) return null;
    const cs = getComputedStyle(el);
    if (cs.display === 'none' || cs.visibility === 'hidden' && el.tagName !== 'HTML') {
      // visibility:hidden elements can have visible descendants; handle by walking children only.
      if (cs.display === 'none') return null;
    }
    const hidden = cs.visibility === 'hidden' || cs.visibility === 'collapse';
    if (parseFloat(cs.opacity) === 0) return null;
    const r = rectOf(el);
    const node = { tag: el.tagName.toLowerCase(), label: label(el), rect: r, kids: [] };

    if (cs.transform !== 'none') stats.transforms++;
    if (cs.filter !== 'none' || cs.backdropFilter !== 'none') stats.filters++;
    if (cs.mixBlendMode !== 'normal') stats.blend++;
    for (const pe of ['::before', '::after']) {
      const c = getComputedStyle(el, pe).content;
      if (c && c !== 'none' && c !== 'normal' && c !== '""') stats.pseudo++;
    }

    if (!hidden) node.style = boxStyle(el, cs, r);
    else node.style = { opacity: 1, border: [], radii: [[0,0],[0,0],[0,0],[0,0]], z: 0 };
    node.style.opacity = parseFloat(cs.opacity);
    if (node.style.overflow) stats.clipped++;

    // Replaced / special content
    if (el.tagName === 'IMG' && !hidden) {
      const pl = px(cs.paddingLeft) + px(cs.borderLeftWidth), pt = px(cs.paddingTop) + px(cs.borderTopWidth);
      const pr = px(cs.paddingRight) + px(cs.borderRightWidth), pb = px(cs.paddingBottom) + px(cs.borderBottomWidth);
      node.img = {
        src: el.currentSrc || el.src,
        rect: { x: r.x + pl, y: r.y + pt, w: r.w - pl - pr, h: r.h - pt - pb },
        fit: cs.objectFit, pos: cs.objectPosition,
        natural: [el.naturalWidth, el.naturalHeight],
        alt: el.alt || '',
      };
    } else if (el.tagName === 'svg' || el instanceof SVGSVGElement) {
      if (!hidden) node.svg = serialiseSvg(el, r, cs);
      return node;
    } else if (el.tagName === 'CANVAS' && !hidden) {
      try { node.canvas = el.toDataURL('image/png'); } catch (e) { node.canvasError = String(e); }
    } else if ((el.tagName === 'INPUT' || el.tagName === 'TEXTAREA') && !hidden) {
      const t = el.tagName === 'INPUT' ? el.type : 'textarea';
      const val = ['text', 'search', 'email', 'url', 'tel', 'number', 'password', 'textarea', 'submit', 'button'].includes(t)
        ? (t === 'password' ? '•'.repeat(el.value.length) : el.value) : '';
      const shown = val || el.placeholder || '';
      if (shown) {
        const pl = px(cs.paddingLeft) + px(cs.borderLeftWidth);
        const pt = px(cs.paddingTop) + px(cs.borderTopWidth);
        cv.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
        const mm = cv.measureText('Hg');
        const asc = mm.fontBoundingBoxAscent, desc = mm.fontBoundingBoxDescent;
        const ts = textStyle(cs);
        if (!val) ts.color = col(getComputedStyle(el, '::placeholder').color);
        const centre = ['submit', 'button'].includes(t);
        const tw = cv.measureText(shown).width;
        const y = t === 'textarea' ? r.y + pt + asc : r.y + (r.h - (asc + desc)) / 2 + asc;
        node.kids.push({
          t: 'text', style: ts,
          lines: [{ x: centre ? r.x + (r.w - tw) / 2 : r.x + pl, y, w: tw, text: shown }],
        });
      }
      return node;
    }

    for (const ch of el.childNodes) {
      if (ch.nodeType === 3) {
        if (hidden) continue;
        const lines = textLines(ch, cs);
        if (lines.length) node.kids.push({ t: 'text', style: textStyle(cs), lines });
      } else if (ch.nodeType === 1) {
        const k = walk(ch);
        if (k) node.kids.push(k);
      }
    }
    // Light-DOM only: shadow roots and iframes are not traversed (documented limitation).
    if (el.tagName === 'IFRAME') node.iframe = el.src;
    // Paint order: positioned children with a z-index above static siblings.
    node.kids.sort((a, b) => ((a.style ? a.style.z : 0) - (b.style ? b.style.z : 0)));
    return node;
  }

  const fonts = new Set();
  document.querySelectorAll('*').forEach((e) => {
    if (e.childNodes.length) fonts.add(getComputedStyle(e).fontFamily.split(',')[0].replace(/["']/g, '').trim());
  });
  const root = walk(document.documentElement);
  const bgOf = (e) => col(getComputedStyle(e).backgroundColor);
  return {
    root,
    title: document.title,
    url: location.href,
    width: Math.max(document.documentElement.scrollWidth, window.innerWidth),
    height: Math.max(document.documentElement.scrollHeight, document.body ? document.body.scrollHeight : 0),
    canvasBg: bgOf(document.documentElement) !== 'rgba(0, 0, 0, 0)' ? bgOf(document.documentElement)
      : (document.body ? bgOf(document.body) : null),
    stats,
    fonts: [...fonts],
  };
}
