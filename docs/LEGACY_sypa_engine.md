# Legacy engine: sypa_engine.py (PRI v3.2, January 2026)

> This is the original README of the earlier engine, kept for reference. The thesis results come from `SYPA_Complete_Pipeline.py`; see the main README.

A reproducible Python engine that builds two diagnostic indices for the U.S. care
economy at the state level (50 states + DC), plus an optional "Pilot Readiness"
overlay. It is designed for researchers, policy analysts, and operators who need
a transparent, auditable way to compare states on **governance pressure** and
**market friction** in long-term services and supports (LTSS) / home- and
community-based services (HCBS).

The engine ingests public data (AARP/CMS LTSS appendices, BLS wages, ACS
incomes, state cost surveys, etc.), standardizes and imputes it, and emits CSVs,
an Excel correlation audit, static PNGs, and interactive HTML dashboards.

> **Not affiliated with** any state or federal agency. Outputs are diagnostic,
> not prescriptive. Always validate against primary sources before citing.

---

## Table of contents

- [What this builds](#what-this-builds)
- [Conceptual model](#conceptual-model)
- [Installation](#installation)
- [Data inputs](#data-inputs)
- [Running the engine](#running-the-engine)
- [Outputs](#outputs)
- [Configuration & tuning](#configuration--tuning)
- [Methodology notes](#methodology-notes)
- [Sensitivity / robustness](#sensitivity--robustness)
- [Data sources](#data-sources)
- [Repository layout](#repository-layout)
- [Limitations](#limitations)
- [License](#license)

---

## What this builds

The engine produces three indices for each state:

1. **Governance Pressure Index (GPI)** — policy / system pressure. Captures how
   hard it is for a person to access and stay in home- and community-based
   care, driven by screening policy, LTSS rebalancing (users + expenditures),
   and access velocity (ADRC/NWD performance). Higher = worse.

2. **Market Friction Index (MFI)** — market / labor wedge. Captures how hard
   it is for the paid-care market to clear, combining cost burden on elders,
   the wage gap between direct-care wages and a local living wage, and the
   scarcity of home-health / personal-care aides. Higher = worse.

3. **Pilot Readiness Index (PRI v3.2)** — an operational overlay. Combines
   digital readiness (ACS S2801 smartphone + broadband), EVV (Electronic Visit
   Verification) regulatory openness, demand transparency (waitlist per 1k
   seniors), and the GPI/MFI signals to rank states by how feasible a pilot
   deployment is. Two flavors: `PRI_commercial_v3` and `PRI_policy_v3`.
   Higher = more pilot-ready.

States are assigned to one of four **quadrants** by GPI × MFI:

| Quadrant            | Story                                                           |
|---------------------|-----------------------------------------------------------------|
| Double Bind         | High policy + high market constraints                           |
| Policy Bottleneck   | Market workable; policy blocks access ("Squandered Opportunity")|
| Market Failure      | Policy tries; market still constrains care ("Tragic Heroes")    |
| High Performance    | Low pressure + low friction                                     |

A composite **Binding Intensity** metric (Euclidean distance of the positive
parts of GPI and MFI) ranks states by how badly *both* dimensions are binding.

---

## Conceptual model

The design deliberately **bifurcates** governance levers from market
constraints. Mixing them into a single score tends to hide where the
intervention should land (regulator vs. market), so the engine keeps them
separate and only reconnects them via the quadrant / Binding Intensity view.

**GPI components (weighted mean of z-scores)**

| Component        | Signal                                            | Weight |
|------------------|---------------------------------------------------|:------:|
| Pressure_Users   | 1 − share of LTSS *users* in HCBS (65+)           | 0.35   |
| Pressure_Exp     | 1 − share of LTSS *spending* on HCBS (65+)        | 0.35   |
| Screening        | State uses screening/waitlists                    | 0.15   |
| Access_Velocity  | 1 − ADRC/NWD overall performance                  | 0.15   |

**MFI components (Mazziotta–Pareto style: mean + λ·std of z-scores)**

| Component       | Signal                                           | Weight |
|-----------------|--------------------------------------------------|:------:|
| Cost_Burden     | log( annualized aide cost / median 65+ income )  | 1/3    |
| Wage_Gap        | log( living wage / direct-care wage )            | 1/3    |
| Labor_Scarcity  | log( 1 / aides per 1,000 seniors )               | 1/3    |

The non-compensatory MPI-style penalty (`MFI_mpi = mean + LAMBDA*std`, default
LAMBDA=1.0) means states with severe bottlenecks on one component can't hide
behind strong performance on another.

All proportions in `[0,1]` are logit-transformed before z-scoring to avoid
floor/ceiling artifacts. Z-scores are winsorized at ±2.5 SD.

---

## Installation

Requires Python 3.9+.

```bash
git clone https://github.com/aminkarimid/care-economy-index.git
cd care-economy-index
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

Optional: set a Census API key for the ACS S2801 digital-readiness pull
(unauthenticated access works for small batches but is rate-limited):

```bash
export CENSUS_API_KEY=your_key_here
```

---

## Data inputs

Place the following in a `data/` folder at the repo root.

### Required

| File                             | Purpose                                      |
|----------------------------------|----------------------------------------------|
| `GPI_MFI.xlsx`                   | Compiled workbook — state list, population, waitlists, cost, income, wages, employment, AARP overall |
| `B1_LTSSUsrRebalMeasr_2023.xlsx` | AARP Appendix B.1 — LTSS users in HCBS       |
| `B2_LTSSExpRebalMeasr_2023.xlsx` | AARP Appendix B.2 — LTSS expenditure in HCBS |

`GPI_MFI.xlsx` is expected to contain these sheets:

- `State_List`
- `Raw_UVA_2030` (population, 65+)
- `Raw_KFF_Waitlist`
- `Raw_CareCost`
- `Raw_ACS_Income65`
- `Raw_BLS_Wage`
- `Raw_LivingWage`
- `Raw_Employment`
- `Raw_AARP_HCBS`

Column names expected in each sheet are declared near the top of
`sypa_engine.py` in `SHEET_MAP` — easy to retarget if your column names differ.

### Optional (used automatically if present)

| File                                     | Purpose                                |
|------------------------------------------|----------------------------------------|
| `ADRC NWD Functions.csv`                 | Access velocity proxy                  |
| `SARPP.xlsx`                             | BEA regional price parities (diag.)    |
| `PHI.csv`                                | PHI direct-care workforce ranks        |
| `Affordability and Access .xlsx`         | AARP domain: affordability & access    |
| `Choice of Setting and Provider .xlsx`   | AARP domain: choice of setting         |
| `macro.xlsx`                             | Unemployment rate + macro controls     |
| `outputs/evv_regulatory_map.csv`         | EVV model + vendor portability (auto-generated if missing) |

---

## Running the engine

From the repo root:

```bash
# Full run — primary indices + PRI + correlation audit + sensitivity workbook
python sypa_engine.py

# Primary outputs only (skip robustness workbook)
python sypa_engine.py --skip-sensitivity

# Sensitivity workbook only (re-run robustness checks)
python sypa_engine.py --sensitivity

# Skip the Pilot Readiness overlay
python sypa_engine.py --skip-pri

# Force rebuild of the EVV regulatory map
python sypa_engine.py --build-evv-map
```

All flags have short aliases (`-x`, `-s`).

---

## Outputs

Written to `outputs/`:

| File                                       | Description                                          |
|--------------------------------------------|------------------------------------------------------|
| `SYPA_Final_Indices_GPI_MFI.csv`           | Master table — all components, indices, PRI columns |
| `SYPA_Correlation_Audit.xlsx`              | Pearson + Spearman validation against AARP/PHI/RPP   |
| `SYPA_Diagnostic_Scatter.png`              | Static quadrant scatter (matplotlib)                 |
| `SYPA_Diagnostic_Scatter.html`             | Interactive Plotly scatter with full hover detail    |
| `SYPA_Diagnostic_Scatter_65plus.html`      | Same scatter, bubble size = % population 65+         |
| `SYPA_Geographic_Map.html`                 | Choropleth: quadrant per state                       |
| `SYPA_PRI_v3_ranking.csv`                  | Full PRI table + ranks                               |
| `SYPA_PRI_v3_highBI_commercial.csv`        | High-Binding-Intensity states ranked by commercial PRI |
| `SYPA_PRI_v3_highBI_policy.csv`            | High-Binding-Intensity states ranked by policy PRI  |
| `SYPA_Sensitivity_Tests.xlsx`              | ~20-scenario robustness workbook                     |
| `evv_regulatory_map.csv`                   | State EVV model + vendor portability                 |

---

## Configuration & tuning

All tunable constants live at the top of `sypa_engine.py`:

- `GPI_WEIGHTS`, `MFI_WEIGHTS` — component weights (must sum to 1.0)
- `LAMBDA` — MPI non-compensatory penalty (default 1.0)
- `Z_CAP`, `Z_DDOF` — winsorization cap (SDs) and SD ddof
- `USE_LOGIT_FOR_REBAL`, `EPS` — logit transform for bounded shares
- `HOURS_PER_WEEK`, `WEEKS_PER_YEAR` — annualization assumptions for paid care
- `QUADRANT_SPLIT` — `"median"` (default), `"mean"`, or `"zero"`

The sensitivity harness automatically sweeps many of these and reports rank
stability (Spearman), Top-10 Binding-Intensity overlap, and quadrant-flip
counts vs. the baseline.

---

## Methodology notes

- **Higher = worse** for GPI and MFI. **Higher = better** for PRI.
- **No SciPy dependency.** Spearman correlation is computed as Pearson
  correlation of average ranks.
- **Imputation.** Missing numeric inputs are filled by Census-region median,
  then national median as a fallback. Missingness flags (`*_Missing`) are
  preserved for every imputed column.
- **Waitlist magnitude is kept OUTSIDE GPI and MFI.** State waitlist numbers
  are not comparable (policy, screening rules, administrative definitions
  differ). They are retained as diagnostics and used only in PRI as a "demand
  transparency" signal.
- **Macro-adjusted indices** (`GPI_weighted_adj`, `MFI_mpi_adj`) are computed
  by residualizing against unemployment and BEA Regional Price Parities via
  simple OLS. These are **sensitivity checks, not canonical outputs**.
- **Partial correlations** against AARP and PHI benchmarks are computed when
  macro controls are available.

---

## Sensitivity / robustness

`run_sensitivity_tests()` sweeps:

- GPI weight schemes (equal, pressure-heavy, balanced, no-access)
- MFI weight schemes (cost-, wage-, labor-heavy)
- `LAMBDA` ∈ {0.0, 0.5, 1.0, 1.5}
- `Z_CAP` ∈ {2.0, 2.5, 3.0} and `Z_DDOF` ∈ {0, 1, 2}
- Logit vs. linear rebalancing transform, alternate `EPS`
- Paid-care annualization (hours/week, weeks/year)
- Quadrant split rule

For each scenario it reports rank-correlation vs. the baseline, Top-10
Binding-Intensity overlap, and the number of states that change quadrants.
Results are written to `outputs/SYPA_Sensitivity_Tests.xlsx`.

---

## Data sources

All underlying data is public. You need to obtain files yourself from the
listed providers before running.

- **AARP LTSS Scorecard** (Appendix B.1, B.2, domain rank exports)
- **KFF** HCBS waitlist tracker
- **CMS / ADRC / No Wrong Door** functions tracker
- **U.S. Census Bureau ACS S2801** (smartphone + broadband shares)
- **BEA** Regional Price Parities (SARPP)
- **BLS OES** (aide wages, employment)
- **MIT Living Wage Calculator**
- **PHI** direct-care workforce state chartbook

---

## Repository layout

```
care-economy-index/
├── sypa_engine.py         # the engine
├── README.md              # this file
├── requirements.txt       # Python deps
├── LICENSE                # MIT
├── .gitignore
├── data/                  # place input files here (not tracked)
│   └── .gitkeep
└── outputs/               # generated artifacts (not tracked)
    └── .gitkeep
```

---

## Limitations

- State-level aggregates hide within-state variation (metros vs. rural).
- AARP LTSS appendices are released with a lag; figures reflect 2020–2023 data.
- EVV regulatory classifications are point-in-time and change frequently as
  states transition between vendors; re-check before acting.
- "Waitlist" magnitudes are intentionally not comparable across states and are
  treated only as a demand-transparency signal in PRI.
- Correlations with AARP/PHI benchmarks should be read as *validation* of
  relative ordering, not as claims about causal effect.
- Imputation by regional median is convenient but biases small states toward
  their regional peers; check the `*_Missing` flags before citing any single
  state's score.

---

## License

MIT — see [LICENSE](LICENSE).
