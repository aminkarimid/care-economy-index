# CareDex data check

[caredex.vercel.app](https://caredex.vercel.app) shows figures copied from public sources. This folder checks once a month that those figures still match their sources and that the live site still shows them.

## What runs

`.github/workflows/caredex-data-check.yml` runs `node caredex/check.mjs` at 14:17 UTC on the 3rd of each month. You can also start it by hand from the Actions tab (Run workflow).

The script:

1. Downloads each source and rebuilds the exact values the site uses (`sources.mjs` holds the parsers).
2. Compares them with the snapshots in `expected/`, which are the values the site was built from on 23 November 2026 (population moved to Census Vintage 2025 the same day).
3. Downloads the site's JavaScript bundle and checks that every snapshot value is in it: the six chart datasets, all 51 state rows, the national figures and the 51 GPI/MFI rows from `results/offline_rerun_2026-11-23/SYPA_GPI_MFI_v5.csv`.
4. Looks for newer releases: OEWS May 2026, Census Vintage 2026, a new KFF chart version, and a new Employment Projections period.

If anything changed, a source could not be read, or a newer release is out, the workflow opens an issue labelled `caredex-data` (or comments on the open one). The rebuilt values are saved as the run artifact `caredex-out`. A run where a source could not be read is marked failed.

Nothing on the site changes automatically. When the check reports a change, look at the source first, then update the site data and the matching file in `expected/`.

## Sources checked

| Snapshot | Source |
|---|---|
| `a1_cms.json` | CMS National Health Expenditure Accounts, Table 23 (nhe-tables.zip) |
| `a2_ep.json` | BLS Employment Projections 2025-35, Table 1.4 (occupation.xlsx) |
| `a3_cooper.json` | Weldon Cooper Center national population projections, age and sex workbook (link read from the projections page) |
| `a4_oews.json` | BLS OEWS national files, May 2014 to May 2025 |
| `a4_cpi.json` | CPI-U, U.S. city average, not seasonally adjusted, May of each year (FRED CPIAUCNS, the same series as BLS CUUR0000SA0) |
| `a5_kff.json` | KFF, 10 Things About LTSS, Figure 2 data (Datawrapper WNQfV v5) |
| `site_states.json` | BLS OEWS May 2025 state file; Census Vintage 2025 civilian population by age |
| `site_national.json` | BLS OEWS May 2025 national file; BLS Employment Projections Table 1.2; Census Vintage 2025 |

Not checked automatically: OEWS industry employment (from OEWS Profiles), the KFF 2024 text figures and the PHI 2025 key facts. Check those by hand when new editions come out.

## Known limits

Some government sites refuse requests from cloud servers. If the BLS or Census downloads fail on GitHub's runners every month, the issue will say so; run `node caredex/check.mjs` on your own computer instead (Node 22 or newer, no packages needed).

The requests send ordinary browser headers and no contact details.
