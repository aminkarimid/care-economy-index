# CareDex Index (GPI, MFI) input audit, 23 Nov 2026

Scope: every input behind the components shown on the CareDex Index page (HPAS, GPI_c_rebal, GPI_c3, MFI_MF2_wage, MFI_MF2_afford, MFI_MF1, Wage_Compression_Ratio, Training_Floor_Gap) and the quadrants. Site values come from the offline rerun of SYPA_Complete_Pipeline.py (results/offline_rerun_2026-11-23). A re-implementation of the formulas from SYPA_Full_v5.csv reproduces the site's GPI, MFI and all 51 quadrants exactly (max difference 3e-14), so the problems below are in the inputs and labels, not in the arithmetic.

Rule applied: a number from the thesis is wrong until checked against a primary source.

## Verdict by input

| Input | Feeds | Status | Finding |
|---|---|---|---|
| P10 and median wage for wage compression (BLS_WAGE_COMPRESSION_DATA, hardcoded) | Wage_Compression_Ratio, MFI_MF1 | **Fabricated** | The code says P10 was "estimated from state minimum wages + competitive labor market floor". The medians in the same table are not BLS values either: they differ from the OEWS May 2024 medians the index uses elsewhere by $1.39 on average (Texas $15.29 vs $11.49 actual). Rank correlation of the hardcoded ratio with the actual OEWS May 2025 P10/median ratio: 0.52. Louisiana shows 0.60 on the site; OEWS gives 0.85. |
| PCA training hours (PHI_TRAINING_HOURS, hardcoded) | Training_Floor_Gap, MFI_MF1 | **Wrong** | The table does not match PHI's 2025 state-by-state requirements. Massachusetts, New York and Washington are coded at 120 hours; PHI lists 60 (MA personal care homemaker, agency, Medicaid), 40 (NY) and 75 (WA). California is coded 70; PHI lists 10 hours for agency home care aides and 8 for the HCBA waiver. A few states do exceed 75 hours because they require HHA or CNA training (DC 125, RI 120, HI 100, WY 91). The 120-hour benchmark is the IOM recommendation for home health aides and nursing assistants, not a PCA standard. Each state has several PCA roles in PHI's tables, so a single number per state needs a stated rule. *(Corrected 23 Nov: an earlier version of this audit said no state requires more than 75 hours, from an older PHI article; PHI's 2025 table shows four that do.)* |
| Aide median wage (Wage_Aide) | MFI_MF2_wage (wage gap) | **Altered for 3 states** | 48 states equal the OEWS May 2024 state median exactly (log mislabels it "2022 fallback"). Louisiana, Mississippi and Texas were raised to $11.49 (a national P10 floor) from their actual $10.18, $11.36 and $11.29. |
| Aide employment (Aide_Count) | MFI_MF2_wage (labor scarcity) | OK | Equals OEWS May 2024 employment, 51 of 51. |
| Population 65+ (Raw_UVA_2030) | MFI_MF2_wage (labor scarcity) | **Wrong year** | A 2030 projection (older Cooper Center vintage; shares differ from the 2030 shares the site now shows) divided into 2024 aide counts. Counts are fractional. The site describes the measure as aides per 1,000 people 65+, which a 2030 denominator is not. |
| MIT living wage, 1 adult 0 children (hardcoded) | MFI_MF2_wage (wage gap) | **Mixed vintage** | Code says about 16 states are still on the Feb 2025 release. Checked against MIT today (Feb 15 2026 data): West Virginia $19.53 matches; Texas $21.82 vs $21.77; California $28.72 vs $30.48. |
| Home care cost (CareScout 2024) | MFI_MF2_afford | OK on all states checked | Massachusetts $38 = $86,944 / 2,288 hours (Genworth/CareScout press release); Alabama $25, Arkansas $26, Louisiana $22, Mississippi $25, New Mexico $28 match the 2024 ranked state table. |
| Median household income, householder 65+ (ACS 2023 1-year, B19049_005E) | MFI_MF2_afford | OK | 51 of 51 equal a live Census API pull of ACS 2023. |
| HCBS share of LTSS users and spending, 65+ (CMS LTSS rebalancing, 2023 files) | GPI_c_rebal | OK, with a caveat | Genuine CMS T-MSIS files; values match. CMS rates HCBS data quality "High Concern" for some states (Alaska FFS users, among others); the site does not say so. |
| ADRC/NWD functions (AARP 2023 Scorecard) | GPI_c3 | Values plausible, **label wrong** | The file's maximum (97%, Wisconsin) and mean (71.7%) match AARP's published best (97%) and U.S. value (72%). AARP's indicator page is retired, so the 51 values could not be checked one by one. The measure is a self-reported survey of how many of 41 system functions a state has; the code and site call it "access velocity" (time to services), which it does not measure. |
| HPAS (hardcoded, "KFF 2024 + MACPAC 2020") | GPI multiplier (0.10 / 0.55 / 1.00) | **8 states disagree with KFF 2026** | Applying the stated definition (0 = no waiting list; 1 = waiting list, no eligibility screening; 2 = waiting list with screening) to KFF's 2026 table: FL 2→1, IL 1→2, NE 2→0, NM 2→1, NY 0→2, RI 2→0, WA 1→2, WI 0→2. The multiplier makes HPAS the largest single driver of GPI (a factor of ten between 0 and 2), so each misclassification moves a state across the GPI median. Some of these may be deliberate calls on the thesis's 2024 data; none is documented. |
| MFI_bottleneck label | Index page "largest component" | **Wrong formula** | The pipeline computes MFI v5, then runs the legacy MFI v4 function, which overwrites MFI_bottleneck using PHI State Index ranks as proxies. All 51 labels on the site come from that legacy formula, not from the headline MFI. |
| AARP overall rank, PHI ranks | Validation only | AARP OK | AARP ranks match the published 2023 order (top five; 36 to 51). Not shown on the site. |

## How much it matters

Correcting only the three inputs that can be fixed from data already in hand (remove the wage floor; replace the fabricated compression ratio with actual OEWS P10/median; classify HPAS by the stated rule on KFF 2026) moves **11 of 51 states to a different quadrant**: AL, AR, AZ, FL, GA, IL, NE, NM, PA, RI, WI. HPAS alone moves 8; the compression ratio alone moves 4; the wage floor alone moves none. The training-hours and population fixes, not yet made, will move more. The quadrant map on the site should not be read as a finding until the index is rebuilt.

The same inputs feed the thesis's published GPI/MFI results and the private PRI ranking.

## Fix list (proposed)

1. Now: put a notice on the Index page that the index is under revision, or take the page down, until the rebuild is checked. MF1 and its two components rest on fabricated or wrong numbers and break the site's rule that every figure traces to a primary source.
2. Wages, employment, P10: one vintage, OEWS May 2025 state file (already extracted for the site), no floor.
3. Population 65+: Census Vintage 2025 (already on the site), same year as the aides.
4. MIT living wage: refetch all 51 states from the Feb 15 2026 release.
5. HPAS: derive from KFF 2026 by the written rule, published with the table; or drop the multiplier.
6. Training: rebuild from PHI's state pages with a written rule (for example, hours for agency-employed PCAs in the state's main Medicaid personal care program), or drop the component and let MF1 rest on wage compression alone. Drop the 120-hour PCA benchmark either way.
7. Rename GPI_c3 to "ADRC/No Wrong Door functions (self-reported, 2022 survey)".
8. Note CMS data-quality ratings next to the rebalancing measure.
9. Recompute, re-run the validation checks, and add the rebuilt inputs to the monthly monitor so every input has a file and a hash.

## Sources checked

- PHI, Personal Care Aide Training Regulations Continue to Fall Short (phinational.org/?p=15318); PHI state-by-state PCA requirements (phinational.org/?p=12551).
- MIT Living Wage Calculator state pages, data updated Feb 15 2026 (livingwage.mit.edu/states/48, /54, /06).
- Genworth/CareScout 2024 Cost of Care Survey, Massachusetts press release (businesswire.com/news/home/20250301706133/en/) and 2024 ranked state tables.
- AARP 2023 LTSS State Scorecard, ADRC/NWD Functions indicator (best state 97%, U.S. 72%) and 2023 rankings.
- KFF State Health Facts, people waiting for Medicaid HCBS, 2026 (phase 2 extract, kff_waiting_2026.json).
- BLS OEWS May 2024 and May 2025 state extracts (phase 1, oews_state_aides_2019_2025.json, oews_state_extract.json).
- CMS LTSS rebalancing measures, users and expenditures by age, 2023 (B1/B2 files, DQ Measures sheet).
- Census ACS 2023 1-year B19049_005E (live API pull in live_rerun_2026-11-23/data/Raw_ACS_v4.csv).

Script: /home/claude/audit/sens.py (re-implements GPI/MFI/quadrants from SYPA_Full_v5.csv and runs the three corrections).

## Fixes applied, 23 Nov 2026

Amin asked for the fixes to be made precisely. Done the same day:

- New engine `caredex/index_rebuild/index_engine.py` with the thesis formulas; `check_reproduces_thesis.py` confirms it reproduces the thesis output exactly from the thesis inputs (max difference 3e-14, 51/51 quadrants, sensitivity table 51/51).
- Corrected inputs in `index_inputs_2026-11-23.csv`: OEWS May 2025 median, P10 and employment (no floor); Census V2025 65+; MIT Feb 15 2026 for all 51 (18 states changed, exactly the 18 the code listed as still on 2025 data); HPAS from KFF 2026 by the stated rule; PHI 2025 training hours by a written rule (agency-employed PCA roles in Medicaid, lowest requirement; consumer-directed-only, non-agency and private-pay-only roles excluded); bottleneck from the headline MFI.
- Kept after checking: CMS 2023 rebalancing, AARP ADRC scores, CareScout 2024, ACS 2023 income.
- Result: 14 Double Bind, 12 Policy Bottleneck, 12 Market Failure, 13 High Performance (thesis 17/9/9/16); 15 states change quadrant (AL, AZ, AR, FL, GA, IL, ME, MO, NE, NM, OR, PA, RI, WI, WY); GPI-MFI Spearman 0.07 (thesis 0.248); 36 jurisdictions hold their quadrant in all 8 sensitivity variants.
- Site: sypaIndexData.ts, indexComponents.ts, needData.ts (PRECISION_RAW) regenerated; Index methods text, driver labels and freshness label rewritten to describe the sources and rules. Monitor reads the new results file.
- The thesis code is unchanged so it still reproduces the thesis; the repo README now says its hardcoded tables are wrong and points to the rebuild.
