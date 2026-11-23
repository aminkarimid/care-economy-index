window.pdfText = async function(buf) {
  const u8 = new Uint8Array(buf); const L = new TextDecoder('latin1').decode(u8);
  const inflate = async (bytes) => { try { const ds = new DecompressionStream('deflate'); const w = ds.writable.getWriter(); w.write(bytes).catch(() => {}); w.close().catch(() => {}); const r = ds.readable.getReader(); const parts = []; let n = 0; for (;;) { const { done, value } = await r.read(); if (done) break; parts.push(value); n += value.length; } const o = new Uint8Array(n); let p = 0; for (const v of parts) { o.set(v, p); p += v.length; } return o; } catch (e) { return null; } };
  const objs = {};
  // top-level objects
  const re = /(\d+)\s+(\d+)\s+obj\b/g; let m;
  const starts = []; while ((m = re.exec(L))) starts.push([+m[1], m.index + m[0].length]);
  for (let k = 0; k < starts.length; k++) {
    const [num, st] = starts[k]; const end = L.indexOf('endobj', st); if (end < 0) continue;
    const body = L.slice(st, end); const si = body.search(/stream\r?\n/);
    if (si >= 0) {
      const dict = body.slice(0, si); const off = st + si + body.slice(si).match(/stream\r?\n/)[0].length;
      const lenM = dict.match(/\/Length\s+(\d+)(\s+\d+\s+R)?/);
      let len = lenM && !lenM[2] ? +lenM[1] : L.indexOf('endstream', off) - off;
      let raw = u8.slice(off, off + len);
      const data = /FlateDecode/.test(dict) ? await inflate(raw) : raw;
      objs[num] = { dict, data };
    } else objs[num] = { dict: body, data: null };
  }
  // object streams
  for (const o of Object.values(objs)) {
    if (!/\/Type\s*\/ObjStm/.test(o.dict) || !o.data) continue;
    const t = new TextDecoder('latin1').decode(o.data); const N = +o.dict.match(/\/N\s+(\d+)/)[1], F = +o.dict.match(/\/First\s+(\d+)/)[1];
    const hdr = t.slice(0, F).trim().split(/\s+/).map(Number);
    for (let i = 0; i < N; i++) { const num = hdr[2 * i], a = F + hdr[2 * i + 1], b = i + 1 < N ? F + hdr[2 * i + 3] : t.length; if (!objs[num]) objs[num] = { dict: t.slice(a, b), data: null }; }
  }
  const get = (ref) => objs[ref];
  const refOf = (s, key) => { const mm = s.match(new RegExp('/' + key + '\\s+(\\d+)\\s+\\d+\\s+R')); return mm ? +mm[1] : null; };
  const dictAt = (s, key) => {
    const i = s.indexOf('/' + key); if (i < 0) return null; let j = i + key.length + 1; while (/\s/.test(s[j])) j++;
    if (s.startsWith('<<', j)) { let d = 0; for (let k = j; k < s.length - 1; k++) { if (s.startsWith('<<', k)) { d++; k++; } else if (s.startsWith('>>', k)) { d--; k++; if (d === 0) return s.slice(j, k + 1); } } }
    const mm = s.slice(j).match(/^(\d+)\s+\d+\s+R/); return mm && objs[+mm[1]] ? objs[+mm[1]].dict : null; };
  const cmaps = {};
  const parseCMap = (t) => { const map = {}; let bytes = 1;
    const cs = t.match(/begincodespacerange\s*<([0-9A-Fa-f]+)>/); if (cs) bytes = cs[1].length / 2;
    for (const blk of t.matchAll(/beginbfchar([\s\S]*?)endbfchar/g)) for (const p of blk[1].matchAll(/<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>/g)) map[parseInt(p[1], 16)] = hexU(p[2]);
    for (const blk of t.matchAll(/beginbfrange([\s\S]*?)endbfrange/g)) for (const p of blk[1].matchAll(/<([0-9A-Fa-f]+)>\s*<([0-9A-Fa-f]+)>\s*(<([0-9A-Fa-f]+)>|\[([^\]]*)\])/g)) {
      const a = parseInt(p[1], 16), b = parseInt(p[2], 16);
      if (p[4]) { const base = parseInt(p[4], 16); for (let c = a; c <= b; c++) map[c] = String.fromCodePoint(base + (c - a)); }
      else { const arr = [...p[5].matchAll(/<([0-9A-Fa-f]+)>/g)].map(x => hexU(x[1])); for (let c = a; c <= b; c++) map[c] = arr[c - a] || ''; } }
    return { map, bytes }; };
  const hexU = (h) => { let s = ''; for (let i = 0; i < h.length; i += 4) s += String.fromCharCode(parseInt(h.slice(i, i + 4), 16)); return s; };
  const fontMap = (fd) => { const tu = refOf(fd, 'ToUnicode'); if (tu && objs[tu] && objs[tu].data) { if (!cmaps[tu]) cmaps[tu] = parseCMap(new TextDecoder('latin1').decode(objs[tu].data)); return { map: cmaps[tu].map, bytes: /\/Subtype\s*\/Type0/.test(fd) ? cmaps[tu].bytes : 1 }; } return null; };
  const pages = Object.entries(objs).filter(([n, o]) => /\/Type\s*\/Page\b/.test(o.dict)).map(([n, o]) => [+n, o]).sort((a, b) => a[0] - b[0]);
  // order pages via /Kids traversal from Root
  const order = []; const rootM = L.match(/\/Root\s+(\d+)\s+\d+\s+R/) || Object.values(objs).map(o => o.dict.match(/\/Root\s+(\d+)\s+\d+\s+R/)).find(Boolean);
  const walk = (n) => { const o = objs[n]; if (!o) return; if (/\/Type\s*\/Page\b/.test(o.dict)) { order.push(n); return; } const kids = o.dict.match(/\/Kids\s*\[([^\]]*)\]/); if (kids) for (const k of kids[1].matchAll(/(\d+)\s+\d+\s+R/g)) walk(+k[1]); };
  if (rootM) { const pagesRef = refOf(objs[+rootM[1]].dict, 'Pages'); walk(pagesRef); }
  const pageList = order.length ? order : pages.map(p => p[0]);
  const out = [];
  for (const pn of pageList) {
    const po = objs[pn]; let res = dictAt(po.dict, 'Resources'); let parent = refOf(po.dict, 'Parent');
    while (!res && parent && objs[parent]) { res = dictAt(objs[parent].dict, 'Resources'); parent = refOf(objs[parent].dict, 'Parent'); }
    const fontsD = res ? dictAt(res, 'Font') : null; const fonts = {};
    if (fontsD) for (const f of fontsD.matchAll(/\/([^\s/]+)\s+(\d+)\s+\d+\s+R/g)) fonts[f[1]] = objs[+f[2]] ? fontMap(objs[+f[2]].dict) : null;
    const cref = po.dict.match(/\/Contents\s*(\[([^\]]*)\]|(\d+)\s+\d+\s+R)/); let refs = [];
    if (cref) refs = cref[2] ? [...cref[2].matchAll(/(\d+)\s+\d+\s+R/g)].map(x => +x[1]) : [+cref[3]];
    const content = refs.map(r => objs[r] && objs[r].data ? new TextDecoder('latin1').decode(objs[r].data) : '').join('\n');
    // tokenize text operators
    let cur = null, lines = [], line = '', lastY = null; const toks = content.matchAll(/\/([^\s/\[\]()<>]+)\s+[\d.]+\s+Tf|\((?:\\.|[^\\)])*\)|<[0-9A-Fa-f\s]*>|\[|\]|-?[\d.]+|[A-Za-z'"*]+/g);
    const decodeStr = (tok) => { let bytes = [];
      if (tok[0] === '(') { const s = tok.slice(1, -1); for (let i = 0; i < s.length; i++) { let c = s[i]; if (c === '\\') { const n = s[++i]; if (/[0-7]/.test(n)) { let o = n; while (o.length < 3 && /[0-7]/.test(s[i + 1])) o += s[++i]; bytes.push(parseInt(o, 8)); } else bytes.push({ n: 10, r: 13, t: 9, b: 8, f: 12 }[n] ?? n.charCodeAt(0)); } else bytes.push(c.charCodeAt(0)); } }
      else { const h = tok.slice(1, -1).replace(/\s/g, ''); for (let i = 0; i < h.length; i += 2) bytes.push(parseInt(h.slice(i, i + 2).padEnd(2, '0'), 16)); }
      if (cur && cur.map) { let s = ''; for (let i = 0; i < bytes.length; i += cur.bytes) { let c = 0; for (let k = 0; k < cur.bytes; k++) c = c * 256 + (bytes[i + k] || 0); s += cur.map[c] ?? (cur.bytes === 1 ? String.fromCharCode(c) : ''); } return s; }
      return String.fromCharCode(...bytes); };
    const stack = []; let inArr = false, arr = '';
    for (const t of toks) {
      const tk = t[0];
      if (t[1]) { cur = fonts[t[1]] || null; continue; }
      if (tk === '[') { inArr = true; arr = ''; continue; }
      if (tk === ']') { inArr = false; stack.push({ str: arr }); continue; }
      if (tk[0] === '(' || tk[0] === '<') { const s = decodeStr(tk); if (inArr) arr += s; else stack.push({ str: s }); continue; }
      if (/^-?[\d.]+$/.test(tk)) { if (inArr) { if (+tk < -200) arr += ' '; } else stack.push({ num: +tk }); continue; }
      if (tk === 'Tj' || tk === 'TJ' || tk === "'" || tk === '"') { const x = stack.pop(); if (tk !== 'Tj' && tk !== 'TJ') { lines.push(line); line = ''; } line += (x && x.str) || ''; stack.length = 0; continue; }
      if (tk === 'Tm') { const y = stack[stack.length - 1]?.num; if (lastY !== null && y !== undefined && Math.abs(y - lastY) > 1) { lines.push(line); line = ''; } else if (line) line += ' '; if (y !== undefined) lastY = y; stack.length = 0; continue; }
      if (tk === 'Td' || tk === 'TD') { const ty = stack[stack.length - 1]?.num; if (ty && Math.abs(ty) > 1) { lines.push(line); line = ''; if (lastY !== null) lastY += ty; } else if (line) line += ' '; stack.length = 0; continue; }
      if (tk === 'T*') { lines.push(line); line = ''; continue; }
      if (tk === 'ET') { if (line) line += ' '; stack.length = 0; continue; }
      stack.length = 0;
    }
    lines.push(line); out.push('--- page ' + (out.length + 1) + ' ---\n' + lines.map(l => l.replace(/\s+/g, ' ').trim()).filter(Boolean).join('\n'));
  }
  return out.join('\n');
};
