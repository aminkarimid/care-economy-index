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
  const name = z.names.find(k => /state.*\.xlsx$/i.test(k));
  const b = await xlsxBook(await z.get(name));
  const rows = await b.read();
  const idx = Object.fromEntries(Object.entries(rows[0]).map(([k, v]) => [String(v).toUpperCase(), k]));
  const out = {};
  rows.slice(1).filter(r => r[idx.OCC_CODE] === occ).forEach(r => {
    out[r[idx.PRIM_STATE]] = { aides: +r[idx.TOT_EMP], medianWage: +r[idx.H_MEDIAN] };
  });
  return out;
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
export function siteChecks(bundle, { canon, states, national, indexRows }) {
  const missing = Object.entries(canon).filter(([, json]) => !bundle.includes(json)).map(([name]) => `dataset ${name}`);
  for (const [label, lit] of siteLiterals({ states, national, indexRows })) if (!bundle.includes(lit)) missing.push(label);
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
