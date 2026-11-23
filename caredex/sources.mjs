// CareDex data monitor: parsers that turn each primary source into the exact JSON the site embeds.
// Pure functions, no dependencies. Runs in Node 18+ and in a browser (used to test this file on each source's own site).

// ---------- zip and xlsx ----------
export async function unzip(buf) {
  const dv = new DataView(buf);
  let e = buf.byteLength - 22;
  while (dv.getUint32(e, true) !== 0x06054b50) e--;
  const n = dv.getUint16(e + 10, true);
  let p = dv.getUint32(e + 16, true);
  const files = {};
  for (let i = 0; i < n; i++) {
    const m = dv.getUint16(p + 10, true), cs = dv.getUint32(p + 20, true), fl = dv.getUint16(p + 28, true);
    const xl = dv.getUint16(p + 30, true), cl = dv.getUint16(p + 32, true), off = dv.getUint32(p + 42, true);
    const name = new TextDecoder().decode(new Uint8Array(buf, p + 46, fl));
    files[name] = { m, cs, off };
    p += 46 + fl + xl + cl;
  }
  const get = async (name) => {
    const f = files[name];
    if (!f) throw new Error(`zip entry not found: ${name}`);
    const lfl = dv.getUint16(f.off + 26, true), lxl = dv.getUint16(f.off + 28, true);
    const data = new Uint8Array(buf, f.off + 30 + lfl + lxl, f.cs);
    if (f.m === 0) return data.slice().buffer;
    const s = new Blob([data]).stream().pipeThrough(new DecompressionStream('deflate-raw'));
    return await new Response(s).arrayBuffer();
  };
  return { names: Object.keys(files), get };
}

const ENT = { amp: '&', lt: '<', gt: '>', quot: '"', apos: "'" };
const unxml = (s) => s.replace(/&(#x[0-9a-f]+|#\d+|amp|lt|gt|quot|apos);/gi, (_, k) =>
  k[0] === '#' ? String.fromCodePoint(k[1].toLowerCase() === 'x' ? parseInt(k.slice(2), 16) : parseInt(k.slice(1), 10)) : ENT[k]);
const attr = (tag, name) => { const m = tag.match(new RegExp(`\\s${name}="([^"]*)"`)); return m ? unxml(m[1]) : null; };
const texts = (xml) => [...xml.matchAll(/<t(?:\s[^>]*)?>([\s\S]*?)<\/t>/g)].map(m => unxml(m[1])).join('');

export async function xlsxBook(buf) {
  const z = await unzip(buf);
  const dec = async (n) => new TextDecoder().decode(await z.get(n));
  const strs = z.names.includes('xl/sharedStrings.xml')
    ? [...(await dec('xl/sharedStrings.xml')).matchAll(/<si>([\s\S]*?)<\/si>/g)].map(m => texts(m[1]))
    : [];
  const wb = await dec('xl/workbook.xml');
  const rels = await dec('xl/_rels/workbook.xml.rels');
  const relMap = Object.fromEntries([...rels.matchAll(/<Relationship\s[^>]*>/g)].map(m => [attr(m[0], 'Id'), attr(m[0], 'Target')]));
  const sheets = [...wb.matchAll(/<sheet\s[^>]*>/g)].map(m => ({
    name: attr(m[0], 'name'),
    target: 'xl/' + relMap[attr(m[0], 'r:id')].replace(/^\/?xl\//, ''),
  }));
  const read = async (name) => {
    const sh = name === undefined ? sheets[0] : sheets.find(s => s.name === name);
    if (!sh) throw new Error(`sheet not found: ${name}`);
    const xml = await dec(sh.target);
    return [...xml.matchAll(/<row[\s>][\s\S]*?<\/row>|<row\s[^>]*\/>/g)].map(rm => {
      const o = {};
      for (const cm of rm[0].matchAll(/<c\s([^>]*?)(?:\/>|>([\s\S]*?)<\/c>)/g)) {
        const tag = ' ' + cm[1];
        const col = attr(tag, 'r').replace(/\d+/g, '');
        const inner = cm[2] || '';
        const v = inner.match(/<v>([\s\S]*?)<\/v>/);
        let val = v ? unxml(v[1]) : texts(inner);
        if (attr(tag, 't') === 's') val = strs[+val];
        o[col] = val;
      }
      return o;
    });
  };
  return { sheets, read };
}

// ---------- A1: CMS NHE Table 23 (from nhe-tables.zip) ----------
export async function cmsHomeHealth(nheTablesZip) {
  const z = await unzip(nheTablesZip);
  const name = z.names.find(n => /^Table 23 /.test(n));
  const b = await xlsxBook(await z.get(name));
  const rows = await b.read();
  const yr = rows[1];
  const ycols = Object.entries(yr).filter(([, v]) => /^20(1[3-9]|2\d)$/.test(String(v).trim())).map(([k, v]) => [k, String(v).trim()]);
  const want = { 'National Health Expenditures': 'nhe', 'Home Health Care': 'homeHealth', 'Other Health, Residential, and Personal Care': 'otherHRPC' };
  const data = { nominal: {}, real: {} };
  let section = '';
  for (const r of rows) {
    const all = Object.values(r).join(' ');
    const lab = String(Object.values(r)[0] || '').trim();
    if (/Nominal Dollars \(billions\)/.test(all)) section = 'nominal';
    else if (/Real Dollars \(2017 \$, billions\)/.test(all)) section = 'real';
    else if (/Price Index|Average Annual Growth|Table 23/.test(all)) section = '';
    if (section && want[lab] && !data[section][want[lab]]) data[section][want[lab]] = Object.fromEntries(ycols.map(([k, y]) => [y, +r[k]]));
  }
  return JSON.stringify(data);
}

// ---------- A2: BLS Employment Projections Table 1.4 (occupation.xlsx) ----------
export async function epMostJobGrowth(occupationXlsx) {
  const b = await xlsxBook(occupationXlsx);
  const t = await b.read('Table 1.4');
  const r1 = (v) => Math.round(+v * 10) / 10;
  const rows = t.slice(2).filter(r => /^\d\d-\d{4}$/.test(String(r.B || ''))).slice(0, 11)
    .map(r => ({ title: String(r.A).trim(), code: r.B, emp2025: r1(r.C), emp2035: r1(r.D), change: r1(r.E), pct: r1(r.F) }));
  return JSON.stringify(rows);
}

// ---------- BLS Employment Projections Table 1.2: one occupation (aides) ----------
export async function epOccupation(occupationXlsx, code = '31-1120') {
  const b = await xlsxBook(occupationXlsx);
  const t = await b.read('Table 1.2');
  const r = t.find(r => r.B === code);
  if (!r) throw new Error(`occupation ${code} not in Table 1.2`);
  const r1 = (v) => Math.round(+v * 10) / 10;
  return { emp2025: r1(r.D), emp2035: r1(r.E), change: r1(r.H), pct: r1(r.I), openings: r1(r.K), header: [t[1].D, t[1].E, t[1].H, t[1].I, t[1].K].join(' | ') };
}

// ---------- A3: Cooper Center age and sex workbook ----------
export async function cooperAging(ageSexXlsx) {
  const bk = await xlsxBook(ageSexXlsx);
  const calc = async (sheet) => {
    const rows = await bk.read(sheet);
    const hdr = rows[3];
    const ageCols = Object.entries(hdr).filter(([, v]) => /^(65|70|75|80|85)/.test(String(v))).map(([k]) => k);
    const res = {};
    rows.slice(4).filter(r => r.C === 'Total' && r.A).forEach(r => {
      const tot = +r.D;
      const o = ageCols.reduce((s, k) => s + +r[k], 0);
      res[String(r.A).padStart(2, '0')] = [r.B, Math.round(o / tot * 10000) / 100];
    });
    return res;
  };
  const a = await calc('2020'), b = await calc('2030');
  return JSON.stringify(Object.keys(a).sort().map(f => ({ fips: f, name: a[f][0], s2020: a[f][1], s2030: b[f][1] })));
}

// ---------- A4: BLS OEWS national files, median hourly wage ----------
export async function oewsNationalRows(natZip) {
  const z = await unzip(natZip);
  const name = z.names.find(k => /national.*\.xlsx$/i.test(k));
  const b = await xlsxBook(await z.get(name));
  const rows = await b.read();
  const idx = Object.fromEntries(Object.entries(rows[0]).map(([k, v]) => [String(v).toUpperCase(), k]));
  return { rows, idx };
}
export function oewsMedians(year, { rows, idx }) {
  const g = idx.O_GROUP || idx.OCC_GROUP;
  const pick = (code) => {
    const r = rows.find(r => r[idx.OCC_CODE] === code && ['detailed', 'total', 'broad'].includes(r[g]));
    return r ? Math.round(+r[idx.H_MEDIAN] * 100) / 100 : null;
  };
  const o = { all: pick('00-0000') };
  if (year <= 2018) { o.hha = pick('31-1011'); o.pca = pick('39-9021'); } else { o.aides = pick('31-1120'); }
  return o;
}

// ---------- CPI-U, not seasonally adjusted, May of each year (FRED CPIAUCNS = BLS CUUR0000SA0) ----------
export function cpiMay(fredCsv, from = 2014, to = 2025) {
  const out = {};
  for (const line of fredCsv.trim().split('\n').slice(1)) {
    const [d, v] = line.split(',');
    const y = +d.slice(0, 4);
    if (d.slice(5, 7) === '05' && y >= from && y <= to) out[String(y)] = +v;
  }
  return JSON.stringify(out);
}

// ---------- A5: KFF Figure 2 data (Datawrapper WNQfV dataset.csv) ----------
export function kffLtss(datasetCsv) {
  const L = datasetCsv.trim().split('\n').map(l => l.split('\t'));
  const keys = { 'Medicaid': 'medicaid', 'Out of Pocket': 'outOfPocket', 'Other Payers': 'otherPayers' };
  const d = {};
  L.slice(1).forEach(r => { d[keys[r[0]]] = { institutional: +r[2], hcbs: +r[3] }; });
  return JSON.stringify(d);
}

// ---------- OEWS national, May 2025: values on the Overview and wage-comparison chart ----------
export function oewsNationalDetail({ rows, idx }, codes) {
  const g = idx.O_GROUP || idx.OCC_GROUP;
  const num = (v) => +v;
  const out = codes.map(code => {
    const r = rows.find(r => r[idx.OCC_CODE] === code && ['detailed', 'total', 'broad'].includes(r[g]));
    return { soc: code, employment: num(r[idx.TOT_EMP]), p10: num(r[idx.H_PCT10]), median: num(r[idx.H_MEDIAN]), mean: num(r[idx.H_MEAN]), p90: num(r[idx.H_PCT90]), annualMedian: num(r[idx.A_MEDIAN]) };
  });
  return JSON.stringify(out);
}

// ---------- OEWS state file (oesm25st.zip): aides employed and median wage by state ----------
export async function oewsStates(stZip, occ = '31-1120') {
  const z = await unzip(stZip);
  const { rows, idx } = await oewsStateRows(stZip, z);
  const out = {};
  rows.slice(1).filter(r => r[idx.OCC_CODE] === occ).forEach(r => {
    out[r[idx.PRIM_STATE]] = { aides: +r[idx.TOT_EMP], medianWage: +r[idx.H_MEDIAN] };
  });
  return out;
}


// ---------- OEWS state file rows. Skips Excel lock files (~$...) and folder entries in the zip. ----------
export async function oewsStateRows(stZip, z) {
  z = z || await unzip(stZip);
  const name = z.names.find(k => /(^|\/)state_M20\d\d_dl\.xlsx$/i.test(k) && !k.includes('~$'));
  if (!name) throw new Error('no state_M20YY_dl.xlsx in the zip');
  const rows = await (await xlsxBook(await z.get(name))).read();
  const idx = Object.fromEntries(Object.entries(rows[0]).map(([k, v]) => [String(v).toUpperCase(), k]));
  return { rows, idx };
}

// ---------- Pay layer (payData.ts): competing jobs, minimum wage, price levels ----------
export const COMPETING_SOC = ['35-2021', '35-3023', '37-2011', '41-2011', '53-7062', '53-7065'];
// {ST: {soc: hourly median}} for the aide code and the six competing codes. Non-numeric cells throw.
export async function oewsStateMedians(stZip, occs = ['31-1120', ...COMPETING_SOC]) {
  const { rows, idx } = await oewsStateRows(stZip);
  const st = idx.PRIM_STATE || idx.ST;
  const out = {};
  for (const r of rows.slice(1)) {
    if (!occs.includes(r[idx.OCC_CODE])) continue;
    const v = Number(r[idx.H_MEDIAN]);
    if (!Number.isFinite(v)) throw new Error(`non-numeric median ${r[idx.H_MEDIAN]} for ${r[st]} ${r[idx.OCC_CODE]}`);
    (out[r[st]] || (out[r[st]] = {}))[r[idx.OCC_CODE]] = v;
  }
  return out;
}
// DOL "Changes in Basic Minimum Wages" page: {state name: cell text} for one year column.
export function dolMinWageColumn(html, year = '2024') {
  const clean = (t) => t.replace(/<[^>]+>/g, '').replace(/&nbsp;/g, ' ').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim();
  for (const t of html.match(/<table[\s\S]*?<\/table>/gi) || []) {
    const rows = (t.match(/<tr[\s\S]*?<\/tr>/gi) || []).map(r => (r.match(/<t[hd][\s\S]*?<\/t[hd]>/gi) || []).map(clean));
    const head = rows.find(r => r.some(c => c.replace(/\s*\(.*\)$/, '') === year));
    if (!head) continue;
    const col = head.findIndex(c => c.replace(/\s*\(.*\)$/, '') === year);
    const out = {};
    for (const r of rows) if (r.length === head.length && r !== head && r[0]) out[r[0]] = r[col];
    return out;
  }
  throw new Error(`no table with a ${year} column`);
}
// BEA SARPP zip: {fips2: {year: RPP all items}}
export async function beaRpp(sarppZip) {
  const z = await unzip(sarppZip);
  const name = z.names.find(k => /^SARPP_STATE_2008_\d{4}\.csv$/i.test(k));
  if (!name) throw new Error('SARPP_STATE csv not in zip');
  const lines = new TextDecoder().decode(await z.get(name)).split(/\r?\n/).filter(Boolean);
  const hdr = lines[0].split(',');
  const parse = (l) => { const o = []; let c = '', q = false; for (const ch of l) { if (ch === '"') q = !q; else if (ch === ',' && !q) { o.push(c.trim()); c = ''; } else c += ch; } o.push(c.trim()); return o; };
  const out = {};
  for (const l of lines.slice(1)) {
    const c = parse(l);
    if (c[4] !== '1' || !/^\d{2}000$/.test(c[0]) || c[0] === '00000') continue;
    out[c[0].slice(0, 2)] = Object.fromEntries(hdr.slice(8).map((y, i) => [y, Number(c[8 + i])]));
  }
  return out;
}
const r2 = (x) => Math.round((x + 1e-9) * 100) / 100;
const med = (a) => { const s = [...a].sort((x, y) => x - y), m = s.length >> 1; return s.length % 2 ? s[m] : (s[m - 1] + s[m]) / 2; };
// Rebuild PAY_RAW rows. states: [{code, name, fips}]; dol: dolMinWageColumn output; rpp: beaRpp output.
export function buildPay(m25, m24, dol, rpp, states, rppYear = '2024') {
  return [...states].sort((a, b) => (a.code < b.code ? -1 : 1)).map(({ code, name, fips }) => {
    const a = m25[code], b = m24[code];
    if (!a || !b) throw new Error(`OEWS state medians missing for ${code}`);
    const comp = COMPETING_SOC.map(s => { if (a[s] === undefined) throw new Error(`${code} ${s} missing`); return a[s]; });
    const cm = r2(med(comp));
    const listed = dol[name];
    if (listed === undefined) throw new Error(`DOL table has no row for ${name}`);
    const m = listed.match(/^\$?(\d+\.\d+)(?:[([].*)?$/);
    const mw = Math.max(m ? Number(m[1]) : 7.25, 7.25);
    const rp = rpp[fips] && rpp[fips][rppYear];
    if (!rp) throw new Error(`RPP ${rppYear} missing for ${fips}`);
    const a25 = a['31-1120'], a24 = b['31-1120'];
    return [code, a25, ...comp, cm, r2(a25 / med(comp)), a24, listed, mw, r2(a24 - mw), rp, r2(a25 / (rp / 100))];
  });
}


// ---------- Need layer (needData.ts): ACS 1-year table-based summary file B18107, B18106 ----------
// shells: ACS<YYYY>1YR_Table_Shells.txt; b18107/b18106: acsdt1y<YYYY>-b1810x.dat. Returns {fips2: {ild:[e,moe], pop18:[e,moe], sc18:[e,moe]}}.
export function acsDisability(shells, b18107, b18106) {
  const sh = shells.split(/\r?\n/);
  const labels = (t) => { let age = ''; return sh.filter(l => l.startsWith(t + '|')).map(l => l.split('|')).map(r => { if (+r[2] === 2) age = r[4]; return [r[3], +r[2], r[4], age]; }); };
  const w07 = labels('B18107').filter(r => r[1] === 3 && /^With/.test(r[2])).map(r => r[0]);
  const w06 = labels('B18106').filter(r => r[1] === 3 && /^With/.test(r[2]) && !/5 to 17/.test(r[3])).map(r => r[0]);
  if (w07.length !== 8 || w06.length !== 8) throw new Error(`unexpected table shells (${w07.length}, ${w06.length})`);
  const parse = (txt) => { const L = txt.trim().split(/\r?\n/); const h = L[0].split('|'); return { h, rows: L.slice(1).map(l => l.split('|')).filter(c => /^0400000US\d\d$/.test(c[0]) && c[0] !== '0400000US72') }; };
  const sum = (d, ids, c) => { let e = 0, m2 = 0; for (const id of ids) { e += +c[d.h.indexOf(id.replace('_', '_E'))]; m2 += (+c[d.h.indexOf(id.replace('_', '_M'))]) ** 2; } return [e, Math.round(Math.sqrt(m2))]; };
  const a = parse(b18107), b = parse(b18106), out = {};
  for (const c of a.rows) out[c[0].slice(-2)] = { ild: sum(a, w07, c), pop18: [+c[a.h.indexOf('B18107_E001')], +c[a.h.indexOf('B18107_M001')]] };
  for (const c of b.rows) { const k = c[0].slice(-2); if (out[k]) out[k].sc18 = sum(b, w06, c); }
  return out;
}
const r1 = (x) => Math.round((x + 1e-9) * 10) / 10;
// Rebuild NEED_RAW rows (ACS part and KFF part). kff: rows [name, screens, seniorsCell, totalCell] as printed by KFF.
export function buildNeed(acs, kff, states) {
  const byName = Object.fromEntries(kff.map(r => [r[0], r]));
  return [...states].sort((a, b) => (a.code < b.code ? -1 : 1)).map(s => {
    const a = acs[s.fips], k = byName[s.name];
    if (!a || !a.sc18) throw new Error(`ACS rows missing for ${s.fips}`);
    if (!k) throw new Error(`KFF row missing for ${s.name}`);
    const [ild, ildm] = a.ild, [sc, scm] = a.sc18, [p, pm] = a.pop18;
    return [s.code, ild, ildm, sc, scm, p, pm, r1(ild / p * 100), r1(s.aides / ild * 1000), r1(s.aides * 1000 * ildm / ild ** 2), r1(s.aides / sc * 1000), k[1], Number(String(k[3]).replace(/,/g, '')), k[2]];
  });
}


// ---------- Turnover layer (qwiData.ts): LEHD QWI state files ----------
// rows: arrays [year, quarter, industry, EmpS, HirA, Sep, TurnOvrS, sTurnOvrS, EarnS, sEarnS, sEmpS] for industries 6216, 6241, 00 (race A0, ethnicity A0).
export const QWI_FIELDS = ['year', 'quarter', 'industry', 'EmpS', 'HirA', 'Sep', 'TurnOvrS', 'sTurnOvrS', 'EarnS', 'sEarnS', 'sEmpS'];
// lines: any (async) iterable of CSV lines from a qwi_<st>_rh_f_gs_*_op_u.csv file, header first.
export async function qwiPick(lines, industries) {
  let h = null, ix, iInd, iY, iR, iE; const out = [];
  for await (const l of lines) {
    if (!l) continue;
    if (!h) { h = l.split(','); ix = QWI_FIELDS.map(n => h.indexOf(n)); iInd = h.indexOf('industry'); iY = h.indexOf('year'); iR = h.indexOf('race'); iE = h.indexOf('ethnicity'); continue; }
    if (!l.includes(',A0,A0,')) continue;
    const c = l.split(','); if (c[iR] !== 'A0' || c[iE] !== 'A0' || !industries.includes(c[iInd]) || +c[iY] < 2019) continue;
    out.push(ix.map(i => c[i]));
  }
  return out;
}
const QOK = (f) => ['1', '6', '10'].includes(f);
const r3 = (x) => Math.round((x + 1e-12) * 1000) / 1000;
// byState: {st (lower case): rows}. Returns {out, tr} as in qwiData.ts (QWI_STATE, QWI_TREND).
export function buildQwi(byState, order, trendExclude = ['ak', 'mi'], trendTo = '2025Q2') {
  const out = [], trend = {};
  for (const st of order) {
    const rows = (byState[st] || []).slice().sort((a, b) => (a[2] + a[0] + a[1]).localeCompare(b[2] + b[0] + b[1]));
    const by = {}; for (const r of rows) (by[r[0] + 'Q' + r[1]] = by[r[0] + 'Q' + r[1]] || {})[r[2]] = r;
    const good = Object.keys(by).sort().filter(q => ['6216', '6241', '00'].every(i => by[q][i] && by[q][i][6] !== '' && QOK(by[q][i][7])));
    if (!trendExclude.includes(st)) for (const r of rows) { const q = r[0] + 'Q' + r[1]; if (q < '2019Q1' || q > trendTo || r[6] === '' || !QOK(r[7]) || !(+r[3] > 0)) continue; const t = trend[q] = trend[q] || {}; t[r[2] + 'w'] = (t[r[2] + 'w'] || 0) + (+r[3]); t[r[2] + 's'] = (t[r[2] + 's'] || 0) + (+r[3]) * (+r[6]); t[r[2] + 'n'] = (t[r[2] + 'n'] || 0) + 1; }
    const last4 = good.slice(-4);
    if (!(last4.length === 4 && last4[3] >= '2025Q1')) { out.push([st.toUpperCase(), null]); continue; }
    const avg = (i, f, fl) => { const v = last4.map(q => by[q][i]).filter(r => r[f] !== '' && (fl === undefined || QOK(r[fl]))).map(r => +r[f]); return v.length === 4 ? v.reduce((a, b) => a + b, 0) / 4 : null; };
    const t16 = r3(avg('6216', 6, 7)), t41 = r3(avg('6241', 6, 7)), t00 = r3(avg('00', 6, 7));
    const rd = (v) => (v === null ? null : Math.round(v));
    out.push([st.toUpperCase(), last4[0] + '-' + last4[3], t16, t41, t00, Math.round(t16 / t00 * 100) / 100, Math.round(t41 / t00 * 100) / 100,
      rd(avg('6216', 8, 9)), rd(avg('6241', 8, 9)), rd(avg('00', 8, 9)), rd(avg('6216', 3)), rd(avg('6241', 3))]);
  }
  const tr = Object.keys(trend).sort().map(q => { const t = trend[q]; return [q, t['6216n'], t['6241n'], t['00n'], r3(t['6216s'] / t['6216w']), r3(t['6241s'] / t['6241w']), r3(t['00s'] / t['00w'])]; });
  return { out, tr };
}

// Annual stable-job turnover by state (W5): the mean of the four quarterly TurnOvrS values of each calendar year,
// for 6216, 6241 and all industries, using only cells with clean flags (1, 6, 10). A year with any quarter missing or flagged is null.
// Returns [[ST, [[year, t6216, t6241, t00], ...]], ...] in `order`, values to 3 dp.
export function qwiAnnual(byState, order, from = 2019, to = 2024) {
  return order.map(st => {
    const by = {}; for (const r of byState[st] || []) (by[r[0] + 'Q' + r[1]] = by[r[0] + 'Q' + r[1]] || {})[r[2]] = r;
    const yr = (y, i) => { const v = [1, 2, 3, 4].map(q => by[y + 'Q' + q] && by[y + 'Q' + q][i]).filter(r => r && r[6] !== '' && QOK(r[7])).map(r => +r[6]); return v.length === 4 ? r3(v.reduce((a, b) => a + b, 0) / 4) : null; };
    const ys = []; for (let y = from; y <= to; y++) ys.push([y, yr(y, '6216'), yr(y, '6241'), yr(y, '00')]);
    return [st.toUpperCase(), ys];
  });
}

// ---------- State trends (W5): OEWS state files May 2019 to May 2025, aides [employment, hourly median] ----------
// rows/idx: output of oewsStateRows for one year's oesmYYst.zip. states: [{code, fips}]. Files before 2020 lack PRIM_STATE, so AREA (state FIPS) is mapped to the postal code.
export function oewsStateYear({ rows, idx }, states, occ = '31-1120') {
  const byFips = Object.fromEntries(states.map(s => [s.fips, s.code]));
  const out = {};
  rows.slice(1).filter(r => String(r[idx.OCC_CODE]) === occ).forEach(r => {
    const code = idx.PRIM_STATE !== undefined && r[idx.PRIM_STATE] ? r[idx.PRIM_STATE] : byFips[String(r[idx.AREA]).padStart(2, '0')];
    if (code && states.some(s => s.code === code)) out[code] = [+r[idx.TOT_EMP], +r[idx.H_MEDIAN]];
  });
  return out;
}
// series: {year: {code: [emp, median]}} (2019..2025); cpi: {year: CPI-U May} (cpiMay output); qwiAnn: qwiAnnual output.
// Row per state, in states order: [code, [[year, employment, median, median in May-2025 dollars, TurnOvrS 6216, 6241, all], ...]].
// Real median = median x CPI(May 2025) / CPI(May year), 2 dp. QWI values are calendar-year means (null for 2025 and for unclean years).
export function buildTrends(series, cpi, qwiAnn, states, from = 2019, to = 2025) {
  const q = Object.fromEntries(qwiAnn.map(([st, ys]) => [st, Object.fromEntries(ys.map(y => [y[0], y.slice(1)]))]));
  const r2 = (x) => Math.round((x + 1e-9) * 100) / 100;
  return states.map(({ code }) => {
    const ys = [];
    for (let y = from; y <= to; y++) {
      const o = series[y] && series[y][code];
      if (!o) throw new Error(`OEWS ${y} has no row for ${code}`);
      const t = (q[code] && q[code][y]) || [null, null, null];
      ys.push([y, o[0], o[1], r2(o[1] * cpi[to] / cpi[y]), ...t]);
    }
    return [code, ys];
  });
}

// ---------- Market size (W6) ----------
// County Business Patterns state or US text file (cbpYYst.txt / cbpYYus.txt inside the zip), all legal forms (lfo "-").
// Returns rows of the named fields for the given 6-digit NAICS codes; numeric fields as numbers, flags and codes as strings.
export function cbpRows(txt, naics, fields) {
  const L = txt.split(/\r?\n/); const h = L[0].split(',').map(x => x.replace(/"/g, '').toLowerCase());
  const ix = fields.map(f => { const i = h.indexOf(f); if (i < 0) throw new Error(`CBP field ${f} missing`); return i; });
  const iN = h.indexOf('naics'), iL = h.indexOf('lfo');
  const text = new Set(['fipstate', 'naics', 'lfo', 'emp_nf', 'ap_nf', 'qp1_nf']);
  return L.slice(1).filter(Boolean).map(l => l.split(',').map(x => x.replace(/"/g, ''))).filter(c => naics.includes(c[iN]) && c[iL] === '-')
    .map(c => ix.map((i, k) => (text.has(fields[k]) ? c[i] : +c[i])));
}
// BLS National Employment Matrix page for one occupation (data.bls.gov/projections/nationalMatrix?queryParams=31-1120&ioType=o):
// [code, title, employment 2025 (thousands), projected 2035 (thousands)] for the given industry codes, in page order.
export function epMatrixRows(html, codes) {
  const out = [];
  for (const tr of html.split(/<tr[\s>]/i).slice(1)) {
    const cells = [...tr.split(/<\/tr>/i)[0].matchAll(/<t[dh][^>]*>([\s\S]*?)<\/t[dh]>/gi)].map(m => m[1].replace(/<[^>]+>/g, '').replace(/&amp;/g, '&').replace(/\s+/g, ' ').trim());
    if (cells.length > 6 && codes.includes(cells[1])) out.push([cells[1], cells[0], +cells[3].replace(/,/g, ''), +cells[6].replace(/,/g, '')]);
  }
  return out;
}
// ACS table-based summary file (.dat, pipe-delimited): the named columns for rows whose GEO_ID starts with a prefix, values as printed.
export function acsRows(dat, cols, geoPrefix = '0100000US') {
  const L = dat.split(/\r?\n/); const h = L[0].split('|'); const ix = cols.map(c => { const i = h.indexOf(c); if (i < 0) throw new Error(`ACS column ${c} missing`); return i; });
  return L.slice(1).filter(l => l.startsWith(geoPrefix)).map(l => { const c = l.split('|'); return [c[0], ...ix.map(i => c[i])]; });
}
// The market object embedded in marketData.ts (MARKET_JSON).
// oewsAides: May 2025 national aides employment (site_national.json). ep: epMatrixRows output. acs: acsRows output for B24114 E/M 001, 244, 245.
// cbpSt: cbpRows(state file, ['621610','624120'], ['fipstate','naics','emp_nf','emp','est']); cbpUs: cbpRows(US file, same NAICS, ['naics','emp_nf','emp','est','n<5','n5_9','n10_19','n20_49','n50_99','n100_249','n250_499','n500_999','n1000']).
export function buildMarket(oewsAides, ep, acs, cbpSt, cbpUs, states) {
  const e = Object.fromEntries(ep.map(r => [r[0], Math.round(r[2] * 1000)]));
  const a = acs[0].slice(1).map(Number);
  const moe = Math.round(Math.sqrt(a[3] ** 2 + a[5] ** 2));
  const byF = {}; for (const r of cbpSt) (byF[r[0]] = byF[r[0]] || {})[r[1]] = r;
  const r1 = (x) => Math.round(x * 10) / 10;
  const st = states.map(({ code, fips }) => {
    const h = byF[fips] && byF[fips]['621610'], s = byF[fips] && byF[fips]['624120'];
    if (!h || !s) throw new Error(`CBP rows missing for ${fips}`);
    return [code, h[4], h[3], h[2], r1(h[3] / h[4]), s[4], s[3], s[2], r1(s[3] / s[4])];
  });
  const us = cbpUs.map(r => ({ naics: r[0], emp: r[2], empFlag: r[1], est: r[3], perEst: r1(r[2] / r[3]), sizes: r.slice(4), under20: r1((r[4] + r[5] + r[6]) / r[3] * 100) }));
  return {
    counts: {
      oews2025: oewsAides,
      ep2025: { total: e.TE1000, wageSalary: e.TE1200, selfEmployed: e.TE1100, privateHouseholds: e['814000'], homeHealthCare: e['621600'], elderlyDisabled: e['624120'] },
      acs2025: { homeHealthAides: [a[2], a[3]], personalCareAides: [a[4], a[5]], total: [a[2] + a[4], moe], allOccupations: [a[0], a[1]] },
    },
    cbp2023: { us, sizeClasses: ['<5', '5-9', '10-19', '20-49', '50-99', '100-249', '250-499', '500-999', '1000+'], stateFields: ['code', 'est621610', 'emp621610', 'flag621610', 'perEst621610', 'est624120', 'emp624120', 'flag624120', 'perEst624120'], state: st },
  };
}

// ---------- Census Vintage 2025 civilian population by single year of age (sc-est2025-agesex-civ.csv) ----------
export function censusCivPop(csv, year = 2025) {
  const lines = csv.trim().split(/\r?\n/);
  const h = lines[0].split(',');
  const ix = (n) => h.indexOf(n);
  const out = {};
  for (const l of lines.slice(1)) {
    const c = l.split(',');
    if (c[ix('SEX')] !== '0') continue;
    const fips = c[ix('STATE')].padStart(2, '0'); // '00' is the United States
    const age = +c[ix('AGE')];
    const v = +c[ix(`POPEST${year}_CIV`)];
    const o = out[fips] || (out[fips] = { total: 0, pop65: 0, allAges: null });
    if (age === 999) o.allAges = v; else { o.total += v; if (age >= 65) o.pop65 += v; }
  }
  return out;
}

// ---------- Derived site values: states and national ----------
// Same rounding as the site build: Math.round(x * 10) / 10.
const round1 = (x) => Math.round(x * 10) / 10;

// oewsSt: output of oewsStates; census: output of censusCivPop; list: [{code, fips}] in site order.
export function buildStates(oewsSt, census, list) {
  return list.map(({ code, fips }) => {
    const o = oewsSt[code], c = census[fips];
    if (!o) throw new Error(`OEWS state file has no row for ${code}`);
    if (!c) throw new Error(`Census file has no row for FIPS ${fips}`);
    return {
      code, fips, pop2025: c.allAges, pop65: c.pop65, share65: round1(c.pop65 / c.allAges * 100),
      aides: o.aides, medianWage: o.medianWage, aidesPer1000_65: round1(o.aides / c.pop65 * 1000),
    };
  });
}

// natDetail: parsed output of oewsNationalDetail (May 2025); ep: output of epOccupation; census: censusCivPop output.
export function buildNational(natDetail, ep, census) {
  const aides = natDetail.find(r => r.soc === '31-1120');
  const us = census['00'];
  return {
    occupations: natDetail.map(({ soc, employment, p10, median, p90 }) => ({ soc, employment, p10, median, p90 })),
    aides: { mean: aides.mean, annualMedian: aides.annualMedian },
    projections: {
      emp2025: Math.round(ep.emp2025 * 1000), emp2035: Math.round(ep.emp2035 * 1000), change: Math.round(ep.change * 1000),
      pct: Math.round(ep.pct), openings: Math.round(ep.openings * 1000), header: ep.header,
    },
    population: { pop65: us.pop65, total: us.allAges, share65: round1(us.pop65 / us.allAges * 100) },
  };
}

// ---------- Live site: does the deployed bundle carry exactly these values? ----------
// The minifier (esbuild) writes numbers in shortest form: it drops a leading zero (0.45 -> .45)
// and writes an integer with trailing zeros as XeN when that is shorter (1102000 -> 1102e3).
export function minNum(v) {
  let s = String(Number(v));
  if (/^-?\d+$/.test(s)) {
    const m = s.match(/^(-?\d*?[1-9])(0+)$/);
    if (m) { const e = `${m[1]}e${m[2].length}`; if (e.length < s.length) s = e; }
    return s;
  }
  return s.replace(/^0\./, '.').replace(/^-0\./, '-.');
}

// The literal text each value should have in the bundle.
export function siteLiterals({ states, national, indexRows }) {
  const n = minNum, out = [];
  for (const s of states) out.push([`state ${s.code}`, `{code:"${s.code}",name:"${s.name}",fips:"${s.fips}",pop2025:${n(s.pop2025)},pop65:${n(s.pop65)},share65:${n(s.share65)},aides:${n(s.aides)},medianWage:${n(s.medianWage)},aidesPer1000_65:${n(s.aidesPer1000_65)}}`]);
  for (const o of national.occupations) out.push([`occupation ${o.soc}`, `soc:"${o.soc}",p10:${n(o.p10)},median:${n(o.median)},p90:${n(o.p90)},employment:${n(o.employment)}`]);
  const p = national.projections, a = national.aides, u = national.population;
  const aides = national.occupations.find(o => o.soc === '31-1120');
  out.push(['national figures', `{employment:${n(aides.employment)},medianHourly:${n(aides.median)},medianAnnual:${n(a.annualMedian)},meanHourly:${n(a.mean)},p10Hourly:${n(aides.p10)},p90Hourly:${n(aides.p90)},projEmployment2025:${n(p.emp2025)},projEmployment2035:${n(p.emp2035)},projChange:${n(p.change)},projChangePct:${n(p.pct)},annualOpenings:${n(p.openings)},population65plus2025:${n(u.pop65)},share65plus2025:${n(u.share65)}}`]);
  for (const r of indexRows) out.push([`index ${r.code}`, `{name:"${r.name}",code:"${r.code}",gpi:${n(r.gpi)},mfi:${n(r.mfi)},quadrant:"${r.quadrant}"}`]);
  return out;
}

// bundle: text of /assets/index-*.js; canon: {name: jsonString}. Returns the labels not found.
export function siteChecks(bundle, { canon, states, national, indexRows, pay = [] }) {
  const missing = Object.entries(canon).filter(([, json]) => !bundle.includes(json)).map(([name]) => `dataset ${name}`);
  for (const [label, lit] of siteLiterals({ states, national, indexRows })) if (!bundle.includes(lit)) missing.push(label);
  for (const r of pay) if (!bundle.includes('[' + r.map(v => v === null ? 'null' : typeof v === 'string' ? JSON.stringify(v) : minNum(v)).join(',') + ']')) missing.push(`row ${r[0]} (${r.length} fields)`);
  return missing;
}

// ---------- Compare two JSON values; list up to `max` differing paths ----------
export function diffPaths(a, b, path = '', out = [], max = 25) {
  if (out.length >= max) return out;
  if (a === b) return out;
  if (typeof a !== 'object' || typeof b !== 'object' || a === null || b === null || Array.isArray(a) !== Array.isArray(b)) {
    out.push(`${path || '(root)'}: ${JSON.stringify(a)} -> ${JSON.stringify(b)}`);
    return out;
  }
  const keys = [...new Set([...Object.keys(a), ...Object.keys(b)])];
  for (const k of keys) diffPaths(a[k], b[k], path ? `${path}.${k}` : k, out, max);
  return out;
}

// W2 (src/data/ratesData.ts): KFF Medicaid HCBS Survey 2026, Appendix Table 4 (datawrapper 5M0i2), tab-separated.
const KFF_STATE_CODES = { 'Alabama': 'AL', 'Alaska': 'AK', 'Arizona': 'AZ', 'Arkansas': 'AR', 'California': 'CA', 'Colorado': 'CO', 'Connecticut': 'CT', 'Delaware': 'DE', 'District of Columbia': 'DC', 'Florida': 'FL', 'Georgia': 'GA', 'Hawaii': 'HI', 'Idaho': 'ID', 'Illinois': 'IL', 'Indiana': 'IN', 'Iowa': 'IA', 'Kansas': 'KS', 'Kentucky': 'KY', 'Louisiana': 'LA', 'Maine': 'ME', 'Maryland': 'MD', 'Massachusetts': 'MA', 'Michigan': 'MI', 'Minnesota': 'MN', 'Mississippi': 'MS', 'Missouri': 'MO', 'Montana': 'MT', 'Nebraska': 'NE', 'Nevada': 'NV', 'New Hampshire': 'NH', 'New Jersey': 'NJ', 'New Mexico': 'NM', 'New York': 'NY', 'North Carolina': 'NC', 'North Dakota': 'ND', 'Ohio': 'OH', 'Oklahoma': 'OK', 'Oregon': 'OR', 'Pennsylvania': 'PA', 'Rhode Island': 'RI', 'South Carolina': 'SC', 'South Dakota': 'SD', 'Tennessee': 'TN', 'Texas': 'TX', 'Utah': 'UT', 'Vermont': 'VT', 'Virginia': 'VA', 'Washington': 'WA', 'West Virginia': 'WV', 'Wisconsin': 'WI', 'Wyoming': 'WY' };
export function kffRates(tsv) {
  const cell = (s) => {
    s = s.trim();
    if (!s.startsWith('$')) return [null, s];
    return [Number(s.replace(/[$*,]/g, '')), s.endsWith('*') ? 'not hourly' : ''];
  };
  const out = {};
  for (const line of tsv.split(/\r?\n/)) {
    const r = line.split('\t');
    if (r.length < 6 || r[0] === 'State' || r[0] === 'Median') continue;
    const code = KFF_STATE_CODES[r[0].replace(/\*+$/, '')];
    if (!code) throw new Error(`KFF rates: unknown state "${r[0]}"`);
    out[code] = { agency: cell(r[1]), provider: cell(r[2]), hha: cell(r[5]) };
  }
  return out;
}
// Rows in RATES_RAW order: code, agencyRate, agencyFlag, providerRate, providerFlag, hhaRate, hhaFlag, aideWage2025, wageShare.
// pay = rows of site_pay.json (index 1 = aideMedian2025).
export function buildRates(kff, pay) {
  return pay.map(p => p[0]).sort().map(code => {
    const k = kff[code];
    if (!k) throw new Error(`KFF rates: no row for ${code}`);
    const w = pay.find(p => p[0] === code)[1];
    const share = (k.agency[0] && k.agency[1] === '' && w) ? Math.round(w / k.agency[0] * 1000) / 1000 : null;
    return [code, k.agency[0], k.agency[1], k.provider[0], k.provider[1], k.hha[0], k.hha[1], w, share];
  });
}
