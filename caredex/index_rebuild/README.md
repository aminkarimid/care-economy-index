# Index rebuild, 23 November 2026

The GPI and MFI on CareDex are computed here, not by `SYPA_Complete_Pipeline.py`. An audit on 23 November 2026 found that several inputs hardcoded in the thesis pipeline did not trace to their sources. `index_engine.py` uses the pipeline's formulas (GPI v6, MFI v5, median quadrants) and reproduces its output exactly when given the thesis inputs (`check_reproduces_thesis.py`, largest difference 3e-14, 51 of 51 quadrants). `run_rebuild.py` runs it on the corrected inputs and writes `results/index_rebuild_2026-11-23/index_results_2026-11-23.csv`, the file the CareDex site and the monthly check read.

## Inputs (`index_inputs_2026-11-23.csv`)

| Column | Source | Status in the audit |
|---|---|---|
| HCBS_Users_Share, HCBS_Exp_Share | CMS LTSS rebalancing measures 2023, users and expenditures, age 65 and older (B.1.1, B.2.1) | Checked, kept. CMS rates HCBS data quality "High Concern" for some states. |
| ADRC_Share | AARP 2023 LTSS State Scorecard, ADRC/NWD Functions (self-reported 2022 survey, share of 41 criteria) | Kept; maximum (97%) and mean (72%) match AARP's published values. This is a functions score, not a measure of speed. |
| HPAS | KFF 2026, people waiting for Medicaid HCBS and whether states screen (`caredex/expected/kff_waiting_2026.json`). Rule: total waiting 0 → 0; waiting and no screening → 1; waiting and screening → 2. | Corrected. The thesis table disagreed with this rule for FL, IL, NE, NM, NY, RI, WA, WI. |
| Cost_Hourly | Genworth/CareScout 2024 Cost of Care Survey, home health aide median | Checked, kept. |
| Income_65plus | ACS 2023 1-year, B19049_005E | Checked, kept (equals a live Census API pull). |
| Wage_Aide, Aide_Count | BLS OEWS May 2025, SOC 31-1120, state median and employment (the values on CareDex) | Corrected. The thesis used May 2024 and raised LA, MS and TX to an $11.49 floor. |
| Pop_65plus | Census Vintage 2025 civilian population 65+ (the value on CareDex) | Corrected. The thesis used a 2030 projection. |
| Wage_Living | MIT Living Wage Calculator, 1 adult 0 children, data of 15 Feb 2026 (`mit_living_wage_2026-02-15.json`) | Corrected. The thesis mixed 2025 and 2026 releases (18 states on 2025). |
| Wage_P10, Wage_Median_for_P10 | BLS OEWS May 2025, SOC 31-1120, state 10th percentile and median | Corrected. The thesis values were estimates from minimum wages, not BLS data. |
| Training_Hours, Training_Roles | PHI, Personal Care Aide Training Requirements by State, 2025 (`phi_pca_training_2025.json`, every role with its scope and hours as printed). Rule: roles covering agency-employed workers in Medicaid (consumer-directed-only, non-agency and private-pay-only roles excluded); the lowest required hours among them; "No" = 0. | Corrected. The thesis table did not match PHI (e.g. MA, NY, WA coded 120; PHI: 60, 40, 75). |

The training gap is (120 − hours) / 120, floored at 0; 120 hours is the Institute of Medicine's recommended minimum for home health aides and nursing assistants. Since all formulas standardize each signal across states, the benchmark only matters for the two states at or above it (DC 125, RI 120).

Two thesis outputs came from the legacy MFI v4 function, which runs after MFI v5 and overwrites them: `MFI_bottleneck` (computed from PHI State Index ranks as proxies) and `MFI_rank` (the rank of MFI v4, not MFI v5). Here the bottleneck is the largest of the five headline MFI v5 components, as the code comment intends, and the results file gives MFI v5 rank ranges across the sensitivity variants instead of a single `MFI_rank`.

## Results

14 Double Bind, 12 Policy Bottleneck, 12 Market Failure, 13 High Performance (thesis: 17, 9, 9, 16). 15 states change quadrant. Spearman ρ between GPI and MFI: 0.07 (thesis 0.248). 36 jurisdictions keep their quadrant in all eight sensitivity variants (thesis inputs: 33).

The thesis text, its tables and the PRI were computed from the uncorrected inputs.
