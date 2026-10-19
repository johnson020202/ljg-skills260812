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
  sections = sections.filter(el => visible(el) && rectOf(el).h > 0);
  const sectionInfo = sections.map((el, i) => {
    const r = rectOf(el);
    const raw = el.getAttribute('data-name') ||
      (el.getAttribute('class') || '').trim().split(/\s+/).filter((c) => c && !/^(island|dark|light)$/.test(c)).join('-') ||
      el.tagName.toLowerCase();
    const safe = raw.replace(/[\\/\x00-\x1f\x7f<>:"|?*]/g, '-').slice(0, 80) || 'section';
    return { index: i, name: String(i + 1).padStart(2, '0') + '-' + safe, el, x: r.x, y: r.y, h: r.h, right: r.right, bottom: r.bottom, radius: parseFloat(getComputedStyle(el).borderTopLeftRadius) || 0 };
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
    const text = node.nodeValue;
    const first = text.search(/\S/);
    if (first < 0) return [];
    r.setStart(node, first);
    r.setEnd(node, text.trimEnd().length);
    return [...r.getClientRects()]
      .filter((rr) => rr.height > 0 && rr.width > 0)
      .map((rr) => ({ top: rr.top + scrollY0, bottom: rr.bottom + scrollY0, left: rr.left, right: rr.right, w: rr.width }));
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
  // Minimum singular value catches shrinking in either axis, including inherited
  // transforms, individual scale and zoom. Rotation alone keeps the same size.
  const visualScale = (el, pseudoStyle) => {
    let matrix = new DOMMatrix();
    let zoom = 1;
    const styles = [];
    if (pseudoStyle) styles.push(pseudoStyle);
    for (let e = el; e; e = e.parentElement) styles.push(getComputedStyle(e));
    for (const style of styles) {
      let local = style.transform === 'none' ? new DOMMatrix() : new DOMMatrix(style.transform);
      if (style.scale && style.scale !== 'none') {
        const values = style.scale.split(/\s+/).map(Number);
        local = local.scale(values[0], values[1] ?? values[0]);
      }
      matrix = local.multiply(matrix);
      zoom *= parseFloat(style.zoom) || 1;
    }
    const {a, b, c, d} = matrix;
    const trace = a*a + b*b + c*c + d*d;
    const determinant = (a*d - b*c) ** 2;
    return zoom * Math.sqrt(Math.max(0, (trace - Math.sqrt(Math.max(0, trace*trace - 4*determinant))) / 2));
  };
  const checkFont = (el, cs, text, pseudo = '') => {
    const size = parseFloat(cs.fontSize) * visualScale(el, pseudo ? cs : null);
    if (!Number.isFinite(size)) return;
    fontSizes.push(size);
    if (size >= fontFloorPx - 0.000001) return;
    underFloorPx++;
    const r = rectOf(el);
    const section = (sectionInfo.find((s) => r.y >= s.y - 2 && r.y < s.bottom) || {}).name || '';
    add(1, 'T-MIN-FONT', `可见字号 ${size}px < ${fontFloorPx}px：${text.trim().slice(0, 24)}`, el,
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

  // Group by formatting block, not text node: <strong> and trailing collapsed
  // whitespace must not hide the last character. No implicit large-title exemption.
  const blocks = new Map();
  const blockOf = (el) => {
    while (el !== poster && /^(inline|contents)$/.test(getComputedStyle(el).display)) el = el.parentElement;
    return el;
  };
  const clipOf = (el) => {
    const clip = { left: Math.max(0, posterRect.x), right: Math.min(innerWidth, posterRect.right), top: 0, bottom: pageHeight };
    for (let e = el; e; e = e.parentElement) {
      const style = getComputedStyle(e), r = rectOf(e);
      const sx = e.offsetWidth ? r.w / e.offsetWidth : 1;
      const sy = e.offsetHeight ? r.h / e.offsetHeight : 1;
      if (/^(hidden|clip|scroll|auto)$/.test(style.overflowX)) {
        clip.left = Math.max(clip.left, r.x + e.clientLeft * sx);
        clip.right = Math.min(clip.right, r.x + (e.clientLeft + e.clientWidth) * sx);
      }
      if (/^(hidden|clip|scroll|auto)$/.test(style.overflowY)) {
        clip.top = Math.max(clip.top, r.y + e.clientTop * sy);
        clip.bottom = Math.min(clip.bottom, r.y + (e.clientTop + e.clientHeight) * sy);
      }
    }
    return clip;
  };

  nodes.forEach(({ node, el, cs, text, rects }) => {
    checkFont(el, cs, text);
    const fontSize = parseFloat(cs.fontSize) || 0;
    const parentSize = parseFloat(getComputedStyle(el.parentElement).fontSize) || fontSize;
    const trimmed = text.trim();
    const r0 = rectOf(el);
    const section = (sectionInfo.find((s) => r0.y >= s.y - 2 && r0.y < s.bottom) || {}).name || '';

    const clip = clipOf(el);
    if (rects.some(r => r.right > clip.right + 2 || r.left < clip.left - 2 ||
                        r.top < clip.top - 2 || r.bottom > clip.bottom + 2)) {
      add(1, 'T-OVERFLOW', `文字被裁切或超出画布：${selOf(el)}`, el, { y: r0.y, section, clip });
    }
    const block = blockOf(el);
    if (!blocks.has(block)) blocks.set(block, []);
    blocks.get(block).push({ node, text, clip });

    // giant whole sentence
    if (fontSize > 80 && trimmed.length > 12) {
      add(2, 'T-GIANT', `整句被放大到 ${Math.round(fontSize)}px（应只放大 1 个关键词）：${trimmed.slice(0, 18)}…`, el, { y: r0.y, section });
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

  const segmenter = new Intl.Segmenter('zh', { granularity: 'grapheme' });
  for (const [block, entries] of blocks) {
    const lines = [];
    const vertical = getComputedStyle(block).writingMode.startsWith('vertical');
    const range = document.createRange();
    for (const {node, text, clip} of entries) {
      for (const {segment, index} of segmenter.segment(text)) {
        if (!segment.trim()) continue;
        range.setStart(node, index);
        range.setEnd(node, index + segment.length);
        const r = range.getBoundingClientRect();
        if (r.width <= 0 || r.height <= 0 || r.right <= clip.left || r.left >= clip.right ||
            r.bottom + scrollY0 <= clip.top || r.top + scrollY0 >= clip.bottom) continue;
        const box = vertical ? {top:r.left, bottom:r.right} : {top:r.top + scrollY0, bottom:r.bottom + scrollY0};
        let line = lines.find(l => sameLine(l, box));
        if (!line) { line = {...box, text: '', y:r.top + scrollY0}; lines.push(line); }
        line.text += segment;
      }
    }
    if (lines.length < 2) continue;
    const last = lines[lines.length - 1];
    const chars = [...segmenter.segment(last.text)].length;
    const text = entries.map(e => e.text.trim()).join('');
    const bodyCopy = !/^H[1-6]$/.test(block.tagName) && parseFloat(getComputedStyle(block).fontSize) <= 110;
    if (chars === 1 || (chars === 2 && text.length >= 8 && bodyCopy)) {
      const section = (sectionInfo.find(s => last.y >= s.y - 2 && last.y < s.bottom) || {}).name || '';
      add(2, 'T-WIDOW', `末行只剩 ${chars} 个字（孤字行）：${text.slice(-12)}`, block, {y:last.y, section});
    }
  }

  // Generated labels, native list markers and counters are not DOM text nodes.
  for (const el of [poster, ...poster.querySelectorAll('*')]) {
    if (!visible(el)) continue;
    for (const pseudo of ['::before', '::after', '::marker']) {
      const cs = getComputedStyle(el, pseudo);
      let content = cs.content.trim();
      if (pseudo === '::marker') {
        const style = getComputedStyle(el);
        if (style.display !== 'list-item') continue;
        if (content === 'normal' && style.listStyleType !== 'none') content = style.listStyleType;
      }
      if (!content || /^(none|normal|""|'')$/.test(content) || /^url\(/.test(content)) continue;
      if (cs.display === 'none' || cs.visibility !== 'visible' || Number(cs.opacity) <= 0) continue;
      generatedTextNodes++;
      checkFont(el, cs, content, pseudo);
    }
  }

  // Chapter identity repeats are local to an explicitly marked heading group,
  // not a ban on repeated numbers in maps, body data or lists.
  const chapterNumber = (raw) => {
    const value = raw.replace(/\s/g, '').replace(/^第/, '').replace(/章$/, '');
    if (/^\d+$/.test(value)) return Number(value);
    const digits = '零一二三四五六七八九';
    if (value === '十') return 10;
    if (/^[一二三四五六七八九]?十[一二三四五六七八九]?$/.test(value)) {
      const [a, b] = value.split('十');
      return (a ? digits.indexOf(a) : 1) * 10 + (b ? digits.indexOf(b) : 0);
    }
    return value.length === 1 && digits.includes(value) ? digits.indexOf(value) : null;
  };
  for (const head of poster.querySelectorAll('.sec-head,[data-chapter-heading]')) {
    if (!visible(head)) continue;
    const labels = [];
    const roles = [...head.querySelectorAll('.sec-num,[data-chapter-number],h1,h2,h3,h4,h5,h6,.kicker,[data-chapter-label]')];
    for (const role of roles.filter(el => !roles.some(other => other !== el && el.contains(other)))) {
      if (!visible(role)) continue;
      let text = nodes.filter(n => role.contains(n.el)).map(n => n.text).join('').trim();
      for (const pseudo of ['::before', '::after']) {
        const style = getComputedStyle(role, pseudo);
        if (style.display === 'none' || style.visibility !== 'visible' || Number(style.opacity) <= 0) continue;
        const literal = style.content.match(/^"([^"\\]*)"$/);
        if (literal) text = pseudo === '::before' ? literal[1] + text : text + literal[1];
      }
      const prefix = text.match(/^(?:第\s*)?([\d零一二三四五六七八九十]+)\s*章/);
      const value = role.matches('.sec-num,[data-chapter-number]') ? chapterNumber(text) :
        prefix ? chapterNumber(prefix[1]) : null;
      if (value !== null) labels.push(value);
    }
    if (new Set(labels).size < labels.length) {
      add(2, 'T-CHAPTER-DUP', '同一章标题组合重复编号；保留唯一大编号，副标签用主题词', head, {y:rectOf(head).y});
    }
  }

  // A font-family candidate scan is NOT proof of a rendered glyph: fallback,
  // aliases and future font versions still need manual inspection. Never rewrite
  // source quotations, titles or names automatically.
  const huiwenRiskCharacters = '让药继赞钟钥认讲论证铁';
  const huiwenCandidates = [];
  const huiwenRequested = (el, style) => /huiwen|汇文|匯文/i.test(style.fontFamily) ||
    !!el.closest('[data-glyph-review="huiwen"]');
  const addHuiwen = (el, style, text, pseudo = '') => {
    if (!huiwenRequested(el, style)) return false;
    const characters = [...new Set([...text].filter(c => huiwenRiskCharacters.includes(c)))].join('');
    if (characters) huiwenCandidates.push({selector:selOf(el), y:rectOf(el).y, pseudo, characters});
    return true;
  };
  let usesHuiwen = false;
  for (const {el, cs, text} of nodes) usesHuiwen = addHuiwen(el, cs, text) || usesHuiwen;
  for (const el of [poster, ...poster.querySelectorAll('*')]) {
    if (!visible(el)) continue;
    for (const pseudo of ['::before', '::after', '::marker']) {
      const style = getComputedStyle(el, pseudo), text = style.content;
      if (/^(none|normal|""|'')$/.test(text) || style.display === 'none' ||
          style.visibility !== 'visible' || Number(style.opacity) <= 0) continue;
      usesHuiwen = addHuiwen(el, style, text, pseudo) || usesHuiwen;
    }
  }
  const huiwenReview = {status:usesHuiwen ? 'manual-review-required' : 'not-requested',
    riskCharacters:huiwenRiskCharacters, candidates:huiwenCandidates};

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
    sections: sectionInfo.map((s) => ({ index: s.index, name: s.name, y: s.y, h: s.h, bottom: s.bottom })),
    counts,
    issues: issues.slice(0, 80),
    fontFloorPx,
    minFontPx: fontSizes.length ? Math.min(...fontSizes) : null,
    underFloorPx,
    generatedTextNodes,
    textNodes: nodes.length,
    huiwenReview,
  };
})()
