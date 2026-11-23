// CareDex monthly data check.
// 1. Re-fetches every primary source behind caredex.vercel.app and rebuilds the values the site shows.
// 2. Compares them with the snapshots in caredex/expected/ (what the site was built from).
// 3. Checks that the deployed site still carries exactly those values.
// 4. Looks for newer releases the site does not use yet.
// Writes caredex/out/ (rebuilt values and report.md) and appends the report to $GITHUB_STEP_SUMMARY.
// Exit code: 0 when every source was read, 1 when any fetch or parse failed. Data changes do not fail the run;
// the workflow opens an issue for them instead.
// Usage: node caredex/check.mjs   (Node 22 or newer; no dependencies)

import { readFileSync, writeFileSync, mkdirSync, appendFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import * as S from './sources.mjs';

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = join(HERE, '..');
const OUT = join(HERE, 'out');
const EXP = join(HERE, 'expected');
const SITE = process.env.CAREDEX_URL || 'https://caredex.vercel.app/';
const INDEX_CSV = process.env.CAREDEX_INDEX_CSV || join(ROOT, 'results/index_rebuild_2026-11-23/index_results_2026-11-23.csv');

// Ordinary browser headers. No contact details are sent.
const HEADERS = {
  'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/131.0.0.0 Safari/537.36',
  'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8',
  'Accept-Language': 'en-US,en;q=0.9',
};

const URLS = {
  cms: 'https://www.cms.gov/files/zip/nhe-tables.zip',
  ep: 'https://www.bls.gov/emp/ind-occ-matrix/occupation.xlsx',
  cooperPage: 'https://www.coopercenter.org/national-population-projections',
  oewsNat: (yy) => `https://www.bls.gov/oes/special-requests/oesm${yy}nat.zip`,
  oewsSt: 'https://www.bls.gov/oes/special-requests/oesm25st.zip',
  oewsSt24: 'https://www.bls.gov/oes/special-requests/oesm24st.zip',
  dol: 'https://www.dol.gov/agencies/whd/state/minimum-wage/history',
  bea: 'https://apps.bea.gov/regional/zip/SARPP.zip',
  acsShells: 'https://www2.census.gov/programs-surveys/acs/summary_file/2025/table-based-SF/documentation/ACS20251YR_Table_Shells.txt',
  acs: (t) => `https://www2.census.gov/programs-surveys/acs/summary_file/2025/table-based-SF/data/1YRData/acsdt1y2025-${t}.dat`,
  qwi: (st, f) => `https://lehd.ces.census.gov/data/qwi/latest_release/${st}/${f}`,
  qwiRelease: 'R2026Q4',
  cpi: 'https://fred.stlouisfed.org/graph/fredgraph.csv?id=CPIAUCNS',
  kff: 'https://datawrapper.dwcdn.net/WNQfV/5/dataset.csv',
  kffRates: 'https://datawrapper.dwcdn.net/5M0i2/4/dataset.csv',
  census: 'https://www2.census.gov/programs-surveys/popest/datasets/2020-2025/state/asrh/sc-est2025-agesex-civ.csv',
  // Newer releases. A 200 here means the site could move to newer data.
  probes: {
    'OEWS May 2026 national file': 'https://www.bls.gov/oes/special-requests/oesm26nat.zip',
    'OEWS May 2026 state file': 'https://www.bls.gov/oes/special-requests/oesm26st.zip',
    'Census Vintage 2026 civilian population by age': 'https://www2.census.gov/programs-surveys/popest/datasets/2020-2026/state/asrh/sc-est2026-agesex-civ.csv',
    'KFF chart WNQfV version 6': 'https://datawrapper.dwcdn.net/WNQfV/6/dataset.csv',
    'KFF HCBS rates table 5M0i2 version 5': 'https://datawrapper.dwcdn.net/5M0i2/5/dataset.csv',
    'ACS 2026 1-year table-based summary file': 'https://www2.census.gov/programs-surveys/acs/summary_file/2026/table-based-SF/data/1YRData/acsdt1y2026-b18107.dat',
  },
};

const sleep = (ms) => new Promise(r => setTimeout(r, ms));
async function get(url, kind = 'buffer', tries = 3) {
  let last;
  for (let i = 1; i <= tries; i++) {
    try {
      const r = await fetch(url, { headers: HEADERS, redirect: 'follow' });
      if (!r.ok) throw new Error(`HTTP ${r.status}`);
      return kind === 'text' ? await r.text() : await r.arrayBuffer();
    } catch (e) {
      last = e;
      if (i < tries) await sleep(5000 * i);
    }
  }
  throw new Error(`${url}: ${last.message}`);
}
async function probe(url) {
  try {
    const r = await fetch(url, { method: 'HEAD', headers: HEADERS, redirect: 'follow' });
    return r.status;
  } catch (e) { return `error: ${e.message}`; }
}

const readExp = (f) => readFileSync(join(EXP, f), 'utf8');
const errors = [];
const changes = [];
const ok = [];
const notes = [];

async function step(name, fn) {
  try { return await fn(); } catch (e) { errors.push(`${name}: ${e.message}`); return undefined; }
}

// Compare a rebuilt JSON string with the snapshot file of the same name.
function compareCanon(name, file, rebuilt, sourceUrl) {
  if (rebuilt === undefined) return;
  writeFileSync(join(OUT, file), rebuilt);
  const expected = readExp(file);
  if (rebuilt === expected) { ok.push(`${name} unchanged`); return; }
  const d = S.diffPaths(JSON.parse(expected), JSON.parse(rebuilt));
  changes.push({ name, source: sourceUrl, diff: d });
}
function compareObj(name, file, rebuilt, sourceUrl) {
  if (rebuilt === undefined) return;
  writeFileSync(join(OUT, file), JSON.stringify(rebuilt, null, 1));
  // Key arrays of states by their code so a change reads "TX.medianWage", not "43.medianWage".
  const byCode = (v) => Array.isArray(v) && v.every(r => r && r.code) ? Object.fromEntries(v.map(r => [r.code, r])) : v;
  const d = S.diffPaths(byCode(JSON.parse(readExp(file))), byCode(rebuilt));
  if (d.length === 0) ok.push(`${name} unchanged`); else changes.push({ name, source: sourceUrl, diff: d });
}

// Rows of src/data/indexComponents.ts, from the CareDex index rebuild CSV (same column order as the site file).
function readIndexComponents(path) {
  const lines = readFileSync(path, 'utf8').trim().split(/\r?\n/);
  const h = lines[0].split(',');
  const cols = ['state_code', 'HPAS', 'GPI_c_rebal', 'GPI_c3', 'GPI_hpas_mult', 'MFI_MF2_wage', 'MFI_MF2_afford', 'MFI_MF2', 'MFI_MF1', 'MFI_bottleneck', 'Wage_Compression_Ratio', 'Training_Floor_Gap'];
  const ix = cols.map(n => { const i = h.indexOf(n); if (i < 0) throw new Error(`column ${n} missing in ${path}`); return i; });
  return lines.slice(1).map(l => l.split(',')).map(c => ix.map((i, k) => (k === 0 || k === 9 ? c[i] : Number(c[i]))))
    .sort((a, b) => (a[0] < b[0] ? -1 : 1));
}

function readIndexCsv(path) {
  const lines = readFileSync(path, 'utf8').trim().split(/\r?\n/);
  const h = lines[0].split(',');
  const ix = (n) => { const i = h.indexOf(n); if (i < 0) throw new Error(`column ${n} missing in ${path}`); return i; };
  const [iN, iC, iG, iM, iQ] = ['State', 'state_code', 'GPI', 'MFI', 'Quadrant'].map(ix);
  return lines.slice(1).map(l => l.split(',')).map(c => ({ name: c[iN], code: c[iC], gpi: c[iG], mfi: c[iM], quadrant: c[iQ] }));
}

async function main() {
  mkdirSync(OUT, { recursive: true });

  // A1: CMS National Health Expenditure Table 23
  compareCanon('A1 CMS home health spending (NHE Table 23)', 'a1_cms.json',
    await step('CMS nhe-tables.zip', async () => S.cmsHomeHealth(await get(URLS.cms))), URLS.cms);

  // A2 and aides projections: BLS Employment Projections
  const epBuf = await step('BLS occupation.xlsx', () => get(URLS.ep));
  if (epBuf) {
    compareCanon('A2 fastest job growth (EP Table 1.4)', 'a2_ep.json', await step('EP Table 1.4', () => S.epMostJobGrowth(epBuf)), URLS.ep);
  }
  const ep = epBuf && await step('EP Table 1.2', () => S.epOccupation(epBuf));

  // A3: Cooper Center projections. The link changes with each vintage, so read it from the page.
  const cooperUrl = await step('Cooper Center page', async () => {
    const html = await get(URLS.cooperPage, 'text');
    const m = html.match(/href="([^"]*_AGE_SEX\.xlsx)"/i);
    if (!m) throw new Error('no *_AGE_SEX.xlsx link on the page');
    return new URL(m[1], URLS.cooperPage).href;
  });
  if (cooperUrl) {
    notes.push(`Cooper Center workbook used: ${cooperUrl}`);
    compareCanon('A3 share aged 65+ by state (Cooper Center)', 'a3_cooper.json',
      await step('Cooper workbook', async () => S.cooperAging(await get(cooperUrl))), cooperUrl);
  }

  // A4: OEWS national medians, May 2014 to May 2025; the 2025 file also feeds the Overview and wage chart.
  const medians = {};
  let nat2025;
  for (let y = 2014; y <= 2025; y++) {
    const yy = String(y).slice(2);
    const parsed = await step(`OEWS May ${y} national file`, async () => S.oewsNationalRows(await get(URLS.oewsNat(yy))));
    if (!parsed) continue;
    medians[String(y)] = S.oewsMedians(y, parsed);
    if (y === 2025) nat2025 = parsed;
  }
  if (Object.keys(medians).length === 12) compareCanon('A4 median hourly wages (OEWS)', 'a4_oews.json', JSON.stringify(medians), URLS.oewsNat('YY'));

  // CPI-U, May of each year
  compareCanon('CPI-U, May (FRED CPIAUCNS)', 'a4_cpi.json',
    await step('FRED CPIAUCNS', async () => S.cpiMay(await get(URLS.cpi, 'text'))), URLS.cpi);

  // A5: KFF LTSS spending by setting and payer
  compareCanon('A5 LTSS spending by payer (KFF)', 'a5_kff.json',
    await step('KFF dataset.csv', async () => S.kffLtss(await get(URLS.kff, 'text'))), URLS.kff);

  // States and national figures
  const census = await step('Census civilian population', async () => S.censusCivPop(await get(URLS.census, 'text'), 2025));
  const oewsStBuf = await step('OEWS May 2025 state file', () => get(URLS.oewsSt));
  const oewsSt = oewsStBuf && await step('OEWS May 2025 state parse', () => S.oewsStates(oewsStBuf));
  const siteStates = JSON.parse(readExp('site_states.json'));
  const siteNational = JSON.parse(readExp('site_national.json'));
  if (census && oewsSt) {
    const rebuilt = await step('build states', () => S.buildStates(oewsSt, census, siteStates)
      .map(r => ({ code: r.code, name: siteStates.find(s => s.code === r.code).name, ...r })));
    compareObj('State figures (OEWS May 2025, Census V2025)', 'site_states.json', rebuilt, `${URLS.oewsSt} ; ${URLS.census}`);
  }
  if (census && nat2025 && ep) {
    const rebuilt = await step('build national', () =>
      S.buildNational(JSON.parse(S.oewsNationalDetail(nat2025, siteNational.occupations.map(o => o.soc))), ep, census));
    compareObj('National figures (OEWS May 2025, EP 2025-35, Census V2025)', 'site_national.json', rebuilt, `${URLS.oewsNat('25')} ; ${URLS.ep} ; ${URLS.census}`);
  }


  // Pay layer (src/data/payData.ts): competing jobs (OEWS May 2025), aide median May 2024, DOL minimum wage 2024, BEA RPP 2024
  const m25 = oewsStBuf && await step('OEWS May 2025 state medians', () => S.oewsStateMedians(oewsStBuf));
  const m24 = await step('OEWS May 2024 state file', async () => S.oewsStateMedians(await get(URLS.oewsSt24), ['31-1120']));
  const dolHtml = await step('DOL minimum wage history page', () => get(URLS.dol, 'text'));
  const dol = dolHtml && await step('DOL 2024 column', () => S.dolMinWageColumn(dolHtml, '2024'));
  const rpp = await step('BEA SARPP.zip', async () => S.beaRpp(await get(URLS.bea)));
  if (m25 && m24 && dol && rpp) {
    compareCanon('Pay layer (OEWS 2024-25, DOL, BEA RPP)', 'site_pay.json',
      await step('build pay', () => JSON.stringify(S.buildPay(m25, m24, dol, rpp, siteStates))), `${URLS.oewsSt} ; ${URLS.oewsSt24} ; ${URLS.dol} ; ${URLS.bea}`);
  }

  // Need layer (src/data/needData.ts): ACS 2025 1-year B18107/B18106; KFF 2026 waiting lists come from the snapshot (KFF pages are not machine-readable).
  const acs = await step('ACS 2025 B18107/B18106', async () => S.acsDisability(await get(URLS.acsShells, 'text'), await get(URLS.acs('b18107'), 'text'), await get(URLS.acs('b18106'), 'text')));
  if (acs) compareCanon('Need layer (ACS 2025 B18107/B18106 with KFF 2026 snapshot)', 'site_need.json',
    await step('build need', () => JSON.stringify(S.buildNeed(acs, JSON.parse(readExp('kff_waiting_2026.json')), siteStates))), `${URLS.acs('b18107')} ; ${URLS.acs('b18106')}`);
  notes.push('KFF waiting lists (2026 survey) are checked by hand: https://www.kff.org/medicaid/state-indicator/number-of-people-waiting-for-hcbs-by-target-population-and-whether-states-screen-for-eligibility/');

  // Medicaid rates layer (src/data/ratesData.ts, RATES_RAW): KFF Medicaid HCBS Survey 2026 Appendix Table 4 joined with the aide median in site_pay.json.
  compareCanon('Medicaid rates (KFF 2026 Appendix Table 4)', 'site_rates.json',
    await step('build rates', async () => JSON.stringify(S.buildRates(S.kffRates(await get(URLS.kffRates, 'text')), JSON.parse(readExp('site_pay.json'))))), URLS.kffRates);
  notes.push('State payment rate disclosures (DISCLOSURE_CHECK in ratesData.ts, 8 states) are checked by hand against the files linked on the Financing page.');

  // Turnover layer (src/data/qwiData.ts): QWI. A release probe always; the full rebuild (about 900 MB of downloads) only with CAREDEX_QWI=1.
  const qwiVer = await step('QWI release (MA version file)', () => get(URLS.qwi('ma', 'version_qwi.txt'), 'text'));
  if (qwiVer && !qwiVer.includes(URLS.qwiRelease)) releases.push(`QWI has a release newer than ${URLS.qwiRelease}: ${qwiVer.trim().split(/\r?\n/)[0]}`);
  if (process.env.CAREDEX_QWI === '1') {
    const { Readable } = await import('node:stream');
    const zlib = await import('node:zlib');
    const readline = await import('node:readline');
    const order = ['al','ak','az','ar','ca','co','ct','de','dc','fl','ga','hi','id','il','in','ia','ks','ky','la','me','md','ma','mi','mn','ms','mo','mt','ne','nv','nh','nj','nm','ny','nc','nd','oh','ok','or','pa','ri','sc','sd','tn','tx','ut','vt','va','wa','wv','wi','wy'];
    const lines = async (url) => { const r = await fetch(url, { headers: HEADERS }); if (!r.ok) throw new Error(`${url}: HTTP ${r.status}`); return readline.createInterface({ input: Readable.fromWeb(r.body).pipe(zlib.createGunzip()), crlfDelay: Infinity }); };
    const byState = {};
    for (const st of order) {
      const rows = await step(`QWI ${st}`, async () => [
        ...await S.qwiPick(await lines(URLS.qwi(st, `qwi_${st}_rh_f_gs_n4_op_u.csv.gz`)), ['6216', '6241']),
        ...await S.qwiPick(await lines(URLS.qwi(st, `qwi_${st}_rh_f_gs_ns_op_u.csv.gz`)), ['00'])]);
      if (rows) byState[st] = rows;
    }
    if (Object.keys(byState).length === order.length) compareCanon('Turnover layer (QWI)', 'site_qwi.json', JSON.stringify(S.buildQwi(byState, order)), URLS.qwi('<st>', ''));
  } else notes.push('QWI full rebuild skipped (set CAREDEX_QWI=1 to run it; about 900 MB of downloads).');

  // Live site: does the deployed bundle still carry the snapshot values?
  let siteMissing;
  await step('caredex.vercel.app bundle', async () => {
    const html = await get(SITE, 'text');
    const js = html.match(/\/assets\/index-[\w-]+\.js/);
    if (!js) throw new Error('no /assets/index-*.js in the page');
    const bundle = await get(new URL(js[0], SITE).href, 'text');
    const canon = Object.fromEntries(['a1_cms', 'a2_ep', 'a3_cooper', 'a4_oews', 'a4_cpi', 'a5_kff'].map(n => [n, readExp(`${n}.json`)]));
    siteMissing = S.siteChecks(bundle, { canon, states: siteStates, national: siteNational, indexRows: readIndexCsv(INDEX_CSV), pay: [...JSON.parse(readExp('site_pay.json')), ...readIndexComponents(INDEX_CSV), ...JSON.parse(readExp('site_need.json')), ...JSON.parse(readExp('site_qwi.json')).out, ...JSON.parse(readExp('site_qwi.json')).tr, ...JSON.parse(readExp('site_rates.json'))] });
    notes.push(`Site bundle checked: ${new URL(js[0], SITE).href}`);
  });
  if (siteMissing && siteMissing.length === 0) ok.push('Live site carries every snapshot value (6 datasets, 51 states, national figures, 51 index rows, 51 pay rows, 51 index-component rows, 51 need rows, 51 turnover rows, 26 turnover-trend rows)');
  if (siteMissing && siteMissing.length) changes.push({ name: 'Live site differs from the snapshots', source: SITE, diff: siteMissing.map(m => `not found in bundle: ${m}`) });

  // Newer releases
  const releases = [];
  for (const [label, url] of Object.entries(URLS.probes)) {
    const st = await probe(url);
    if (st === 200) releases.push(`${label} is available: ${url}`);
  }
  if (dolHtml) { try { S.dolMinWageColumn(dolHtml, '2025'); releases.push(`DOL minimum wage table now has a 2025 column: ${URLS.dol}`); } catch { /* not yet */ } }
  if (rpp && Object.values(rpp)[0] && Object.values(rpp)[0]['2025'] !== undefined) releases.push(`BEA RPP now covers 2025: ${URLS.bea}`);
  if (ep && ep.header !== siteNational.projections.header) releases.push(`BLS Employment Projections now has a new period: "${ep.header}"`);

  // Report
  const date = new Date().toISOString().slice(0, 10);
  const L = [`# CareDex data check, ${date}`, ''];
  L.push(`Changed: ${changes.length} · New releases: ${releases.length} · Fetch or parse errors: ${errors.length} · Unchanged: ${ok.length}`, '');
  if (changes.length) {
    L.push('## Changed against the snapshots', '');
    for (const c of changes) {
      L.push(`### ${c.name}`, `Source: ${c.source}`, '', '```', ...c.diff, '```', '');
    }
    L.push('Rebuilt values are in the run artifact `caredex-out`. Update the site and caredex/expected/ only after checking the change at the source.', '');
  }
  if (releases.length) { L.push('## Newer releases the site does not use yet', '', ...releases.map(r => `- ${r}`), ''); }
  if (errors.length) { L.push('## Fetch or parse errors', '', ...errors.map(e => `- ${e}`), ''); }
  L.push('## Unchanged', '', ...ok.map(o => `- ${o}`), '');
  if (notes.length) { L.push('## Notes', '', ...notes.map(n => `- ${n}`), ''); }
  L.push('Not checked automatically: OEWS industry employment (OEWS Profiles), KFF 2024 text figures, PHI 2025 key facts. Check these by hand when their publishers release new editions.');
  const report = L.join('\n');
  writeFileSync(join(OUT, 'report.md'), report);
  writeFileSync(join(OUT, 'status.json'), JSON.stringify({ changes: changes.length, releases: releases.length, errors: errors.length }));
  if (process.env.GITHUB_STEP_SUMMARY) appendFileSync(process.env.GITHUB_STEP_SUMMARY, report + '\n');
  console.log(report);
  process.exitCode = errors.length ? 1 : 0;
}

main().catch(e => { console.error(e); process.exitCode = 1; });
