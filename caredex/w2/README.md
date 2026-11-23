# W2 register: Medicaid HCBS payment rate disclosures (42 CFR 447.203(b)(2)-(4)) against aide wages

Status 23 Nov 2026: 8 states entered (RI, PA, KY, MD, IL, NC, TX, CA partial). Register stopped at 8 by decision, see below.

## Decision, 23 Nov 2026 (rev 14 of the plan)
KFF published its 2026 Medicaid HCBS survey on 20 Nov 2026 with state-by-state average hourly rates (Appendix Table 4; 49 states plus DC responded, FL did not). The site's cross-state rate measure uses that table: one survey, one question, one definition (personal care agency average hourly rate). The disclosure register is kept as a check on KFF for 8 states and published as such. Reason: the disclosures are not comparable across states (TX reports an unweighted mean of 168 rates; IL files its elder in-home service as homemaker; CA splits across three agencies; MD includes a $93/hr code), and the 8-state check shows KFF and the disclosures within 13% in only 3 of 6 comparable states (NC, RI, KY). Extracting the other 43 disclosures would cost several sessions and would not yield a comparable number.
- kff_hcbs_rates_2026_appx4.tsv: Appendix Table 4 as served by datawrapper chart 5M0i2 v4 (dataset.csv), SHA-256 a321d2360b7d8fd006404df36a303ede0af1f8f3d335f2be54a95a4d39a30731.
- In this repository the rebuild is kffRates() and buildRates() in ../sources.mjs, checked monthly by ../check.mjs against ../expected/site_rates.json. The Python scripts that first built ratesData.ts (build_w2.py, make_ts.py) and reg.py stay in Amin's working folder, projects/GPI_MFI/w2_rates_2026-11-23.
- Disclosure sources located but not entered: CO (Google Drive xlsx linked from hcpf.colorado.gov/access-rule, id 10sPL6JNr-dmMVJGS2EwQf1a7-m6rEBgZ), UT (medicaid-documents.dhhs.utah.gov, Access Rule Comparative Payment Rate Analysis 6.24.26.pdf), CA DDS and CDSS. CT's access page posts only the E/M comparative analysis. NY and MA disclosure pages not found by search.

## Rule for each state
- Source: the state's own payment rate disclosure (due July 1, 2026; rates in effect July 1, 2025 or the period the state states). Record URL, title, SHA-256 of the file as downloaded, page.
- Personal care: rows in the personal care service category that pay in-home aide hours (respite, adult day, per-diem coordinated caregiving and case management rows excluded even when filed under personal care). Use agency rows; where the state does not split agency and individual providers, use the combined rows. Exclude individual-only rows.
- Home health aide: same rule. If the state's category mixes in nursing codes (RN/LPN), keep the value in the register but do not use it for the aide comparison (hha_use = false).
- Several rows (regions, populations, waivers): claims-weighted mean of the disclosed average hourly rates, using the paid-claims counts in the disclosure. If no counts are given, simple mean, flagged.
- Comparison wage: OEWS May 2025 state median for 31-1120 (already on the site). Wage share = median wage / average hourly rate.
- A second pass re-reads 10 random states from the files before publishing.

## Files
- register.json: one entry per state with verbatim rows used, weights and notes.
- pdftext.js: in-browser PDF text extractor (no third-party code), used on each state's own site.
