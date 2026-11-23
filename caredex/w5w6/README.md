# W5 and W6 source extracts, 23 Nov 2026

Extracted in the browser from the publishers' files; each hash below matched between the browser and the local copy (SHA-256 of the file as saved).

| File | Source | Content |
|---|---|---|
| oews_state_aides_2019_2025.json | BLS OEWS state files oesm19st.zip to oesm25st.zip | 31-1120 [employment, hourly median] by state and year. `oewsStateYear` in sources.mjs reproduces it (checked in the browser on bls.gov). |
| qwi_annual.json | LEHD QWI R2026Q4 state files (rh_f_gs_n4_op_u, rh_f_gs_ns_op_u) | Calendar-year mean TurnOvrS, 2019 to 2024, for 6216, 6241 and all industries; `qwiAnnual` output. The same download reproduced site_qwi.json exactly. |
| ep_matrix_31-1120.json | data.bls.gov National Employment Matrix, 31-1120 | Total, self-employed, wage and salary, 621600, 624120, 814000: 2025 and 2035, thousands; `epMatrixRows` output. |
| acs_b24114_2025_us.json | ACS 2025 1-year table-based summary file, acsdt1y2025-b24114.dat | U.S. row: all occupations, home health aides (line 244), personal care aides (line 245), estimates and MOEs; `acsRows` output. The file has no state rows. |
| cbp_raw.json | County Business Patterns 2023, cbp23st.zip and cbp23us.zip | 621610 and 624120, all legal forms: state employment, establishments, payroll; U.S. size classes. `cbpRows` reproduces the fields used. |

CBP 2024 was not on the Census server on 23 Nov 2026 (cbp24st.zip returned 404); the check probes for it.
