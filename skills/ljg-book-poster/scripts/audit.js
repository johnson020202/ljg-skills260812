/* In-page layout audit. Returns a plain JSON object; run via page.evaluate(). */
(() => {
  const poster = document.querySelector('#poster') || document.querySelector('main') || document.body;
  const scrollY0 = window.scrollY || document.documentElement.scrollTop || 0;

  const rectOf = (el) => {
    const r = el.getBoundingClientRect();
    return { x: r.x, y: r.y + scrollY0, w: r.width, h: r.height, right: r.right, bottom: r.bottom + scrollY0 };
  };

  const selOf = (el) => {
    if (!el || el.nodeType !== 1) return '?';
    if (el.id) return '#' + el.id;
    const cls = (el.getAttribute('class') || '').trim().split(/\s+/).filter(Boolean).slice(0, 2);
    return el.tagName.toLowerCase() + (cls.length ? '.' + cls.join('.') : '');
  };

  const visible = (el) => {
    if (!el || el.closest('[data-export-ignore]')) return false;
    if (getComputedStyle(el).visibility !== 'visible') return false;
    let opacity = 1;
    for (let e = el; e; e = e.parentElement) {
      const cs = getComputedStyle(e);
      opacity *= Number(cs.opacity);
      if (cs.display === 'none' || cs.contentVisibility === 'hidden' || opacity <= 0) return false;
    }
    return true;
  };

  const parseColor = (c) => {
    if (!c) return null;
    const m = c.match(/rgba?\(([^)]+)\)/);
    if (!m) return null;
    const p = m[1].split(/[,\s\/]+/).filter(Boolean).map(Number);
    if (p.length < 3) return null;
    return { r: p[0], g: p[1], b: p[2], a: p.length > 3 ? p[3] : 1 };
  };

  const bgOf = (el) => {
    let e = el;
    while (e && e.nodeType === 1) {
      const c = parseColor(getComputedStyle(e).backgroundColor);
      if (c && c.a > 0.85) return c;
      e = e.parentElement;
    }
    const bodyBg = parseColor(getComputedStyle(document.body).backgroundColor);
    return bodyBg || { r: 255, g: 255, b: 255, a: 1 };
  };

  const lum = (c) => {
    const f = (v) => {
      v /= 255;
      return v <= 0.03928 ? v / 12.92 : Math.pow((v + 0.055) / 1.055, 2.4);
    };
    return 0.2126 * f(c.r) + 0.7152 * f(c.g) + 0.0722 * f(c.b);
  };
  const contrast = (a, b) => {
    const l1 = lum(a), l2 = lum(b);
    return (Math.max(l1, l2) + 0.05) / (Math.min(l1, l2) + 0.05);
  };

  const issues = [];
  const seen = new Set();
  const add = (sev, code, msg, el, extra) => {
    const s = selOf(el);
    const key = code + '|' + s + '|' + ((extra && extra.pseudo) || '') + '|' + Math.round((extra && extra.y) || 0);
    if (seen.has(key)) return;
    seen.add(key);
    issues.push(Object.assign({ sev, code, msg, selector: s }, extra || {}));
  };

  // ---------- sections ----------
  const sectionSel = ':scope > section, :scope > header, :scope > footer, :scope > div[data-section]';
  let sections = [...poster.querySelectorAll(sectionSel)];
  if (!sections.length) {
    sections = [...poster.children].filter((el) => el.nodeType === 1 && rectOf(el).h > 40);
  }
  const sectionInfo = sections.map((el, i) => {
    const r = rectOf(el);
    const raw = el.getAttribute('data-name') ||
      (el.getAttribute('class') || '').trim().split(/\s+/).filter((c) => c && !/^(island|dark|light)$/.test(c)).join('-') ||
      el.tagName.toLowerCase();
    return { index: i, name: String(i + 1).padStart(2, '0') + '-' + raw, el, x: r.x, y: r.y, h: r.h, right: r.right, bottom: r.bottom, radius: parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0 };
  });

  const posterRect = rectOf(poster);
  const pageHeight = Math.max(document.body.scrollHeight, document.documentElement.scrollHeight);
  const pageWidth = Math.max(document.body.scrollWidth, document.documentElement.scrollWidth);

  // ---------- global checks ----------
  if (pageWidth > posterRect.w + 2) {
    add(1, 'H-OVERFLOW', `页面存在横向溢出：内容宽 ${Math.round(pageWidth)}px > 画布 ${Math.round(posterRect.w)}px`, poster, { y: 0 });
  }
  const last = sectionInfo[sectionInfo.length - 1];
  if (last && pageHeight - last.bottom > 140) {
    add(1, 'BOTTOM-VOID', `底部空白 ${Math.round(pageHeight - last.bottom)}px（最后区块结束后无内容）`, last.el, { y: last.bottom, section: last.name });
  }
  if (sectionInfo[0] && sectionInfo[0].y < 16) {
    add(3, 'TOP-TIGHT', `首个区块距画布顶部仅 ${Math.round(sectionInfo[0].y)}px`, sectionInfo[0].el, { y: 0, section: sectionInfo[0].name });
  }
  for (let i = 1; i < sectionInfo.length; i++) {
    const gap = sectionInfo[i].y - sectionInfo[i - 1].bottom;
    if (gap < 12) {
      add(2, 'SECTION-GAP', `区块「${sectionInfo[i].name}」与上一块间距仅 ${Math.round(gap)}px`, sectionInfo[i].el, { y: sectionInfo[i].y, section: sectionInfo[i].name });
    }
  }
  sectionInfo.forEach((s) => {
    if (s.radius >= 40 && (s.x <= posterRect.x + 6 || s.right >= posterRect.right - 6)) {
      add(3, 'EDGE-TIGHT', `圆角区块「${s.name}」贴住画布边缘，四角无法完整露出`, s.el, { y: s.y, section: s.name });
    }
  });

  // ---------- walk rendered text nodes ----------
  const lineRects = (node) => {
    const r = document.createRange();
    r.selectNodeContents(node);
    return [...r.getClientRects()]
      .filter((rr) => rr.height > 0 && rr.width > 0)
      .map((rr) => ({ top: Math.round(rr.top + scrollY0), left: rr.left, right: rr.right, w: rr.width }));
  };

  const walker = document.createTreeWalker(poster, NodeFilter.SHOW_TEXT);
  const nodes = [];
  let n;
  while ((n = walker.nextNode())) {
    const t = n.nodeValue;
    if (!t || !t.trim()) continue;
    const el = n.parentElement;
    if (!el || !visible(el)) continue;
    const rects = lineRects(n);
    if (!rects.length) continue;
    const cs = getComputedStyle(el);
    nodes.push({ node: n, el, cs, text: t, rects });
  }

  // Font floor is a hard user rule: nothing visible may be smaller than 70 CSS px.
  const fontFloorPx = 70;
  const fontSizes = [];
  let underFloorPx = 0;
  let generatedTextNodes = 0;
  const checkFont = (el, cs, text, pseudo = '') => {
    const size = parseFloat(cs.fontSize);
    if (!Number.isFinite(size)) return;
    fontSizes.push(size);
    if (size >= fontFloorPx) return;
    underFloorPx++;
    const r = rectOf(el);
    const section = (sectionInfo.find((s) => r.y >= s.y - 2 && r.y < s.bottom) || {}).name || '';
    add(1, 'T-MIN-FONT', `计算字号 ${size}px < ${fontFloorPx}px：${text.trim().slice(0, 24)}`, el,
      { y: r.y, section, fontSizePx: size, pseudo });
  };

  // Find the unit that follows a numeric text node: a following text node, or an
  // inline element right after it, holding 1-3 non-digit characters.
  // Only immediate inline siblings count — walking up to block siblings would flag
  // layout pairs like a 168px section number next to a 72px title.
  const nextUnit = (node) => {
    const glyphBox = (target) => {
      if (target.nodeType === 3) {
        const t = target.nodeValue;
        const i = t.search(/\S/);
        if (i < 0) return null;
        const r = document.createRange();
        r.setStart(target, i);
        r.setEnd(target, Math.min(t.length, i + 2));
        const rr = r.getBoundingClientRect();
        return rr.height > 2 ? { top: rr.top + scrollY0, bottom: rr.bottom + scrollY0, text: t.trim().slice(0, 3) } : null;
      }
      const cs2 = getComputedStyle(target);
      if (!/^inline/.test(cs2.display)) return null; // block/flex/grid sibling: layout pair, not a unit
      const t = (target.textContent || '').trim();
      if (!t || t.length > 3 || /\d/.test(t)) return null;
      const r = document.createRange();
      r.selectNodeContents(target);
      const rr = r.getClientRects()[0];
      if (!rr || rr.height <= 2) return null;
      return { top: rr.top + scrollY0, bottom: rr.bottom + scrollY0, text: t };
    };

    let sib = node.nextSibling;
    while (sib && sib.nodeType === 3 && !sib.nodeValue.trim()) sib = sib.nextSibling;
    if (!sib) return null;
    if (sib.nodeType === 3) return /^\s*[^\d\s]/.test(sib.nodeValue) ? glyphBox(sib) : null;
    if (sib.nodeType === 1) return glyphBox(sib);
    return null;
  };

  // Two boxes share a line when their vertical extents overlap substantially.
  // Comparing tops alone misfires when font sizes differ and vertical-align is used.
  const sameLine = (a, b) => {
    const overlap = Math.min(a.bottom, b.bottom) - Math.max(a.top, b.top);
    const smaller = Math.min(a.bottom - a.top, b.bottom - b.top);
    return smaller > 0 && overlap / smaller > 0.5;
  };

  const lastLineChars = (node) => {
    const t = node.nodeValue;
    const r = document.createRange();
    const pts = [];
    for (let i = t.length - 1; i >= 0 && pts.length < 24; i--) {
      r.setStart(node, i);
      r.setEnd(node, i + 1);
      const rr = r.getBoundingClientRect();
      if (rr.height <= 2) continue;
      pts.unshift({ i, top: Math.round(rr.top + scrollY0), w: rr.width });
    }
    if (!pts.length) return null;
    const lastTop = pts[pts.length - 1].top;
    let count = 0;
    for (let k = pts.length - 1; k >= 0; k--) {
      if (pts[k].top === lastTop) count++;
      else break;
    }
    return { chars: count, sampled: pts.length };
  };

  nodes.forEach(({ node, el, cs, text, rects }) => {
    checkFont(el, cs, text);
    const fontSize = parseFloat(cs.fontSize) || 0;
    const parentSize = parseFloat(getComputedStyle(el.parentElement).fontSize) || fontSize;
    const trimmed = text.trim();
    const r0 = rectOf(el);
    const section = (sectionInfo.find((s) => r0.y >= s.y - 2 && r0.y < s.bottom) || {}).name || '';

    // horizontal overflow / clipped text
    if (r0.right > posterRect.right + 2 || r0.x < posterRect.x - 2) {
      add(1, 'T-OVERFLOW', `文字超出画布：${selOf(el)}`, el, { y: r0.y, section });
    }

    // giant whole sentence
    if (fontSize > 80 && trimmed.length > 12) {
      add(2, 'T-GIANT', `整句被放大到 ${Math.round(fontSize)}px（应只放大 1 个关键词）：${trimmed.slice(0, 18)}…`, el, { y: r0.y, section });
    }

    // widow / orphan tail: a wrapped line ending in 1 char (any length) or
    // 2 chars in body copy. Chinese typography forbids a lone last char.
    // fontSize cap 110 keeps hero keywords out; the 70px floor replaced the old 64.
    if (rects.length >= 2 && fontSize <= 110) {
      const li = lastLineChars(node);
      if (li && (li.chars <= 1 && trimmed.length >= 2 || li.chars === 2 && trimmed.length >= 8)) {
        add(2, 'T-WIDOW', `末行只剩 ${li.chars} 个字（孤字行）：${trimmed.slice(-12)}`, el, { y: rects[rects.length - 1].top, section });
      }
    }

    // inline keyword broken across lines
    if (rects.length > 1 && (el.tagName === 'SPAN' || el.tagName === 'EM' || el.tagName === 'STRONG' || el.tagName === 'B')) {
      const uniqueTops = new Set(rects.map((r) => r.top)).size;
      if (uniqueTops > 1 && (fontSize >= parentSize * 1.5 || fontSize >= 80)) {
        add(1, 'T-KEY-BREAK', `强调词被折成 ${uniqueTops} 行（需 display:inline-block 并留出空间）：${trimmed.slice(0, 16)}`, el, { y: r0.y, section });
      }
    }

    // number + unit split across lines
    if (/^[−\-+—]?\d+(\.\d+)?$/.test(trimmed) && trimmed.length <= 6) {
      const unit = nextUnit(node);
      if (unit) {
        const numLine = rects[0];
        const numBox = { top: numLine.top, bottom: numLine.top + fontSize * 1.3 };
        if (!sameLine(numBox, unit)) {
          add(1, 'T-UNIT-WRAP', `数字「${trimmed}」与单位「${unit.text}」被拆到两行（给数字+单位加 white-space:nowrap）`, el, { y: r0.y, section });
        }
      }
    }

    // contrast
    if (fontSize >= 16 && trimmed.length > 0) {
      const fg = parseColor(cs.color);
      if (fg) {
        const bg = bgOf(el);
        const ratio = contrast(fg, bg);
        const need = fontSize >= 32 || (fontSize >= 24 && Number(cs.fontWeight) >= 700) ? 3 : 4.5;
        if (ratio < need) {
          add(ratio < 2.2 ? 2 : 3, 'C-CONTRAST', `对比度 ${ratio.toFixed(2)}:1（需 ≥${need}）：${trimmed.slice(0, 14)}`, el, { y: r0.y, section });
        }
      }
    }
  });

  // Generated labels and counters are not DOM text nodes.
  for (const el of [poster, ...poster.querySelectorAll('*')]) {
    if (!visible(el)) continue;
    for (const pseudo of ['::before', '::after']) {
      const cs = getComputedStyle(el, pseudo);
      const content = cs.content.trim();
      if (!content || /^(none|normal|""|'')$/.test(content) || /^url\(/.test(content)) continue;
      if (cs.display === 'none' || cs.visibility !== 'visible' || Number(cs.opacity) <= 0) continue;
      generatedTextNodes++;
      checkFont(el, cs, content, pseudo);
    }
  }

  // ---------- fixed / sticky ----------
  const fixedEls = [...poster.querySelectorAll('*')].filter((el) => {
    const p = getComputedStyle(el).position;
    return (p === 'fixed' || p === 'sticky') && visible(el);
  });
  if (fixedEls.length) {
    add(2, 'L-FIXED', `存在 ${fixedEls.length} 个 fixed/sticky 元素，整页截图时会被重复渲染或错位`, fixedEls[0], { y: 0 });
  }

  // ---------- output ----------
  const sevOrder = { 1: 0, 2: 1, 3: 2 };
  issues.sort((a, b) => (sevOrder[a.sev] - sevOrder[b.sev]) || (a.y - b.y));
  const counts = { 1: 0, 2: 0, 3: 0 };
  issues.forEach((i) => counts[i.sev]++);

  return {
    page: { width: Math.round(posterRect.w), height: Math.round(pageHeight), scrollWidth: Math.round(pageWidth) },
    sections: sectionInfo.map((s) => ({ index: s.index, name: s.name, y: Math.round(s.y), h: Math.round(s.h), bottom: Math.round(s.bottom) })),
    counts,
    issues: issues.slice(0, 80),
    fontFloorPx,
    minFontPx: fontSizes.length ? Math.min(...fontSizes) : null,
    underFloorPx,
    generatedTextNodes,
    textNodes: nodes.length,
  };
})()
