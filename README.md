# Care Economy Index

Code for the three state-level indices in my Second Year Policy Analysis at Harvard Kennedy School:

> Karimi Dehnashi, A. (2026). *Breaking the Bad-Jobs Equilibrium: X3P as Industrial Policy in the U.S. Home Care Economy.* Second Year Policy Analysis, MPA/ID, Harvard Kennedy School. Advisor: Dani Rodrik. Section leader: Rema Hanna. March 2026.

The indices cover the 50 states and the District of Columbia:

- **Governance Pressure Index (GPI)**: strain on the public access channel for home care. Higher means more pressure.
- **Market Friction Index (MFI)**: strain on the private delivery market. Higher means more friction.
- **Pilot Readiness Index (PRI)**: where a platform-based pilot could run now, from a Feasibility score and an Opportunity score with a gate on both.

The method is in Section 4, Section 7 and Appendix III of the thesis. GPI, MFI and the quadrants are published on CareDex: https://caredex.vercel.app/dashboard/index

## Which file is which

| File | What it is |
|---|---|
| `SYPA_Complete_Pipeline.py` | The code behind the thesis (22 March 2026): GPI v4 (geometric mean of HCBS rebalancing and ADRC access, times a program-authority multiplier), MFI v5 (0.60 × MF2 + 0.40 × MF1, Mazziotta-Pareto), PRI v6 (√(F × O) with a bilateral 60th-percentile gate and an EVV gate). |
| `sypa_engine.py` | An earlier engine (PRI v3.2, January 2026). Kept for reference; it does not produce the thesis numbers. Its documentation is in `docs/LEGACY_sypa_engine.md`. |
| `results/offline_rerun_2026-11-23/` | Outputs of a rerun of the thesis code without network access (see below). |

## Running the thesis pipeline

Python 3.10 or later.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python SYPA_Complete_Pipeline.py --fast            # skip the sensitivity analysis
python SYPA_Complete_Pipeline.py                   # full run
python SYPA_Complete_Pipeline.py --guide           # how to update the hardcoded tables
```

Outputs go to `outputs/`: `SYPA_GPI_MFI_v5.csv`, `SYPA_PRI_v5.csv`, `SYPA_Full_v5.csv`, `SYPA_Validation_v5.csv`, `SYPA_HPAS_Appendix_III.csv` and `SYPA_Scatter_v5.png`.

The script fetches six sources live: BLS OEWS and LAUS, Census ACS 2023 (B19049, B28005), BEA regional price parities, the CMS LTSS rebalancing files, and the CareScout cost survey. API keys are optional (`BLS_API_KEY`, `CENSUS_KEY`, `BEA_KEY`). If a fetch fails, it falls back to local files in `data/`: `GPI_MFI.xlsx`, `B1_LTSSUsrRebalMeasr_2023.xlsx`, `B2_LTSSExpRebalMeasr_2023.xlsx`, `SARPP.xlsx`, `macro.xlsx`, `PHI.csv` and `ADRC NWD Functions.csv`. These input files are not in the repository. Check `run.log` to see which sources came live and which came from fallbacks.

## Reproduction status

A rerun on 23 November 2026 without network access, using the local fallbacks, gave these results:

| | Offline rerun, 23 Nov 2026 | Thesis |
|---|---|---|
| Quadrants (Double Bind / High Performance / Policy Bottleneck / Market Failure) | 17 / 16 / 9 / 9 | 17 / 16 / 9 / 9 |
| Oklahoma GPI, MFI | 0.37, 115.29 | 0.37, 115 |
| Maine GPI, MFI | 0.76, 98.57 | 0.76, 99 |
| Spearman ρ, GPI vs MFI | 0.248 | 0.248 |
| Partial ρ (RPP, unemployment, region) | −0.076 | −0.116 |
| PRI eligible states | AZ, HI, WI, MN, OH, MA, OR, NH, PA, OK, WA, GA | AZ, HI, MA, CO, MN, OH, OR, NH, GA, NV, WA, WI |

GPI, MFI and the quadrants reproduce. The PRI list does not, for a reason visible in the code. Without the Census fetch, the fallback has no broadband data for households aged 65 and over, so digital readiness is set to 0.635 for every state. That input carries 0.35 of the Feasibility weight, and a constant adds no information, so Feasibility is decided by the EVV, program-authority and GPI terms alone. The partial correlation differs because the RPP and unemployment controls also came from fallbacks (BEA 2023 file, `macro.xlsx`). A rerun with network access is needed to check the PRI list.

## Data sources

All inputs are public: CMS LTSS rebalancing measures, the ADRC / No Wrong Door functions assessment, BLS OEWS and LAUS, Census ACS, BEA regional price parities, the Genworth / CareScout cost of care survey, the MIT Living Wage Calculator, the PHI direct care workforce state index, the AARP LTSS Scorecard, and state EVV records. Hardcoded tables in the script say where each value came from and when.

## Limitations

State aggregates hide variation within states. Several inputs are hardcoded snapshots and change over time. The indices are the author's constructions for a policy analysis, not official statistics. Check the original sources before citing a single state's value.

## License

MIT. See `LICENSE`.
