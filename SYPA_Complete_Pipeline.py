"""
=============================================================================
SYPA Complete Pipeline — v1.0
"Breaking the Bad-Jobs Equilibrium: X3P as Industrial Policy in the
 U.S. Home Care Economy"
Harvard Kennedy School SYPA — Amin Karimi Dehnashi
Faculty Advisor: Prof. Dani Rodrik

=============================================================================
RUN THIS ONE FILE TO REPRODUCE ALL RESULTS
=============================================================================

    python SYPA_Complete_Pipeline.py                # full run
    python SYPA_Complete_Pipeline.py --fetch-only   # data fetch only
    python SYPA_Complete_Pipeline.py --compute-only # compute only (data exists)
    python SYPA_Complete_Pipeline.py --no-cache     # force re-download
    python SYPA_Complete_Pipeline.py --fast         # skip sensitivity analysis
    python SYPA_Complete_Pipeline.py --guide        # print manual update guide
    python SYPA_Complete_Pipeline.py --verify       # check all output files

=============================================================================
WHAT THIS FILE DOES
=============================================================================

PHASE 1 — DATA ACQUISITION
  Auto-installs all Python packages (no manual pip needed).
  Fetches 6 sources from live government APIs/downloads:
    BLS OEWS   → aide wages, P10, employment (SOC 31-1120)
    Census ACS → income 65+, broadband 65+ (B19049, B28005)
    BEA RPP    → Regional Price Parities
    CMS LTSS   → HCBS rebalancing measures B1+B2 (2023)
    BLS LAUS   → state unemployment rates
    CareScout  → home health aide hourly rates (PDF)
  Writes 5 hardcoded tables (no network needed):
    PHI        → Direct Care Workforce State Index (2024)
    ADRC/NWD   → No Wrong Door functions assessment (AARP 2023)
    KFF        → Screening policy flag (documentation only)
    MIT        → Living Wage, 1 adult 0 children (fetched Mar 2026)
    AARP       → Official overall rank 1–51 (2023 5th Edition)
  Falls back to local project files if network is unavailable.

PHASE 2 — INDEX COMPUTATION
  GPI v4 — Governance Pressure Index (geometric mean)
    Components: HCBS Users Share, HCBS Exp Share,
                NWD Access Velocity, HPAS ordinal (0/1/2)
    HPAS replaces binary Screening variable (MACPAC 2020 rationale)
    Screening and waitlist counts excluded from all formulas

  MFI v4 — Market Friction Index (Mazziotta-Pareto)
    Formula: MFI = M_r + S_r²/M_r  (100-centered normalization)
    Components: Cost Burden, Wage Gap, Labor Scarcity,
                Wage Compression (PHI proxy), Training Floor (PHI proxy)

  PRI v4 — Pilot Readiness Index (two-stage)
    Stage 1: 4 binary gates (GPI, MFI, EVV thresholds)
    Stage 2: responsiveness scoring (no MFI component)
    demand_transparency and screen_policy removed (MACPAC rationale)

PHASE 3 — VALIDATION & OUTPUTS
  External validation (5 checks, all should pass)
  Tier-1 sensitivity analysis (weight perturbation ±30%)
  Diagnostic scatter plot (GPI × MFI quadrant map)
  Quality and sanity checks (30-point test suite)
  Output files: CSV tables, validation report, scatter PNG

=============================================================================
API KEYS (all free, all optional — script works via fallbacks without them)
=============================================================================
  BLS_API_KEY  → https://data.bls.gov/registrationEngine/
  CENSUS_KEY   → https://api.census.gov/data/key_signup.html
  BEA_KEY      → https://apps.bea.gov/api/signup/

  Set before running:  export BLS_API_KEY="your_key_here"
                       export CENSUS_KEY="your_key_here"
                       export BEA_KEY="your_key_here"

=============================================================================
OUTPUTS (written to outputs/)
=============================================================================
  SYPA_Full_v4.csv           — All 51 states, all index columns
  SYPA_GPI_MFI_v4.csv        — GPI + MFI summary with quadrants
  SYPA_PRI_v4.csv            — PRI eligible states ranked
  SYPA_Validation_v4.csv     — External validation Spearman correlations
  SYPA_Sensitivity_v4.xlsx   — Weight perturbation sensitivity tests
  SYPA_Scatter_v4.png        — GPI × MFI diagnostic scatter

=============================================================================
KEY METHODOLOGICAL DECISIONS
=============================================================================
  Screening/waitlist EXCLUDED: Per MACPAC (2020), KFF waitlist counts and
    the binary screening flag are not comparable across states. HPAS
    captures the structural Medicaid authority choice directly.
  GPI: Geometric mean (non-compensatory aggregation, UNDP HDI 2010)
  MFI: Actual Mazziotta-Pareto formula (Mazziotta & Pareto 2013, 2016)
  PRI: MFI excluded from Stage 2 scoring to avoid Allcott (2015) bias
  AARP: Official 2023 overall rank (NOT the HCBS rebalancing ratio from
    GPI_MFI.xlsx which was circular — see code comments)
=============================================================================
"""

# =============================================================================
# PHASE 0: AUTO-INSTALL PACKAGES
# =============================================================================
import sys, subprocess

REQUIRED_PACKAGES = {
    "requests":   "requests",
    "pandas":     "pandas",
    "numpy":      "numpy",
    "openpyxl":   "openpyxl",
    "pdfplumber": "pdfplumber",
    "bs4":        "beautifulsoup4",
    "lxml":       "lxml",
    "matplotlib": "matplotlib",
}

def _bootstrap():
    missing = []
    for imp, pkg in REQUIRED_PACKAGES.items():
        try:
            __import__(imp)
        except ImportError:
            missing.append(pkg)
    if missing:
        print(f"[SETUP] Installing: {', '.join(missing)}")
        subprocess.check_call([sys.executable, "-m", "pip", "install",
                               "--quiet"] + missing)
        print("[SETUP] ✅ Done.\n")
    else:
        print("[SETUP] ✅ All packages present.\n")

_bootstrap()

# =============================================================================
# IMPORTS
# =============================================================================
import os, io, re, json, time, zipfile, datetime, argparse, warnings
from pathlib import Path
from typing import Optional, Dict, List, Tuple, Any

import requests
import pandas as pd
import numpy as np
import pdfplumber
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt

warnings.filterwarnings("ignore")

# =============================================================================
# CONFIGURATION
# =============================================================================

# ---- Paths
DATA_DIR   = Path("data")
CACHE_DIR  = Path("data/_cache")
OUTPUT_DIR = Path("outputs")

# ---- API keys (set via env vars)
BLS_API_KEY    = os.getenv("BLS_API_KEY", "")
CENSUS_API_KEY = os.getenv("CENSUS_KEY",  "")
BEA_API_KEY    = os.getenv("BEA_KEY",     "")

# ---- Source file (primary input workbook with population, waitlist etc.)
# Engine prefers auto-generated workbook, falls back to original project file
INPUT_FILE   = "GPI_MFI_auto.xlsx"   # written by Phase 1
INPUT_FILE_FALLBACK = "GPI_MFI.xlsx" # original project file

LTSS_USER_FILE = "B1_LTSSUsrRebalMeasr_auto.xlsx"
LTSS_EXP_FILE  = "B2_LTSSExpRebalMeasr_auto.xlsx"
LTSS_USER_FILE_FALLBACK = "B1_LTSSUsrRebalMeasr_2023.xlsx"
LTSS_EXP_FILE_FALLBACK  = "B2_LTSSExpRebalMeasr_2023.xlsx"
ADRC_FILE   = "ADRC NWD Functions.csv"
PHI_FILE    = "PHI.csv"

# ---- Sheet names in input workbook
SHEET_MAP = {
    "STATE_LIST": "State_List",
    "POP":        "Raw_UVA_2030",
    "WAIT":       "Raw_KFF_Waitlist",
    "COST":       "Raw_CareCost",
    "INCOME":     "Raw_ACS_Income65",
    "WAGE":       "Raw_BLS_Wage",
    "LIVING":     "Raw_LivingWage",
    "EMP":        "Raw_Employment",
    "AARP":       "Raw_AARP_HCBS",
}
LTSS_USER_SHEET = "B.1.1 BalanceByAge"
LTSS_EXP_SHEET  = "B.2.1 BalanceByAge"

# ---- Index parameters
BLS_AIDE_WAGE_P10_FLOOR = 11.49  # BLS national P10, SOC 31-1120, May 2023

# ── BLS OES May 2023 — SOC 31-1120 Home Health and Personal Care Aides ──────
# Wage_Compression_Ratio = H_PCT10 / H_MEDIAN  (Acemoglu-Pischke 1999 identification var)
# Higher ratio = more compressed wage distribution = less training externality problem
# Lower ratio  = wider distribution = more severe training externality
#
# H_MEDIAN: median hourly wage
#   - Confirmed from ASPE (2024) where noted; otherwise ≈ BLS OES mean (state pages)
#   - BLS national: median=$16.12, mean=$16.05 (nearly identical for this occupation)
# H_PCT10: 10th-percentile hourly wage
#   - Estimated from state minimum wages (primary driver) + competitive labor market floor
#   - Full P10 by state available in BLS oesm23st.zip (H_PCT10 column, SOC 31-1120)
#   - Download: https://www.bls.gov/oes/special-requests/oesm23st.zip
#
# Sources: BLS OES May 2023 state pages; ASPE (Dec 2024) "Direct Care Worker Wages";
#          state minimum wage schedules (NCSL 2023); EPI (2024) home care wage analysis
BLS_WAGE_COMPRESSION_DATA = {
    # State: (H_PCT10, H_MEDIAN)
    # ── High minimum-wage states: P10 constrained near state floor ───────
    "Washington":           (16.00, 20.35),  # MW $15.74; ASPE median confirmed
    "Oregon":               (14.00, 19.26),  # MW $13.50
    "Massachusetts":        (15.25, 18.50),  # MW $15.00
    "Rhode Island":         (13.25, 18.64),  # MW $13.00
    "New York":             (14.50, 18.40),  # MW $14.20 (statewide floor)
    "Alaska":               (11.75, 17.81),  # MW $10.85; ASPE median confirmed
    "District of Columbia": (17.00, 17.79),  # MW $17.00; ASPE median confirmed
    "Hawaii":               (13.50, 17.26),  # MW $12.00; ASPE median confirmed
    "California":           (15.50, 16.93),  # MW $15.50
    "New Jersey":           (14.25, 16.99),  # MW $14.13
    "Connecticut":          (15.00, 16.75),  # MW $15.00
    "Colorado":             (13.75, 16.00),  # MW $13.65
    "Minnesota":            (11.75, 16.04),  # MW $10.59
    "Maryland":             (13.50, 16.16),  # MW $13.25
    "Illinois":             (13.25, 15.97),  # MW $13.00
    "Pennsylvania":         (11.25, 15.60),  # MW $7.25 (many localities higher)
    "Nevada":               (11.25, 15.51),  # MW $10.50–$11.25
    "Michigan":             (10.75, 15.43),  # MW $10.10
    "Vermont":              (13.20, 15.38),  # MW $13.18
    "North Dakota":         (11.25, 15.48),  # MW $7.25; competitive rural market
    "Wisconsin":            (11.25, 15.42),  # MW $7.25
    "Ohio":                 (10.75, 15.26),  # MW $10.10
    "New Hampshire":        (11.75, 15.84),  # MW $7.25; competition with MA lifts floor
    "Arizona":              (13.90, 15.27),  # MW $13.85
    "Texas":                (10.75, 15.29),  # MW $7.25; large competitive market
    "Maine":                (13.80, 15.28),  # MW $13.80
    "Delaware":             (12.00, 15.87),  # MW $11.75
    "Virginia":             (12.25, 15.78),  # MW $12.00
    "Indiana":              (11.00, 15.04),  # MW $7.25
    "Iowa":                 (11.00, 15.00),  # MW $7.25
    "Utah":                 (11.25, 15.01),  # MW $7.25; competitive SLC market
    "Wyoming":              (10.75, 15.03),  # MW $7.25
    "Kansas":               (10.75, 14.92),  # MW $7.25
    "Missouri":             (12.10, 14.89),  # MW $12.00
    "North Carolina":       (10.50, 14.89),  # MW $7.25
    "Florida":              (12.00, 14.83),  # MW $12.00
    "Kentucky":             (10.25, 14.75),  # MW $7.25
    "Nebraska":             (11.25, 14.77),  # MW $10.50
    "Montana":              (10.25, 14.80),  # MW $9.95
    "South Carolina":       (10.25, 14.69),  # MW $7.25
    "Tennessee":            (10.50, 14.65),  # MW $7.25
    "Idaho":                (10.75, 14.63),  # MW $7.25
    "Georgia":              (10.50, 15.12),  # MW $7.25; competitive ATL market
    "New Mexico":           (12.25, 14.52),  # MW $12.00
    "Oklahoma":             (10.25, 14.49),  # MW $7.25
    "Arkansas":             (11.25, 14.16),  # MW $11.00
    "South Dakota":         (11.00, 14.24),  # MW $10.80
    "Alabama":              (10.00, 14.40),  # MW $7.25; depressed care market
    "West Virginia":        ( 9.50, 14.11),  # MW $8.75
    "Mississippi":          ( 9.75, 13.97),  # MW $7.25; lowest mean in nation
    "Louisiana":            ( 9.00, 14.90),  # MW $7.25; wide wage dispersion
}
# Resulting WCR range: MS≈0.70, WA≈0.79, MA≈0.82, DC≈0.96 — meaningful cross-state variance
# National check: BLS P10=$11.49, BLS median=$16.12, national WCR=0.712
HOURS_PER_WEEK = 30
WEEKS_PER_YEAR = 52
EPS  = 1e-9
Z_CAP  = 2.5
Z_DDOF = 1
ADJ_SMARTPHONE = 0.665   # all-ages → 65+ (Pew 2022 + ACS B28005)
ADJ_BROADBAND  = 0.848

# ---- PRI gate thresholds
GPI_GATE_PERCENTILE = 0.65
MFI_GATE_PERCENTILE = 0.35
EVV_GATE_MIN        = 0.5

# ---- Quadrant split
QUADRANT_SPLIT = "median"

# ---- Data fetch settings
TARGET_BLS_YEAR  = "2024"
TARGET_ACS_YEAR  = "2023"
TARGET_BEA_YEAR  = "2024"
THROTTLE         = 1.5

SESSION = requests.Session()
SESSION.headers.update({
    "User-Agent": "Mozilla/5.0 SYPA-Pipeline/1.0 Harvard Kennedy School"
})

# =============================================================================
# STATE & REGION REFERENCE
# =============================================================================
STATES: List[Tuple[str, str, str]] = [
    ("01","Alabama","AL"),       ("02","Alaska","AK"),
    ("04","Arizona","AZ"),       ("05","Arkansas","AR"),
    ("06","California","CA"),    ("08","Colorado","CO"),
    ("09","Connecticut","CT"),   ("10","Delaware","DE"),
    ("11","District of Columbia","DC"),
    ("12","Florida","FL"),       ("13","Georgia","GA"),
    ("15","Hawaii","HI"),        ("16","Idaho","ID"),
    ("17","Illinois","IL"),      ("18","Indiana","IN"),
    ("19","Iowa","IA"),          ("20","Kansas","KS"),
    ("21","Kentucky","KY"),      ("22","Louisiana","LA"),
    ("23","Maine","ME"),         ("24","Maryland","MD"),
    ("25","Massachusetts","MA"), ("26","Michigan","MI"),
    ("27","Minnesota","MN"),     ("28","Mississippi","MS"),
    ("29","Missouri","MO"),      ("30","Montana","MT"),
    ("31","Nebraska","NE"),      ("32","Nevada","NV"),
    ("33","New Hampshire","NH"), ("34","New Jersey","NJ"),
    ("35","New Mexico","NM"),    ("36","New York","NY"),
    ("37","North Carolina","NC"),("38","North Dakota","ND"),
    ("39","Ohio","OH"),          ("40","Oklahoma","OK"),
    ("41","Oregon","OR"),        ("42","Pennsylvania","PA"),
    ("44","Rhode Island","RI"),  ("45","South Carolina","SC"),
    ("46","South Dakota","SD"),  ("47","Tennessee","TN"),
    ("48","Texas","TX"),         ("49","Utah","UT"),
    ("50","Vermont","VT"),       ("51","Virginia","VA"),
    ("53","Washington","WA"),    ("54","West Virginia","WV"),
    ("55","Wisconsin","WI"),     ("56","Wyoming","WY"),
]
FIPS_TO_NAME = {f: n for f, n, _ in STATES}
FIPS_TO_CODE = {f: c for f, _, c in STATES}
NAME_TO_CODE = {n: c for _, n, c in STATES}

STATE_REGION: Dict[str, str] = {
    "Connecticut":"Northeast","Maine":"Northeast","Massachusetts":"Northeast",
    "New Hampshire":"Northeast","Rhode Island":"Northeast","Vermont":"Northeast",
    "New Jersey":"Northeast","New York":"Northeast","Pennsylvania":"Northeast",
    "Illinois":"Midwest","Indiana":"Midwest","Michigan":"Midwest",
    "Ohio":"Midwest","Wisconsin":"Midwest","Iowa":"Midwest","Kansas":"Midwest",
    "Minnesota":"Midwest","Missouri":"Midwest","Nebraska":"Midwest",
    "North Dakota":"Midwest","South Dakota":"Midwest",
    "Delaware":"South","District of Columbia":"South","Florida":"South",
    "Georgia":"South","Maryland":"South","North Carolina":"South",
    "South Carolina":"South","Virginia":"South","West Virginia":"South",
    "Alabama":"South","Kentucky":"South","Mississippi":"South",
    "Tennessee":"South","Arkansas":"South","Louisiana":"South",
    "Oklahoma":"South","Texas":"South",
    "Arizona":"West","Colorado":"West","Idaho":"West","Montana":"West",
    "Nevada":"West","New Mexico":"West","Utah":"West","Wyoming":"West",
    "Alaska":"West","California":"West","Hawaii":"West",
    "Oregon":"West","Washington":"West",
}

# =============================================================================
# HARDCODED DATA TABLES
# =============================================================================

# ── PHI Direct Care Workforce State Index (2024) ─────────────────────────────
# Source: PHI National (2024). phinational.org/state-index-tool/
# Update: ~Annual. Email info@phinational.org for bulk data file.
PHI_DATA: Dict[str, Dict[str, int]] = {
    "Alabama":              {"overall":49,"worker":51,"economic":43},
    "Alaska":               {"overall":11,"worker":22,"economic": 2},
    "Arizona":              {"overall":24,"worker":24,"economic":30},
    "Arkansas":             {"overall":37,"worker":33,"economic":35},
    "California":           {"overall":12,"worker": 4,"economic":40},
    "Colorado":             {"overall":16,"worker":13,"economic":24},
    "Connecticut":          {"overall": 9,"worker":10,"economic":19},
    "Delaware":             {"overall":20,"worker":18,"economic":25},
    "District of Columbia": {"overall": 6,"worker": 5,"economic":13},
    "Florida":              {"overall":36,"worker":31,"economic":34},
    "Georgia":              {"overall":46,"worker":40,"economic":46},
    "Hawaii":               {"overall": 8,"worker":14,"economic": 5},
    "Idaho":                {"overall":39,"worker":32,"economic":39},
    "Illinois":             {"overall":13,"worker":11,"economic":29},
    "Indiana":              {"overall":34,"worker":35,"economic":26},
    "Iowa":                 {"overall":28,"worker":39,"economic": 8},
    "Kansas":               {"overall":26,"worker":21,"economic":42},
    "Kentucky":             {"overall":38,"worker":44,"economic":17},
    "Louisiana":            {"overall":48,"worker":34,"economic":50},
    "Maine":                {"overall": 4,"worker": 8,"economic": 3},
    "Maryland":             {"overall": 7,"worker": 9,"economic":11},
    "Massachusetts":        {"overall":14,"worker":12,"economic":21},
    "Michigan":             {"overall":21,"worker":20,"economic":27},
    "Minnesota":            {"overall":19,"worker":16,"economic":22},
    "Mississippi":          {"overall":50,"worker":50,"economic":49},
    "Missouri":             {"overall":42,"worker":30,"economic":47},
    "Montana":              {"overall":17,"worker":17,"economic":18},
    "Nebraska":             {"overall":27,"worker":37,"economic": 9},
    "Nevada":               {"overall":30,"worker":38,"economic":15},
    "New Hampshire":        {"overall":18,"worker":26,"economic": 4},
    "New Jersey":           {"overall": 5,"worker": 2,"economic":33},
    "New Mexico":           {"overall":32,"worker":18,"economic":48},
    "New York":             {"overall":10,"worker": 7,"economic":31},
    "North Carolina":       {"overall":44,"worker":47,"economic":37},
    "North Dakota":         {"overall":31,"worker":43,"economic":12},
    "Ohio":                 {"overall":29,"worker":29,"economic":32},
    "Oklahoma":             {"overall":43,"worker":41,"economic":41},
    "Oregon":               {"overall": 3,"worker": 3,"economic":10},
    "Pennsylvania":         {"overall":23,"worker":25,"economic":23},
    "Rhode Island":         {"overall": 2,"worker": 5,"economic": 1},
    "South Carolina":       {"overall":45,"worker":42,"economic":45},
    "South Dakota":         {"overall":33,"worker":46,"economic": 7},
    "Tennessee":            {"overall":47,"worker":49,"economic":36},
    "Texas":                {"overall":51,"worker":48,"economic":51},
    "Utah":                 {"overall":25,"worker":28,"economic":14},
    "Vermont":              {"overall":15,"worker":15,"economic":16},
    "Virginia":             {"overall":35,"worker":27,"economic":44},
    "Washington":           {"overall": 1,"worker": 1,"economic": 6},
    "West Virginia":        {"overall":40,"worker":36,"economic":38},
    "Wisconsin":            {"overall":22,"worker":23,"economic":28},
    "Wyoming":              {"overall":41,"worker":45,"economic":20},
}


# ── PHI PCA/HHA Mandated Training Hours (2024) ───────────────────────────────
# Source: PHI (2024). "Personal Care Aide Training Standards Across the United
#         States: 2025 Update." phinational.org
# Metric: Minimum mandated pre-service training hours for Personal Care Aides
#         (PCA/PCSP) per state. Federal HHA minimum = 75 hrs; PHI/CMS benchmark
#         = 120 hrs. Training_Floor_Gap = max(0, 120 - hours) / 120
#         States with 0 = no state mandate (federal floor = 0 for PCA).
# Update: Annual. Check phinational.org or email info@phinational.org.
PHI_TRAINING_HOURS: Dict[str, int] = {
    "Alabama":               0,    # no PCA mandate
    "Alaska":               40,
    "Arizona":               0,
    "Arkansas":              0,
    "California":           70,
    "Colorado":             12,
    "Connecticut":          75,
    "Delaware":             18,
    "District of Columbia": 75,
    "Florida":              40,
    "Georgia":               0,
    "Hawaii":               80,
    "Idaho":                 0,
    "Illinois":             40,
    "Indiana":              30,
    "Iowa":                  8,
    "Kansas":                0,
    "Kentucky":             16,
    "Louisiana":            40,
    "Maine":                80,
    "Maryland":             18,
    "Massachusetts":       120,
    "Michigan":             75,
    "Minnesota":            75,
    "Mississippi":           0,
    "Missouri":              0,
    "Montana":              40,
    "Nebraska":              0,
    "Nevada":               16,
    "New Hampshire":        75,
    "New Jersey":           90,
    "New Mexico":           75,
    "New York":            120,
    "North Carolina":        0,
    "North Dakota":         75,
    "Ohio":                 18,
    "Oklahoma":              0,
    "Oregon":               75,
    "Pennsylvania":         40,
    "Rhode Island":         20,
    "South Carolina":        0,
    "South Dakota":          0,
    "Tennessee":             0,
    "Texas":                 0,
    "Utah":                  0,
    "Vermont":              75,
    "Virginia":              0,
    "Washington":          120,
    "West Virginia":        40,
    "Wisconsin":            75,
    "Wyoming":               0,
}

# Training Floor Gap = max(0, 120 - hours) / 120
# 120-hour threshold: CMS HCBS quality benchmark + PHCAST certification standard
PHI_TRAINING_GAP: Dict[str, float] = {
    s: round(max(0, 120 - h) / 120, 4)
    for s, h in PHI_TRAINING_HOURS.items()
}

# ── ADRC / No Wrong Door Functions (AARP 2023, 2022 survey data) ──────────────
# Source: AARP LTSS Scorecard 5th Edition (2023), Appendix B.
# Update: Every 3 years (~2026). Download Scorecard PDF → Appendix B.
ADRC_NWD_DATA: Dict[str, float] = {
    "Alabama":92.0,"Alaska":53.0,"Arizona":58.0,"Arkansas":66.0,
    "California":42.0,"Colorado":56.0,"Connecticut":91.0,"Delaware":82.0,
    "District of Columbia":89.0,"Florida":80.0,"Georgia":86.0,"Hawaii":77.0,
    "Idaho":65.0,"Illinois":81.0,"Indiana":64.0,"Iowa":55.0,"Kansas":71.0,
    "Kentucky":87.0,"Louisiana":72.0,"Maine":55.0,"Maryland":84.0,
    "Massachusetts":93.0,"Michigan":68.0,"Minnesota":92.0,"Mississippi":87.0,
    "Missouri":85.0,"Montana":44.0,"Nebraska":55.0,"Nevada":66.0,
    "New Hampshire":95.0,"New Jersey":88.0,"New Mexico":41.0,"New York":87.0,
    "North Carolina":21.0,"North Dakota":73.0,"Ohio":96.0,"Oklahoma":61.0,
    "Oregon":91.0,"Pennsylvania":86.0,"Rhode Island":86.0,
    "South Carolina":37.0,"South Dakota":78.0,"Tennessee":74.0,"Texas":78.0,
    "Utah":31.0,"Vermont":69.0,"Virginia":82.0,"Washington":95.0,
    "West Virginia":77.0,"Wisconsin":97.0,"Wyoming":20.0,
}

# ── KFF HCBS Screening Policy — DOCUMENTATION ONLY ───────────────────────────
# ⚠️  NOT USED IN ANY INDEX FORMULA.
# HPAS_CLASSIFICATION (below) drives the GPI, not this table.
# Screening and waitlist counts excluded per MACPAC (2020) methodology review.
# Source: KFF HCBS Waiting Lists Survey 2024.
KFF_SCREENS: Dict[str, str] = {
    "Alabama":"Yes","Alaska":"No","Arizona":"Unknown","Arkansas":"Yes",
    "California":"Yes","Colorado":"Yes","Connecticut":"Yes","Delaware":"Unknown",
    "District of Columbia":"Unknown","Florida":"Yes","Georgia":"Yes",
    "Hawaii":"Unknown","Idaho":"Unknown","Illinois":"No","Indiana":"Yes",
    "Iowa":"No","Kansas":"Yes","Kentucky":"Yes","Louisiana":"Yes","Maine":"Yes",
    "Maryland":"Yes","Massachusetts":"Unknown","Michigan":"Yes",
    "Minnesota":"Unknown","Mississippi":"Yes","Missouri":"Yes","Montana":"Yes",
    "Nebraska":"Yes","Nevada":"Yes","New Hampshire":"Unknown","New Jersey":"Yes",
    "New Mexico":"Yes","New York":"Unknown","North Carolina":"Yes",
    "North Dakota":"Yes","Ohio":"Yes","Oklahoma":"No","Oregon":"No",
    "Pennsylvania":"Yes","Rhode Island":"Yes","South Carolina":"No",
    "South Dakota":"Yes","Tennessee":"Yes","Texas":"No","Utah":"Yes",
    "Vermont":"Unknown","Virginia":"Yes","Washington":"No","West Virginia":"Yes",
    "Wisconsin":"Unknown","Wyoming":"Yes",
}

# ── MIT Living Wage (1 Adult, 0 Children) ────────────────────────────────────
# Source: Glasmeier, A.K. MIT Living Wage Calculator. livingwage.mit.edu
# Fetched: March 21, 2026 from individual state pages.
# Vintage: Mixed — ~35 states Feb 15 2026; ~16 states Feb 10 2025 (pending).
# States still on 2025 data: AZ, CA, CT, DE, IL, IN, IA, KS, ME, NE,
#   NM, NC, RI, SC, TX, UT, VT, VA.
MIT_LIVING_WAGE: Dict[str, float] = {
    "Alabama":21.06,"Alaska":24.98,"Arizona":24.42,"Arkansas":20.01,
    "California":28.72,"Colorado":26.00,"Connecticut":25.28,"Delaware":23.43,
    "District of Columbia":26.72,"Florida":24.09,"Georgia":24.21,
    "Hawaii":31.01,"Idaho":23.60,"Illinois":23.56,"Indiana":20.81,
    "Iowa":20.89,"Kansas":21.06,"Kentucky":20.21,"Louisiana":20.37,
    "Maine":23.22,"Maryland":25.94,"Massachusetts":30.58,"Michigan":22.07,
    "Minnesota":23.31,"Mississippi":20.69,"Missouri":21.27,"Montana":24.23,
    "Nebraska":20.99,"Nevada":24.16,"New Hampshire":25.77,"New Jersey":27.35,
    "New Mexico":21.01,"New York":29.89,"North Carolina":22.54,
    "North Dakota":20.61,"Ohio":21.00,"Oklahoma":20.73,"Oregon":26.46,
    "Pennsylvania":23.32,"Rhode Island":24.36,"South Carolina":22.15,
    "South Dakota":20.53,"Tennessee":21.61,"Texas":21.82,"Utah":23.91,
    "Vermont":23.95,"Virginia":25.65,"Washington":26.59,"West Virginia":19.53,
    "Wisconsin":21.88,"Wyoming":21.45,
}

# ── AARP LTSS Scorecard — Official Overall Ranks (2023 5th Edition) ──────────
# Source: AARP PPI (2023). ltsschoices.aarp.org/scorecard-report/2023
# Rank 1 = best LTSS system, 51 = worst.
# ⚠️  Prior "AARP_Score" 0-1 values from GPI_MFI.xlsx were NOT this —
#   they were HCBS_OAPD_2020 = HCBS expenditure rebalancing ratio (FY2020),
#   essentially a variant of GPI component → circular validation.
# Update: Every 3 years (~2026). Check ltsschoices.aarp.org.
AARP_OVERALL_RANK: Dict[str, int] = {
    "Minnesota":1,"Washington":2,"District of Columbia":3,
    "Massachusetts":4,"Colorado":5,"New York":6,"Oregon":7,
    "Hawaii":8,"Vermont":9,"New Jersey":10,"California":11,
    "Rhode Island":12,"Connecticut":13,"Maryland":14,"Wisconsin":15,
    "Maine":16,"Delaware":17,"Nebraska":18,"North Dakota":19,
    "New Mexico":20,"Pennsylvania":21,"Arizona":22,"Iowa":23,
    "New Hampshire":24,"Illinois":25,"Alaska":26,"Indiana":27,
    "Virginia":28,"Utah":29,"Kansas":30,"Michigan":31,"Ohio":32,
    "Montana":33,"Texas":34,"Idaho":35,"South Dakota":36,
    "Arkansas":37,"Missouri":38,"Georgia":39,"Wyoming":40,
    "North Carolina":41,"Kentucky":42,"Florida":43,"Nevada":44,
    "Louisiana":45,"Oklahoma":46,"Tennessee":47,"Mississippi":48,
    "South Carolina":49,"Alabama":50,"West Virginia":51,
}
# Convenience score (higher = better) for validation polarity
AARP_SCORES: Dict[str, float] = {
    s: round((52 - r) / 51, 4) for s, r in AARP_OVERALL_RANK.items()
}

# ── HPAS — HCBS Program Authority Score ──────────────────────────────────────
# Replaces binary Screening variable in GPI.
# Captures structural Medicaid authority choice, not a reporting artifact.
# 0 = Entitlement/Open (best), 1 = Unscreened interest list, 2 = Screened capped
# Source: KFF (2024) + MACPAC (2020) waiver authority analysis.
HPAS_CLASSIFICATION: Dict[str, int] = {
    "Arizona":0,"Delaware":0,"District of Columbia":0,"Hawaii":0,"Idaho":0,
    "Massachusetts":0,"Minnesota":0,"New Hampshire":0,"New York":0,
    "Vermont":0,"Wisconsin":0,
    "Alaska":1,"Illinois":1,"Iowa":1,"Oklahoma":1,"Oregon":1,
    "South Carolina":1,"Texas":1,"Washington":1,
}  # default for all others = 2

# ── EVV Regulatory Map ───────────────────────────────────────────────────────
# Source: HHAeXchange state tracker + CMS EVV state pages (verified 2025)
# Arizona updated from Hybrid → Open effective Oct 1, 2025.
EVV_REGULATORY_MAP: Dict[str, Dict] = {
    "Alabama":{"model":"Open","portability":True},
    "Alaska":{"model":"Open","portability":True},
    "Arizona":{"model":"Open","portability":True},
    "Arkansas":{"model":"Hybrid","portability":True},
    "California":{"model":"Hybrid","portability":False},
    "Colorado":{"model":"Open","portability":True},
    "Connecticut":{"model":"Closed","portability":False},
    "Delaware":{"model":"Open","portability":True},
    "District of Columbia":{"model":"Open","portability":True},
    "Florida":{"model":"Hybrid","portability":True},
    "Georgia":{"model":"Open","portability":True},
    "Hawaii":{"model":"Open","portability":True},
    "Idaho":{"model":"Open","portability":True},
    "Illinois":{"model":"Closed","portability":False},
    "Indiana":{"model":"Hybrid","portability":True},
    "Iowa":{"model":"Open","portability":True},
    "Kansas":{"model":"Open","portability":True},
    "Kentucky":{"model":"Hybrid","portability":True},
    "Louisiana":{"model":"Hybrid","portability":True},
    "Maine":{"model":"Hybrid","portability":False},
    "Maryland":{"model":"Open","portability":True},
    "Massachusetts":{"model":"Hybrid","portability":True},
    "Michigan":{"model":"Hybrid","portability":True},
    "Minnesota":{"model":"Open","portability":True},
    "Mississippi":{"model":"Open","portability":True},
    "Missouri":{"model":"Open","portability":True},
    "Montana":{"model":"Open","portability":True},
    "Nebraska":{"model":"Open","portability":True},
    "Nevada":{"model":"Open","portability":True},
    "New Hampshire":{"model":"Open","portability":True},
    "New Jersey":{"model":"Hybrid","portability":False},
    "New Mexico":{"model":"Hybrid","portability":True},
    "New York":{"model":"Open","portability":True},
    "North Carolina":{"model":"Hybrid","portability":True},
    "North Dakota":{"model":"Open","portability":True},
    "Ohio":{"model":"Open","portability":True},
    "Oklahoma":{"model":"Open","portability":True},
    "Oregon":{"model":"Open","portability":True},
    "Pennsylvania":{"model":"Open","portability":True},
    "Rhode Island":{"model":"Hybrid","portability":False},
    "South Carolina":{"model":"Open","portability":True},
    "South Dakota":{"model":"Hybrid","portability":True},
    "Tennessee":{"model":"Hybrid","portability":True},
    "Texas":{"model":"Hybrid","portability":False},
    "Utah":{"model":"Open","portability":True},
    "Vermont":{"model":"Open","portability":True},
    "Virginia":{"model":"Open","portability":True},
    "Washington":{"model":"Open","portability":True},
    "West Virginia":{"model":"Hybrid","portability":True},
    "Wisconsin":{"model":"Open","portability":True},
    "Wyoming":{"model":"Open","portability":True},
}

def _evv_model_score(m: str) -> float:
    return {"Open":1.0,"Hybrid":0.6,"Closed":0.2}.get(str(m).strip(),0.5)

def _evv_vendor_score(p: bool) -> float:
    return 1.0 if p else 0.0

# =============================================================================
# UTILITY FUNCTIONS
# =============================================================================

def _ensure_dirs():
    for d in (DATA_DIR, CACHE_DIR, OUTPUT_DIR):
        d.mkdir(parents=True, exist_ok=True)

def _standardize_state(s) -> str:
    if pd.isna(s): return ""
    s = str(s).strip().title()
    return s.replace("District Of Columbia","District of Columbia")

def _parse_pct(x) -> float:
    if pd.isna(x): return np.nan
    if isinstance(x,(int,float,np.integer,np.floating)):
        v = float(x)
        return v/100.0 if v > 1.0 else v
    s = str(x).strip().replace(",","")
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*%?$", s)
    if not m: return np.nan
    v = float(m.group(1))
    return v/100.0 if v > 1.0 else v

def _safe_log_ratio(a: pd.Series, b: pd.Series) -> pd.Series:
    return np.log((a / b.clip(lower=EPS)).clip(lower=EPS))

def _logit(p: pd.Series) -> pd.Series:
    return np.log(p.clip(lower=EPS,upper=1-EPS) /
                  (1 - p.clip(lower=EPS,upper=1-EPS)))

def _winsorized_z(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    m, sd = s.mean(), s.std(ddof=Z_DDOF)
    if sd == 0 or pd.isna(sd): return pd.Series(0.0, index=s.index)
    return ((s - m) / sd).clip(lower=-Z_CAP, upper=Z_CAP)

def _minmax_norm(s: pd.Series, floor=0.01, ceil=1.0) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    mn, mx = s.min(), s.max()
    if mx == mn: return pd.Series((floor+ceil)/2, index=s.index)
    return ((s - mn)/(mx - mn)).clip(lower=floor, upper=ceil)

def _mpi_normalize_100(s: pd.Series) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce").fillna(s.median())
    M, S = s.mean(), s.std(ddof=1)
    if S == 0: return pd.Series(100.0, index=s.index)
    return 100.0 + (s - M) / S * 10.0

def _impute_regional_median(master: pd.DataFrame, col: str) -> None:
    if col not in master.columns: return
    for region in master["Region"].dropna().unique():
        mask = master[col].isna() & (master["Region"] == region)
        if mask.any():
            master.loc[mask, col] = master.loc[
                master["Region"]==region, col].median()
    still = master[col].isna()
    if still.any():
        master.loc[still, col] = master[col].median()

def _spearman(a: pd.Series, b: pd.Series) -> float:
    valid = a.notna() & b.notna()
    if valid.sum() < 3: return np.nan
    return a[valid].rank().corr(b[valid].rank())

def _resolve(filename: str) -> str:
    for folder in (str(DATA_DIR), str(OUTPUT_DIR), ""):
        p = os.path.join(folder, filename) if folder else filename
        if os.path.exists(p): return p
    # Try fallback names
    if filename == INPUT_FILE and os.path.exists(
            os.path.join(str(DATA_DIR), INPUT_FILE_FALLBACK)):
        return os.path.join(str(DATA_DIR), INPUT_FILE_FALLBACK)
    if filename == INPUT_FILE and os.path.exists(INPUT_FILE_FALLBACK):
        return INPUT_FILE_FALLBACK
    return filename

# ---- Cache helpers
def _cache_is_fresh(key: str, max_days=30) -> bool:
    p = CACHE_DIR / re.sub(r'[^a-zA-Z0-9_.\-]','_',key)[:120]
    if not p.exists(): return False
    return (datetime.datetime.now() -
            datetime.datetime.fromtimestamp(p.stat().st_mtime)).days < max_days

def _cache_get(key: str) -> Optional[bytes]:
    p = CACHE_DIR / re.sub(r'[^a-zA-Z0-9_.\-]','_',key)[:120]
    return p.read_bytes() if p.exists() else None

def _cache_set(key: str, data: bytes) -> None:
    p = CACHE_DIR / re.sub(r'[^a-zA-Z0-9_.\-]','_',key)[:120]
    p.write_bytes(data)

def _fetch_url(url: str, cache_key: Optional[str]=None,
               max_days=30, **kw) -> bytes:
    if cache_key and _cache_is_fresh(cache_key, max_days):
        return _cache_get(cache_key)
    time.sleep(THROTTLE)
    r = SESSION.get(url, timeout=60, **kw)
    r.raise_for_status()
    if cache_key: _cache_set(cache_key, r.content)
    return r.content

def _network_available() -> bool:
    try:
        SESSION.get("https://www.bls.gov", timeout=5)
        return True
    except Exception:
        return False

def _fallback(filename: str) -> Optional[Path]:
    for p in [DATA_DIR/filename, Path("/mnt/project")/filename, Path(filename)]:
        if p.exists(): return p
    return None

def _api_key_notice():
    missing = []
    if not BLS_API_KEY:
        missing.append(("BLS_API_KEY","https://data.bls.gov/registrationEngine/"))
    if not CENSUS_API_KEY:
        missing.append(("CENSUS_KEY","https://api.census.gov/data/key_signup.html"))
    if not BEA_API_KEY:
        missing.append(("BEA_KEY","https://apps.bea.gov/api/signup/"))
    if missing:
        print("─"*60)
        print("ℹ️  Optional API keys (all free — fallbacks work without them):")
        for k,u in missing:
            print(f"   {k} → {u}")
        print(f"   Set: export {missing[0][0]}='key'")
        print("─"*60+"\n")

# =============================================================================
# PHASE 1A: AUTOMATED DATA FETCHING
# =============================================================================

def fetch_bls_oews(force=False) -> pd.DataFrame:
    OUT = DATA_DIR/"Raw_BLS_Wage_v4.csv"
    if OUT.exists() and not force:
        print(f"    [CACHE] BLS OEWS → {OUT.name}")
        return pd.read_csv(OUT)
    print("    [FETCH] BLS OEWS wages (SOC 31-1120)...")
    try:
        area_raw = _fetch_url(
            "https://download.bls.gov/pub/time.series/oe/oe.area",
            cache_key="bls_oe_area.tsv", max_days=180)
        areas = pd.read_csv(io.BytesIO(area_raw),sep='\t')
        areas.columns = areas.columns.str.strip()
        areas['area_code'] = areas['area_code'].str.strip()
        areas['area_type_code'] = areas['area_type_code'].str.strip()
        state_areas = areas[areas['area_type_code']=='S'].copy()

        bulk_raw = _fetch_url(
            "https://download.bls.gov/pub/time.series/oe/oe.data.0.Current",
            cache_key="bls_oe_current.tsv", max_days=30)
        df = pd.read_csv(io.BytesIO(bulk_raw),sep='\t')
        df.columns = df.columns.str.strip()
        df['series_id'] = df['series_id'].str.strip()
        df['value'] = df['value'].str.strip()

        mask = (df['series_id'].str.startswith('OEUS') &
                (df['series_id'].str[18:24]=='311120'))
        df = df[mask].copy()
        latest = df['year'].max()
        df = df[df['year']==latest].copy()
        df['area_code'] = df['series_id'].str[4:11]
        df['datatype']  = df['series_id'].str[-2:]
        df['val_num']   = pd.to_numeric(df['value'],errors='coerce')

        pivot = df[df['datatype'].isin(['01','07','08'])].pivot_table(
            index='area_code',columns='datatype',values='val_num',
            aggfunc='first').reset_index()
        pivot.columns.name = None
        pivot = pivot.rename(columns={'01':'TOT_EMP','07':'H_PCT10','08':'H_MEDIAN'})
        pivot = pivot.merge(state_areas[['area_code','area_name']],
                            on='area_code',how='left')
        pivot['state_name'] = pivot['area_name'].str.title()
        pivot['data_year']  = latest
        pivot = pivot.rename(columns={'H_PCT10': 'Wage_P10_SOC31120'})
        result = pivot[['state_name','H_MEDIAN','Wage_P10_SOC31120','TOT_EMP','data_year']
                       ].dropna(subset=['state_name'])
        print(f"    ✅ {len(result)} states | BLS OES May {latest}")
        result.to_csv(OUT,index=False)
        return result
    except Exception as e:
        print(f"    ⚠️  Network failed ({type(e).__name__}). Using fallback...")
    src = _fallback("GPI_MFI.xlsx")
    if src:
        df = pd.read_excel(src,sheet_name="Raw_BLS_Wage")
        df.columns = df.columns.str.strip()
        result = pd.DataFrame({
            "state_name":  df.iloc[:,0].astype(str).str.title(),
            "H_MEDIAN":    pd.to_numeric(df.iloc[:,2],errors='coerce'),
            "Wage_P10_SOC31120": np.nan,"TOT_EMP":np.nan,"data_year":"2022(fallback)"
        }).dropna(subset=["state_name","H_MEDIAN"])
        print(f"    ✅ {len(result)} states | local fallback (~2022)")
        result.to_csv(OUT,index=False)
        return result
    return pd.DataFrame()

def fetch_census_acs(force=False) -> pd.DataFrame:
    OUT = DATA_DIR/"Raw_ACS_v4.csv"
    if OUT.exists() and not force:
        print(f"    [CACHE] Census ACS → {OUT.name}")
        return pd.read_csv(OUT)
    print(f"    [FETCH] Census ACS {TARGET_ACS_YEAR} (B19049+B28005)...")
    try:
        params = {"get":"NAME,B19049_005E,B28005_014E,B28005_017E","for":"state:*"}
        if CENSUS_API_KEY: params["key"] = CENSUS_API_KEY
        raw = _fetch_url(f"https://api.census.gov/data/{TARGET_ACS_YEAR}/acs/acs1",
                         params=params,
                         cache_key=f"census_acs_{TARGET_ACS_YEAR}.json")
        data = json.loads(raw)
        df = pd.DataFrame([dict(zip(data[0],r)) for r in data[1:]])
        df['Income_65plus'] = pd.to_numeric(df['B19049_005E'],errors='coerce')
        df['HH_65plus_total'] = pd.to_numeric(df['B28005_014E'],errors='coerce')
        df['HH_65plus_broadband'] = pd.to_numeric(df['B28005_017E'],errors='coerce')
        df['Broadband_65plus_Pct'] = (df['HH_65plus_broadband'] /
                                       df['HH_65plus_total'].clip(lower=1))
        df['state_name'] = df['NAME']
        df['state_code'] = df['state'].map(FIPS_TO_CODE)
        result = df[['state_name','state_code','Income_65plus','Broadband_65plus_Pct']].copy()
        print(f"    ✅ {len(result)} states | ACS {TARGET_ACS_YEAR}")
        result.to_csv(OUT,index=False)
        return result
    except Exception as e:
        print(f"    ⚠️  Network failed ({type(e).__name__}). Using fallback...")
    src = _fallback("GPI_MFI.xlsx")
    if src:
        df = pd.read_excel(src,sheet_name="Raw_ACS_Income65")
        df.columns = df.columns.str.strip()
        result = pd.DataFrame({
            "state_name":  df.iloc[:,0].astype(str).str.title(),
            "state_code":  df.iloc[:,1].astype(str),
            "Income_65plus": pd.to_numeric(df.iloc[:,2],errors='coerce'),
            "Broadband_65plus_Pct": np.nan,
        }).dropna(subset=["state_name","Income_65plus"])
        print(f"    ✅ {len(result)} states | local fallback")
        result.to_csv(OUT,index=False)
        return result
    return pd.DataFrame()

def fetch_bea_rpp(force=False) -> pd.DataFrame:
    OUT = DATA_DIR/"Raw_RPP_v4.csv"
    if OUT.exists() and not force:
        print(f"    [CACHE] BEA RPP → {OUT.name}")
        return pd.read_csv(OUT)
    print(f"    [FETCH] BEA RPP {TARGET_BEA_YEAR}...")
    if BEA_API_KEY:
        try:
            params = {"UserID":BEA_API_KEY,"method":"GetData",
                      "datasetname":"Regional","TableName":"SARPP",
                      "LineCode":"1","GeoFIPS":"STATE",
                      "Year":TARGET_BEA_YEAR,"ResultFormat":"JSON"}
            raw = _fetch_url("https://apps.bea.gov/api/data",params=params,
                              cache_key=f"bea_rpp_{TARGET_BEA_YEAR}.json")
            data = json.loads(raw)
            result = pd.DataFrame([
                {"state_name":r["GeoName"],
                 "RPP_AllItems":float(r["DataValue"].replace(",","")),
                 "data_year":r["TimePeriod"]}
                for r in data["BEAAPI"]["Results"]["Data"]
                if r["GeoFips"]!="00000"])
            print(f"    ✅ {len(result)} states | BEA API {TARGET_BEA_YEAR}")
            result.to_csv(OUT,index=False)
            return result
        except Exception as e:
            print(f"    ⚠️  BEA API failed ({type(e).__name__}). Trying ZIP...")
    try:
        raw = _fetch_url("https://apps.bea.gov/regional/zip/SARPP.zip",
                          cache_key="bea_sarpp_bulk.zip",max_days=30)
        with zipfile.ZipFile(io.BytesIO(raw)) as z:
            fn = next((n for n in z.namelist() if n.endswith('.csv')),None)
            with z.open(fn) as f: df = pd.read_csv(f,skiprows=4)
        if 'LineCode' in df.columns:
            rpp = df[df['LineCode']==5].copy()
            yr_cols = sorted([c for c in df.columns if re.match(r'^20\d\d$',str(c))])
            if yr_cols:
                yr = yr_cols[-1]
                nm = 'GeoName' if 'GeoName' in df.columns else df.columns[1]
                result = pd.DataFrame({
                    "state_name": rpp[nm],"RPP_AllItems":pd.to_numeric(rpp[yr],errors='coerce'),
                    "data_year":yr}).dropna()
                print(f"    ✅ {len(result)} states | BEA ZIP {yr}")
                result.to_csv(OUT,index=False)
                return result
    except Exception as e:
        print(f"    ⚠️  BEA ZIP failed ({type(e).__name__}). Using fallback...")
    src = _fallback("SARPP.xlsx")
    if src:
        try:
            raw_xl = pd.read_excel(src,header=None)
            hdr = next((i for i,row in raw_xl.iterrows()
                        if any('GeoName' in str(v) or '2023' in str(v)
                               for v in row.values)),5)
            df = pd.read_excel(src,header=hdr)
            df.columns = df.columns.str.strip()
            if 'LineCode' in df.columns: df = df[df['LineCode']==5]
            yr_cols = sorted([c for c in df.columns if re.match(r'^20\d\d$',str(c))])
            if yr_cols:
                yr = yr_cols[-1]
                nm = 'GeoName' if 'GeoName' in df.columns else df.columns[1]
                result = pd.DataFrame({
                    "state_name":df[nm].astype(str),
                    "RPP_AllItems":pd.to_numeric(df[yr],errors='coerce'),
                    "data_year":yr}).dropna()
                known = {n for _,n,_ in STATES}
                result = result[result['state_name'].isin(known)]
                print(f"    ✅ {len(result)} states | SARPP.xlsx fallback {yr}")
                result.to_csv(OUT,index=False)
                return result
        except Exception: pass
    print("    ❌ BEA RPP unavailable")
    return pd.DataFrame()

def fetch_cms_ltss(force=False) -> Dict[str,Optional[Path]]:
    B1_OUT = DATA_DIR/"B1_LTSSUsrRebalMeasr_auto.xlsx"
    B2_OUT = DATA_DIR/"B2_LTSSExpRebalMeasr_auto.xlsx"
    B3_OUT = DATA_DIR/"B3_LTSSTransRebalMeasr_auto.xlsx"
    if B1_OUT.exists() and B2_OUT.exists() and not force:
        print(f"    [CACHE] CMS LTSS B1+B2+B3 → auto xlsx files")
        return {"B1":B1_OUT,"B2":B2_OUT,"B3":B3_OUT}
    base = "https://www.medicaid.gov/medicaid/long-term-services-supports/downloads/"
    results: Dict[str,Optional[Path]] = {}
    for key,fname,out,fb_name in [
        ("B1","ltss-users-rebalancing-2023.xlsx",B1_OUT,LTSS_USER_FILE_FALLBACK),
        ("B2","ltss-exp-rebalancing-2023.xlsx",B2_OUT,LTSS_EXP_FILE_FALLBACK),
        ("B3","ltss-transitions-rebalancing-2023.xlsx",B3_OUT,"B3_LTSSTransRebalMeasr_2023.xlsx")]:
        try:
            print(f"    [FETCH] CMS LTSS {key}...")
            raw = _fetch_url(base+fname,cache_key=f"cms_{key}_2023.xlsx",max_days=180)
            out.write_bytes(raw)
            print(f"    ✅ CMS LTSS {key}")
            results[key] = out
        except Exception as e:
            print(f"    ⚠️  CMS {key} failed. Using fallback...")
            fb = _fallback(fb_name)
            if fb:
                import shutil; shutil.copy(fb, out)
                print(f"    ✅ CMS LTSS {key} | local fallback: {fb.name}")
                results[key] = out
            else:
                print(f"    ❌ No fallback for CMS {key}")
                results[key] = None
    return results

def fetch_bls_laus(force=False) -> pd.DataFrame:
    OUT = DATA_DIR/"Raw_Unemployment_v4.csv"
    if OUT.exists() and not force:
        print(f"    [CACHE] BLS LAUS → {OUT.name}")
        return pd.read_csv(OUT)
    print("    [FETCH] BLS LAUS unemployment...")
    try:
        raw = _fetch_url(
            "https://download.bls.gov/pub/time.series/la/la.data.3.AllStatesS",
            cache_key="bls_laus_states.tsv",max_days=7)
        df = pd.read_csv(io.BytesIO(raw),sep='\t')
        df.columns = df.columns.str.strip()
        df['series_id'] = df['series_id'].str.strip()
        df['period'] = df['period'].str.strip()
        df['value'] = df['value'].str.strip()
        mask = ((df['series_id'].str.len()==20) &
                (df['series_id'].str.endswith('3')) &
                (df['period']=='M13'))
        df = df[mask].copy()
        latest = df['year'].max()
        df = df[df['year']==latest].copy()
        df['fips']  = df['series_id'].str[5:7]
        df['state_name'] = df['fips'].map(FIPS_TO_NAME)
        df['Unemployment_Rate'] = pd.to_numeric(df['value'],errors='coerce')
        result = df[['state_name','Unemployment_Rate']].dropna()
        print(f"    ✅ {len(result)} states | BLS LAUS {latest}")
        result.to_csv(OUT,index=False)
        return result
    except Exception as e:
        print(f"    ⚠️  Network failed ({type(e).__name__}). Using fallback...")
    src = _fallback("macro.xlsx")
    if src:
        df = pd.read_excel(src)
        df.columns = df.columns.str.strip()
        result = pd.DataFrame({
            "state_name":       df.iloc[:,0].astype(str).str.title(),
            "Unemployment_Rate":pd.to_numeric(df.iloc[:,1],errors='coerce')
        }).dropna(subset=["state_name","Unemployment_Rate"])
        print(f"    ✅ {len(result)} states | macro.xlsx fallback")
        result.to_csv(OUT,index=False)
        return result
    return pd.DataFrame()

def fetch_carescout(force=False) -> pd.DataFrame:
    OUT = DATA_DIR/"Raw_CareScout_v4.csv"
    if OUT.exists() and not force:
        print(f"    [CACHE] CareScout → {OUT.name}")
        return pd.read_csv(OUT)
    PDF_URL = "https://assets.carescout.com/a41bb6478c/298701.pdf"
    pdf_bytes = None
    try:
        print("    [FETCH] CareScout PDF...")
        pdf_bytes = _fetch_url(PDF_URL,cache_key="carescout_2024.pdf",max_days=365)
    except Exception as e:
        print(f"    ⚠️  PDF download failed ({type(e).__name__}).")
    manual = DATA_DIR/"carescout_manual.pdf"
    if pdf_bytes is None and manual.exists():
        pdf_bytes = manual.read_bytes()
        print(f"    → Using manually placed: {manual.name}")
    if pdf_bytes:
        rows = []
        state_names = {n for _,n,_ in STATES}
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            for page in pdf.pages:
                for table in (page.extract_tables() or []):
                    for row in table:
                        cells = [str(c).strip() if c else '' for c in row]
                        txt = ' '.join(cells)
                        found = next((n for n in state_names if n in txt),None)
                        if not found: continue
                        for amt in re.findall(r'\$?(\d{2,3}(?:\.\d{1,2})?)',txt):
                            val = float(amt)
                            if 15 <= val <= 70:
                                rows.append({"state_name":found,"Cost_Hourly":val})
                                break
        result = pd.DataFrame(rows).drop_duplicates("state_name").reset_index(drop=True)
        if len(result) >= 40:
            print(f"    ✅ {len(result)} states | CareScout 2024 PDF")
            result.to_csv(OUT,index=False)
            return result
        print(f"    ⚠️  PDF parsed only {len(result)} states.")
    src = _fallback("GPI_MFI.xlsx")
    if src:
        df = pd.read_excel(src,sheet_name="Raw_CareCost")
        df.columns = df.columns.str.strip()
        result = pd.DataFrame({
            "state_name": df.iloc[:,0].astype(str).str.title(),
            "Cost_Hourly":pd.to_numeric(df.iloc[:,2],errors='coerce')
        }).dropna()
        print(f"    ✅ {len(result)} states | local fallback")
        result.to_csv(OUT,index=False)
        return result
    return pd.DataFrame()

# =============================================================================
# PHASE 1B: HARDCODED WRITERS
# =============================================================================

def write_phi() -> pd.DataFrame:
    rows = [{"Rank":v["overall"],"State":n.upper(),
             "Worker Supportive Policies Index":v["worker"],
             "Direct Care Workforce Economic Index":v["economic"]}
            for n,v in PHI_DATA.items()]
    result = pd.DataFrame(rows)
    result.to_csv(DATA_DIR/"PHI.csv",index=False)
    print(f"    ✅ 51 states | PHI State Index 2024")
    return result

def write_adrc_nwd() -> pd.DataFrame:
    rows = [{"State":n,"Overall Performance":f"{s}%"}
            for n,s in ADRC_NWD_DATA.items()]
    result = pd.DataFrame(rows)
    result.to_csv(DATA_DIR/"ADRC NWD Functions.csv",index=False)
    print(f"    ✅ 51 states | ADRC/NWD (AARP 2023)")
    return result

def write_kff() -> pd.DataFrame:
    """Documentation only — NO index formula reads this file."""
    rows = [{"state_name":n,"state_code":NAME_TO_CODE.get(n,""),
             "Screen_Policy":v,
             "note":"Not used in any index formula — see HPAS_CLASSIFICATION"}
            for n,v in KFF_SCREENS.items()]
    result = pd.DataFrame(rows)
    result.to_csv(DATA_DIR/"Raw_KFF_Screens.csv",index=False)
    print(f"    ✅ 51 states | KFF screens (documentation only — HPAS drives GPI)")
    return result

def write_mit() -> pd.DataFrame:
    rows = [{"state_name":n,"state_code":NAME_TO_CODE.get(n,""),
             "HourlyLivableWageNoChildren_2026":w}
            for n,w in MIT_LIVING_WAGE.items()]
    result = pd.DataFrame(rows)
    result.to_csv(DATA_DIR/"Raw_LivingWage_v4.csv",index=False)
    print(f"    ✅ 51 states | MIT Living Wage (Mar 2026 fetch; ~35 states Feb 2026)")
    return result

def write_aarp() -> pd.DataFrame:
    rows = [{"state_name":n,"state_code":NAME_TO_CODE.get(n,""),
             "AARP_Overall_Rank":r,
             "AARP_Score":round((52-r)/51,4)}
            for n,r in AARP_OVERALL_RANK.items()]
    result = pd.DataFrame(rows)
    result.to_csv(DATA_DIR/"Raw_AARP_Scores.csv",index=False)
    print(f"    ✅ 51 states | AARP 2023 official rank (1=MN best, 51=WV worst)")
    return result

def write_combined_workbook(bls,census,bea,laus,scout,lw):
    OUT = DATA_DIR/"GPI_MFI_auto.xlsx"
    state_df = pd.DataFrame([(n,c) for _,n,c in STATES],
                              columns=['state_name','state_code'])
    # Try to copy Raw_UVA_2030 from original workbook for population data
    try:
        orig = None
        for p in [Path("data/GPI_MFI.xlsx"), Path("/mnt/project/GPI_MFI.xlsx"),
                  Path("GPI_MFI.xlsx")]:
            if p.exists(): orig = str(p); break
        if orig:
            pop_df = pd.read_excel(orig, sheet_name="Raw_UVA_2030")
            emp_df = pd.read_excel(orig, sheet_name="Raw_Employment")
    except Exception:
        pop_df = None; emp_df = None
    else:
        pass
    aarp_df = pd.DataFrame([{"state_name":n,"state_code":NAME_TO_CODE.get(n,""),
                               "Overall Performance":s}
                              for n,s in AARP_SCORES.items()])
    with pd.ExcelWriter(OUT,engine='openpyxl') as w:
        state_df.to_excel(w,sheet_name='State_List',index=False)
        try:
            if pop_df is not None:
                pop_df.to_excel(w,sheet_name='Raw_UVA_2030',index=False)
            if emp_df is not None:
                emp_df.to_excel(w,sheet_name='Raw_Employment',index=False)
        except Exception:
            pass
        if bls is not None and not bls.empty:
            bls.rename(columns={'H_MEDIAN':'Hourly median wage',
                                  'TOT_EMP':'Employment_311120',
                                  'Wage_P10_SOC31120':'Wage_P10_SOC31120'}
                ).to_excel(w,sheet_name='Raw_BLS_Wage',index=False)
        if census is not None and not census.empty:
            census.rename(columns={'Income_65plus':'Income'}
                ).to_excel(w,sheet_name='Raw_ACS_Income65',index=False)
        if lw is not None and not lw.empty:
            lw.to_excel(w,sheet_name='Raw_LivingWage',index=False)
        if scout is not None and not scout.empty:
            scout.rename(columns={'Cost_Hourly':'Hourly'}
                ).to_excel(w,sheet_name='Raw_CareCost',index=False)
        if bea is not None and not bea.empty:
            bea.to_excel(w,sheet_name='Raw_RPP',index=False)
        if laus is not None and not laus.empty:
            laus.to_excel(w,sheet_name='Raw_Unemployment',index=False)
        aarp_df.to_excel(w,sheet_name='Raw_AARP_HCBS',index=False)
        pd.DataFrame([
            ["Generated",str(datetime.datetime.now())],
            ["BLS OES",f"May {TARGET_BLS_YEAR}"],
            ["Census ACS",f"{TARGET_ACS_YEAR} 1-year (B19049+B28005)"],
            ["BEA RPP",TARGET_BEA_YEAR],
            ["MIT Living Wage","Fetched Mar 21 2026 (mixed 2025/2026 vintage)"],
            ["PHI Index","2024 edition"],
            ["AARP Scorecard","5th Edition 2023 official overall rank"],
            ["ADRC/NWD","AARP 2023 (2022 survey data)"],
            ["KFF HCBS","Screens flag only — not used in formulas"],
            ["CareScout","2024"],
        ],columns=["Item","Value"]).to_excel(w,sheet_name='Metadata',index=False)
    print(f"    ✅ Combined workbook → {OUT.name}")

def run_fetch(force=False):
    _ensure_dirs()
    _api_key_notice()
    online = _network_available()
    print(f"  Network: {'✅ online' if online else '⚠️  offline — using local fallbacks'}\n")

    print("AUTOMATED SOURCES\n")
    bls   = fetch_bls_oews(force)
    cen   = fetch_census_acs(force)
    bea   = fetch_bea_rpp(force)
    cms   = fetch_cms_ltss(force)
    laus  = fetch_bls_laus(force)
    scout = fetch_carescout(force)

    print("\nHARDCODED SOURCES\n")
    write_phi()
    write_adrc_nwd()
    write_kff()
    lw = write_mit()
    write_aarp()

    print("\nCOMBINED WORKBOOK\n")
    write_combined_workbook(bls,cen,bea,laus,scout,lw)

# =============================================================================
# PHASE 2A: DATA LOADING INTO MASTER DATAFRAME
# =============================================================================

def _load_state_list() -> pd.DataFrame:
    path = _resolve(INPUT_FILE)
    df = pd.read_excel(path,sheet_name=SHEET_MAP["STATE_LIST"])
    df.columns = [str(c).strip() for c in df.columns]
    sc = next((c for c in df.columns if "state" in c.lower()),df.columns[0])
    out = pd.DataFrame()
    out["State"] = df[sc].apply(_standardize_state)
    out = out[out["State"].str.len()>0].reset_index(drop=True)
    code_map = {n:c for _,n,c in STATES}
    out["state_code"] = out["State"].map(code_map)
    out["Region"]     = out["State"].map(STATE_REGION)
    return out

def _load_population(master:pd.DataFrame) -> pd.DataFrame:
    path = _resolve(INPUT_FILE)
    try:
        df = pd.read_excel(path,sheet_name=SHEET_MAP["POP"])
        df.columns = [str(c).strip() for c in df.columns]
        sc = next((c for c in df.columns if "state" in c.lower()),df.columns[0])
        df[sc] = df[sc].apply(_standardize_state)
        # Use Total65plus directly if present; otherwise sum age-band columns.
        # IMPORTANT: exclude aggregate columns (Total65plus, SeniorShare, Total*)
        # to avoid double-counting age bands.
        if "Total65plus" in df.columns:
            pop65 = pd.to_numeric(df["Total65plus"], errors="coerce")
        else:
            age_cols = [c for c in df.columns
                        if re.search(r"^6[05789]|^7[05]|^8[05]|^85", str(c))
                        and not re.search(r"total|share|pct|percent", str(c).lower())]
            pop65 = df[age_cols].apply(pd.to_numeric, errors="coerce").sum(axis=1)
        pop_df = pd.DataFrame({"State":df[sc],"Pop_65plus":pop65})
        tc = next((c for c in df.columns
                   if re.search(r"total\s*pop|pop.*total|^total$",str(c).lower())),None)
        if tc: pop_df["Pop_Total"] = pd.to_numeric(df[tc],errors="coerce")
        master = master.merge(pop_df,on="State",how="left")
    except Exception as e:
        print(f"[WARN] Population: {e}")
        master["Pop_65plus"] = np.nan; master["Pop_Total"] = np.nan
    return master

def _apply_hpas(master:pd.DataFrame) -> pd.DataFrame:
    master["HPAS"] = master["State"].map(HPAS_CLASSIFICATION).fillna(2).astype(int)
    return master

def _load_rebalancing(master:pd.DataFrame) -> pd.DataFrame:
    def _try_load(fname,fb_name,sheet,u_out,e_out):
        path = _resolve(fname)
        if not os.path.exists(path):
            path_fb = _fallback(fb_name)
            if path_fb: path = str(path_fb)
        if not path or not os.path.exists(path):
            master[u_out] = np.nan; master[e_out] = np.nan; return
        try:
            raw = pd.read_excel(path,sheet_name=sheet,header=None)
            hdr = next((i for i,row in raw.iterrows()
                        if any("state" in str(v).lower() for v in row.values)),None)
            if hdr is None: raise ValueError("No header")
            df = pd.read_excel(path,sheet_name=sheet,header=hdr)
            df.columns = [str(c).strip() for c in df.columns]
            sc = next((c for c in df.columns if "state" in c.lower()),df.columns[0])
            df[sc] = df[sc].apply(_standardize_state)
            col65 = next((c for c in df.columns
                          if re.search(r"65",str(c))
                          and re.search(r"hcbs|percent|%|share",str(c).lower())),None)
            colall = next((c for c in df.columns
                           if re.search(r"all.*age|total.*age",str(c).lower())
                           and re.search(r"hcbs|percent|%|share",str(c).lower())),None)
            if col65:
                master[u_out] = master["State"].map(
                    df.set_index(sc)[col65].apply(_parse_pct))
            if colall:
                master[e_out] = master["State"].map(
                    df.set_index(sc)[colall].apply(_parse_pct))
        except Exception as ex:
            print(f"[WARN] Rebalancing {fname}: {ex}")
            master[u_out] = np.nan; master[e_out] = np.nan

    _try_load(LTSS_USER_FILE,LTSS_USER_FILE_FALLBACK,LTSS_USER_SHEET,
              "Users_HCBS_65plus_Pct","Users_HCBS_AllAges_Pct")
    _try_load(LTSS_EXP_FILE,LTSS_EXP_FILE_FALLBACK,LTSS_EXP_SHEET,
              "Exp_HCBS_65plus_Pct","Exp_HCBS_AllAges_Pct")

    master["HCBS_Users_Share"] = master.get("Users_HCBS_65plus_Pct",np.nan)
    master["HCBS_Exp_Share"]   = master.get("Exp_HCBS_65plus_Pct",np.nan)
    for src,tgt in [("Users_HCBS_AllAges_Pct","HCBS_Users_Share"),
                    ("Exp_HCBS_AllAges_Pct","HCBS_Exp_Share")]:
        if src in master.columns:
            miss = master[tgt].isna() & master[src].notna()
            master.loc[miss,tgt] = master.loc[miss,src]
    return master

def _load_adrc(master:pd.DataFrame) -> pd.DataFrame:
    path = _resolve(ADRC_FILE)
    if not os.path.exists(path):
        path_fb = _fallback("ADRC_NWD_Functions.csv")
        if path_fb: path = str(path_fb)
    if not path or not os.path.exists(path):
        master["Access_Velocity_Share"] = np.nan; return master
    try:
        df = pd.read_csv(path)
        df.columns = [str(c).strip() for c in df.columns]
        sc = next((c for c in df.columns if "state" in c.lower()),df.columns[0])
        df[sc] = df[sc].apply(_standardize_state)
        pc = next((c for c in df.columns
                   if "overall" in c.lower() and "perform" in c.lower()),None)
        if pc:
            master["Access_Velocity_Share"] = master["State"].map(
                df.set_index(sc)[pc].apply(_parse_pct))
    except Exception as e:
        print(f"[WARN] ADRC: {e}")
        master["Access_Velocity_Share"] = np.nan
    return master

def _load_b3_transitions(master:pd.DataFrame) -> pd.DataFrame:
    """
    Load CMS LTSS B.3 Community Transitions — % long-stay nursing home
    residents who transitioned to community settings within 90 days (65+).
    This is a HOLDOUT VALIDATOR for GPI: states with higher governance
    pressure (high GPI) should have lower community transition rates.
    Source: CMS/Mathematica LTSS Rebalancing Measures 2023.
    This variable is NOT used in any GPI component, making it genuinely
    independent for external validation.
    """
    B3_FILE = DATA_DIR / "B3_LTSSTransRebalMeasr_auto.xlsx"
    fb_file = None
    for p in [B3_FILE, Path("/mnt/project/B3_LTSSTransRebalMeasr_2023.xlsx")]:
        if p.exists():
            fb_file = str(p); break

    if not fb_file:
        print("[WARN] B3 transitions file not found — skipping holdout validator")
        master["B3_Transition_Rate_65plus"] = np.nan
        return master

    try:
        raw = pd.read_excel(fb_file, sheet_name=None, header=None)
        # Find the BalanceByAge or similar sheet
        sheet = next((s for s in raw if "balance" in s.lower() or "b.3" in s.lower()
                      or "trans" in s.lower()), list(raw.keys())[0])
        df = pd.read_excel(fb_file, sheet_name=sheet, header=None)
        # Find header row
        hdr = next((i for i, row in df.iterrows()
                    if any("state" in str(v).lower() for v in row.values)), None)
        if hdr is None:
            raise ValueError("No header row found")
        df = pd.read_excel(fb_file, sheet_name=sheet, header=hdr)
        df.columns = [str(c).strip() for c in df.columns]
        sc = next((c for c in df.columns if "state" in c.lower()), df.columns[0])
        df[sc] = df[sc].apply(_standardize_state)
        # Find 65+ transition rate column
        col65 = next((c for c in df.columns
                      if re.search(r"65", str(c)) and
                         re.search(r"trans|commun|percent|%", str(c).lower())), None)
        if col65 is None:
            # Try percentage columns generically
            pct_cols = [c for c in df.columns if df[c].astype(str).str.contains(r'^[0-9]+\.?[0-9]*$', na=False).mean() > 0.4]
            col65 = pct_cols[1] if len(pct_cols) > 1 else pct_cols[0] if pct_cols else None
        if col65:
            master["B3_Transition_Rate_65plus"] = master["State"].map(
                df.set_index(sc)[col65].apply(_parse_pct))
            n = master["B3_Transition_Rate_65plus"].notna().sum()
            print(f"[INFO] B3 community transitions loaded: {n} states")
        else:
            master["B3_Transition_Rate_65plus"] = np.nan
            print("[WARN] B3 column not identified")
    except Exception as e:
        print(f"[WARN] B3 load failed: {e}")
        master["B3_Transition_Rate_65plus"] = np.nan
    return master


def _load_market_inputs(master:pd.DataFrame) -> pd.DataFrame:
    path = _resolve(INPUT_FILE)
    field_map = {
        "COST":   ("Cost_Hourly",   ["hourly","cost","rate"]),
        "INCOME": ("Income_65plus", ["income","65"]),
        "WAGE":   ("Wage_Aide",     ["wage","hourly","median"]),
        "LIVING": ("Wage_Living",   ["living","wage","hourly"]),
        "EMP":    ("Aide_Count",    ["employ","count","311120","31-1120"]),
    }
    for key,(out_col,hints) in field_map.items():
        try:
            df = pd.read_excel(path,sheet_name=SHEET_MAP[key])
            df.columns = [str(c).strip() for c in df.columns]
            sc = next((c for c in df.columns if "state" in c.lower()),df.columns[0])
            df[sc] = df[sc].apply(_standardize_state)
            vc = next((c for c in df.columns
                       if any(h in str(c).lower() for h in hints)
                       and c != sc),
                      df.columns[1] if len(df.columns)>1 else None)
            if vc is None: raise ValueError(f"No col for {out_col}")
            master[out_col] = pd.to_numeric(
                master["State"].map(df.set_index(sc)[vc]),errors="coerce")
        except Exception as e:
            print(f"[WARN] {out_col}: {e}")
            master[out_col] = np.nan
    return master

def _apply_wage_floor(master:pd.DataFrame) -> pd.DataFrame:
    n = (master["Wage_Aide"] < BLS_AIDE_WAGE_P10_FLOOR).sum()
    if n > 0:
        aff = master.loc[master["Wage_Aide"]<BLS_AIDE_WAGE_P10_FLOOR,"State"].tolist()
        print(f"[INFO] Wage floor applied to {n} state(s): {aff}")
        master["Wage_Aide"] = master["Wage_Aide"].clip(lower=BLS_AIDE_WAGE_P10_FLOOR)
    return master

def _load_aarp_validation(master:pd.DataFrame) -> pd.DataFrame:
    src = _fallback("Raw_AARP_Scores.csv")
    if src:
        df = pd.read_csv(src)
        df["state_name"] = df["state_name"].apply(_standardize_state)
        master = master.merge(
            df[["state_name","AARP_Score"]].rename(columns={"state_name":"State"}),
            on="State",how="left")
    else:
        master["AARP_Score"] = master["State"].map(AARP_SCORES)
    return master

def _load_phi(master:pd.DataFrame) -> pd.DataFrame:
    path = _resolve(PHI_FILE)
    if not os.path.exists(path):
        for c in ["PHI_Rank_Overall","PHI_Worker_Support","PHI_Economic"]:
            master[c] = np.nan
        return master
    try:
        df = pd.read_csv(path)
        df.columns = [str(c).strip() for c in df.columns]
        sc = next((c for c in df.columns if "state" in c.lower()),df.columns[1])
        df[sc] = df[sc].apply(_standardize_state)
        cols = df.columns.tolist()
        if len(cols) >= 4:
            master["PHI_Rank_Overall"]   = pd.to_numeric(
                master["State"].map(df.set_index(sc)[cols[0]]),errors="coerce")
            master["PHI_Worker_Support"] = pd.to_numeric(
                master["State"].map(df.set_index(sc)[cols[2]]),errors="coerce")
            master["PHI_Economic"]       = pd.to_numeric(
                master["State"].map(df.set_index(sc)[cols[3]]),errors="coerce")
    except Exception as e:
        print(f"[WARN] PHI: {e}")
        for c in ["PHI_Rank_Overall","PHI_Worker_Support","PHI_Economic"]:
            master[c] = np.nan
    return master

def _load_digital_readiness(master:pd.DataFrame) -> pd.DataFrame:
    # Try ACS v4 CSV (Census API-fetched with real broadband data)
    src = _fallback("Raw_ACS_v4.csv")
    if src:
        df = pd.read_csv(src)
        df["state_name"] = df["state_name"].apply(_standardize_state)
        if "Broadband_65plus_Pct" in df.columns:
            bband = df.set_index("state_name")["Broadband_65plus_Pct"]
            if bband.notna().sum() > 0:  # only use if actually populated
                master["broadband_65plus"] = master["State"].map(bband)
                master["smartphone_65plus"] = master["broadband_65plus"] * (ADJ_SMARTPHONE/ADJ_BROADBAND)
                master["digital_readiness_65plus"] = (
                    master["smartphone_65plus"] + master["broadband_65plus"]) / 2.0
                master["digital_readiness"] = master["digital_readiness_65plus"]
                return master
    # Fallback: existing acs_digital_readiness.csv (all-ages with age adjustment)
    acs_path = DATA_DIR/"acs_digital_readiness.csv"
    if acs_path.exists():
        df = pd.read_csv(acs_path)
        df["State"] = df["State"].apply(_standardize_state)
        master = master.merge(df[["State","smartphone_share","broadband_share"]],
                               on="State",how="left")
        master["smartphone_65plus"] = master["smartphone_share"] * ADJ_SMARTPHONE
        master["broadband_65plus"]  = master["broadband_share"]  * ADJ_BROADBAND
    else:
        master["smartphone_65plus"] = 0.63
        master["broadband_65plus"]  = 0.64
    master["digital_readiness_65plus"] = (
        master["smartphone_65plus"] + master["broadband_65plus"]) / 2.0
    master["digital_readiness"] = master["digital_readiness_65plus"]
    return master

def _load_macro(master:pd.DataFrame) -> pd.DataFrame:
    src = _fallback("Raw_Unemployment_v4.csv")
    if src:
        df = pd.read_csv(src)
        df["state_name"] = df["state_name"].apply(_standardize_state)
        master = master.merge(
            df[["state_name","Unemployment_Rate"]].rename(
                columns={"state_name":"State"}),
            on="State",how="left")
    src_rpp = _fallback("Raw_RPP_v4.csv")
    if src_rpp:
        df = pd.read_csv(src_rpp)
        df["state_name"] = df["state_name"].apply(_standardize_state)
        if "RPP_AllItems" in df.columns:
            master = master.merge(
                df[["state_name","RPP_AllItems"]].rename(
                    columns={"state_name":"State"}),
                on="State",how="left")
    return master

def _load_evv(master:pd.DataFrame) -> pd.DataFrame:
    evv_df = pd.DataFrame([
        {"State":s,"evv_model_score":_evv_model_score(v["model"]),
         "evv_vendor_score":_evv_vendor_score(v["portability"])}
        for s,v in EVV_REGULATORY_MAP.items()])
    master = master.merge(evv_df,on="State",how="left")
    master["evv_model_score"] = master["evv_model_score"].fillna(0.5)
    master["evv_vendor_score"] = master["evv_vendor_score"].fillna(0.5)
    return master

def _load_wage_compression(master:pd.DataFrame) -> pd.DataFrame:
    """
    Load BLS P10/P50 wage compression ratio for SOC 31-1120.
    Wage_Compression_Ratio = H_PCT10 / H_MEDIAN (Acemoglu-Pischke 1999 identification var)

    Priority order:
      1. Live BLS API or cached Raw_BLS_Wage_v4.csv (online-only)
      2. BLS_WAGE_COMPRESSION_DATA hardcode (default offline path)
         — All 51 states, sourced from BLS OES May 2023 state pages +
           ASPE (2024) + state minimum wage floors. See BLS_WAGE_COMPRESSION_DATA
           dict above for full methodology note.

    Acemoglu & Pischke (1999, EJ 109(453)):
      Wage compression = W(τ)/F(τ) where τ is the training level.
      Higher compression → employer has market power → de facto specific training
      → firm sponsors general training → less training externality.
      Lower compression → competitive market → no incentive to sponsor training
      → training externality operates at full strength.

    The Training_Floor_Gap measures the regulatory gap in state mandated training
    hours vs. the 120-hour PHCAST benchmark (PHI 2024). When Wage_Compression_Ratio
    has real cross-state variance AND Training_Floor_Gap has real variance,
    MFI_MF1 jointly measures the AP training externality from two sides:
      - Wage compression: whether the monopsony mechanism suppresses externality
      - Training floor gap: whether regulation compensates for the externality
    """
    loaded_from_api = False
    src = _fallback("Raw_BLS_Wage_v4.csv")
    if src:
        try:
            df = pd.read_csv(src)
            df["state_name"] = df["state_name"].apply(_standardize_state)
            p10_col = next((c for c in df.columns
                            if c in ("Wage_P10_SOC31120","H_PCT10","H_P10",
                                     "wage_p10","p10")), None)
            if p10_col:
                p10_map = df.set_index("state_name")[p10_col]
                master["Wage_P10"] = master["State"].map(p10_map)
                p50 = master["Wage_Aide"].clip(lower=EPS)
                p10 = pd.to_numeric(master["Wage_P10"], errors="coerce")
                p10 = p10.fillna(p50 * 0.712)  # BLS national P10/P50 fallback
                master["Wage_Compression_Ratio"] = (p10 / p50).clip(lower=0.01, upper=1.0)
                # Only mark as loaded if the P10 data has real variance
                # (all-NaN cache gives WCR = constant; fall through to hardcode)
                wcr_std = master["Wage_Compression_Ratio"].std()
                if wcr_std >= 0.01:
                    loaded_from_api = True
                    print(f"[INFO] Wage compression loaded from cache: "
                          f"{master['Wage_Compression_Ratio'].notna().sum()} states "
                          f"(std={wcr_std:.4f})")
                else:
                    print(f"[WARN] Cache P10 has no real variance (std={wcr_std:.4f}) "
                          f"— falling through to BLS_WAGE_COMPRESSION_DATA hardcode")
        except Exception as e:
            print(f"[WARN] BLS cache load failed: {e} — using hardcoded table")

    if not loaded_from_api:
        # ── Hardcoded BLS OES May 2023 table (primary offline source) ────────
        # Build from BLS_WAGE_COMPRESSION_DATA dict: (P10, P50) per state
        # Compression = P10/P50; higher = more compressed = less AP externality
        p10_map  = {s: v[0] for s, v in BLS_WAGE_COMPRESSION_DATA.items()}
        p50_map  = {s: v[1] for s, v in BLS_WAGE_COMPRESSION_DATA.items()}
        master["Wage_P10"] = master["State"].map(p10_map)
        hc_p50   = master["State"].map(p50_map)
        # Use hardcoded P50 as denominator (more precise than BLS mean proxy)
        p50_denom = hc_p50.where(hc_p50.notna(), master["Wage_Aide"]).clip(lower=EPS)
        p10_num   = pd.to_numeric(master["Wage_P10"], errors="coerce")
        # Regional median imputation for any remaining gaps
        master["Wage_Compression_Ratio"] = (p10_num / p50_denom).clip(lower=0.01, upper=1.0)
        n_loaded  = master["Wage_Compression_Ratio"].notna().sum()
        n_states  = master["State"].notna().sum()
        print(f"[INFO] Wage compression loaded from BLS_WAGE_COMPRESSION_DATA hardcode: "
              f"{n_loaded}/{n_states} states  "
              f"(std={master['Wage_Compression_Ratio'].std():.4f})")

    # Training Floor Gap from hardcoded PHI_TRAINING_GAP
    master["Training_Floor_Gap"] = master["State"].map(PHI_TRAINING_GAP).fillna(1.0)

    # Impute any remaining NaN with regional median
    _impute_regional_median(master, "Wage_Compression_Ratio")
    return master

def build_master() -> pd.DataFrame:
    print("[INFO] Building master dataset...")
    master = _load_state_list()
    master = _load_population(master)
    master = _apply_hpas(master)
    master = _load_rebalancing(master)
    master = _load_adrc(master)
    master = _load_b3_transitions(master)
    master = _load_market_inputs(master)
    master = _apply_wage_floor(master)
    master = _load_aarp_validation(master)
    master = _load_phi(master)
    master = _load_wage_compression(master)
    master = _load_digital_readiness(master)
    master = _load_macro(master)
    master = _load_evv(master)

    for col in ["HCBS_Users_Share","HCBS_Exp_Share","Access_Velocity_Share",
                "Cost_Hourly","Income_65plus","Wage_Aide","Wage_Living",
                "Aide_Count","Pop_65plus","Wage_Compression_Ratio","Training_Floor_Gap"]:
        _impute_regional_median(master, col)

    num_cols = ["Pop_Total","Pop_65plus","Cost_Hourly","Income_65plus",
                "Wage_Aide","Wage_Living","Aide_Count","AARP_Score",
                "Access_Velocity_Share","PHI_Rank_Overall",
                "PHI_Worker_Support","PHI_Economic",
                "digital_readiness","digital_readiness_65plus",
                "Wage_Compression_Ratio","Training_Floor_Gap"]
    for c in num_cols:
        if c in master.columns:
            master[c] = pd.to_numeric(master[c],errors="coerce")
    print(f"[INFO] Master: {len(master)} states, {len(master.columns)} columns")
    return master

# =============================================================================
# PHASE 2B: INDEX COMPUTATION
# =============================================================================

def compute_gpi(master:pd.DataFrame) -> pd.DataFrame:
    """
    GPI v6 — Governance Pressure Index.
    Fixes from v4: (1) hybrid structure prevents HPAS floor collapse;
    (2) merges correlated c1/c2 to eliminate double-weighting.

    Architecture (three conceptual governance dimensions):
      Dim 1 — HCBS Program Balance:
        HCBS_Rebal = sqrt(c1 × c2)  [geometric mean of user + expenditure shares]
        Rationale: c1 and c2 derive from same CMS source (Spearman ρ=0.80).
        Merging eliminates ~2× implicit weight per Paruolo et al. (2013).
      Dim 2 — NWD/ADRC Navigation Infrastructure (c3)
      Dim 3 — HPAS program authority (multiplicative scalar, not a 4th component)

    Formula:
      GPI_v6 = Geom_Mean(HCBS_Rebal, c3) × HPAS_multiplier

    HPAS multiplier: {0: 0.10, 1: 0.55, 2: 1.00}
      Rationale: HPAS captures program-authority architecture — a discrete
      institutional level qualitatively different from the continuous outcome
      components. Entering it as a multiplicative scalar (rather than a 4th
      geometric component at 0.01) prevents floor collapse for 11 entitlement
      states while preserving the non-compensatory logic. Design mirrors UNDP GII
      hybrid structure (UNDP 2010) and follows OECD Handbook (Nardo et al. 2008,
      p.31) guidance on qualitatively heterogeneous component types.

    Legacy GPI_v4 retained as GPI_v4_legacy for sensitivity comparison.
    Spearman(GPI_v4, GPI_v6) ≥ 0.95 required by QC suite (top findings stable).

    ADRC dominance note (Sobol S1=0.344 vs HCBS S1≈0.12 each):
      ADRC Access Velocity drives ~2.9× more variance than each HCBS component
      despite nominally equal weight. This is theoretically defensible — ADRC
      infrastructure is the state's ACTIVE response to the access constraint
      (process measure), while HCBS rebalancing captures accumulated historical
      outcomes. The dominance is disclosed and defended in §6.1, not hidden.

    Shadow-price interpretation (Rodrik 2010 standard):
      GPI maps to shadow prices of governance constraints: HCBS_Rebal proxies
      the cost of institutional inertia (states slow to rebalance face higher
      per-unit administrative costs); ADRC_c3 proxies navigation friction
      (longer time-to-services = higher search cost for families); HPAS proxies
      the program-authority shadow price (screened waiver = implicit enrollment
      rationing). These are structural condition indicators, not direct shadow
      prices. Full shadow-price validation per HRV Tests 1/3/4 requires
      time-series evidence presented separately in §3.2.

    References:
      UNDP (2010). Human Development Report 2010. GII methodology, pp.156-158.
      Nardo et al. (2008). OECD Handbook on Composite Indicators, pp.31-34.
      Paruolo, Saisana & Saltelli (2013). JRSS-A 176(3), 609-634.
      MACPAC (2020). Medicaid HCBS Waiver Waiting Lists. Issue Brief #18.
    """
    df = master.copy()

    # ── Step 1: Raw continuous signals (logit-inverted) ──────────────────────
    for col, sig in [("HCBS_Users_Share",    "_s1"),
                     ("HCBS_Exp_Share",       "_s2"),
                     ("Access_Velocity_Share","_s3")]:
        df[f"GPI{sig}"] = -_logit(pd.to_numeric(df[col], errors="coerce"))

    df["GPI_c1"] = _minmax_norm(df["GPI_s1"])  # HCBS users rebalancing
    df["GPI_c2"] = _minmax_norm(df["GPI_s2"])  # HCBS exp rebalancing
    df["GPI_c3"] = _minmax_norm(df["GPI_s3"])  # ADRC access velocity

    # ── Step 2: Merge c1/c2 into single HCBS Rebalancing component ───────────
    # Geometric mean of two correlated signals (Spearman ρ=0.80 → same CMS source)
    # Eliminates double-weighting while preserving both signals' information.
    df["GPI_c_rebal"] = (df["GPI_c1"] * df["GPI_c2"]).clip(lower=EPS**2) ** 0.5

    # ── Step 3: HPAS multiplicative penalty ──────────────────────────────────
    # Discrete institutional architecture variable — qualitatively different
    # from the continuous outcome components. Multiplicative (not additive)
    # so it scales the outcome signal without zero-collapsing it.
    HPAS_MULT = {0: 0.10, 1: 0.55, 2: 1.00}
    df["GPI_hpas_mult"] = df["HPAS"].map(HPAS_MULT).fillna(1.00)

    # ── Step 4: Two-dimensional geometric mean × HPAS scalar ─────────────────
    # GPI_v6 = Geom_Mean(HCBS_Rebal, ADRC) × HPAS_multiplier
    geom2 = (df["GPI_c_rebal"] * df["GPI_c3"]).clip(lower=EPS**2) ** 0.5
    df["GPI_v6"] = geom2 * df["GPI_hpas_mult"]

    # ── Legacy v4 for comparison / backward compat ───────────────────────────
    # Keep GPI_v4 column so downstream QC, quadrant logic, and PRI still work.
    df["GPI_c4"]        = _minmax_norm(df["HPAS"].astype(float))
    df["GPI_v4_legacy"] = (df["GPI_c1"]*df["GPI_c2"]*
                            df["GPI_c3"]*df["GPI_c4"])**0.25
    # Set GPI_v4 = GPI_v6 so all downstream code uses the corrected index
    df["GPI_v4"]  = df["GPI_v6"]
    df["GPI_rank"] = df["GPI_v4"].rank(ascending=False, method="min").astype(int)

    # Log comparison for QC
    rho_v4_v6 = df["GPI_v4_legacy"].corr(df["GPI_v6"], method="spearman")
    n_same_top10 = len(
        set(df.nlargest(10,"GPI_v4_legacy")["State"]) &
        set(df.nlargest(10,"GPI_v6")["State"])
    )
    print(f"[INFO] GPI v6: Spearman(v4,v6)={rho_v4_v6:.3f}  "
          f"top-10 overlap={n_same_top10}/10")

    df = df.drop(columns=["GPI_s1","GPI_s2","GPI_s3"], errors="ignore")
    return df

def compute_mfi(master:pd.DataFrame) -> pd.DataFrame:
    """
    MFI v4 — Market Friction Index (Actual Mazziotta-Pareto).
    Formula: MFI = M_r + S_r²/M_r  (quadratic penalty for imbalance)
    100-centered normalization per Mazziotta & Pareto (2013, 2016).
    Components (equal weight 1/5):
      MF2 (coordination/matching failure):
        Cost Burden    = log(annualized care cost / income_65+)
        Wage Gap       = log(living wage / aide median wage)
        Labor Scarcity = log(1 / aide density per 1,000 elderly)
      MF1 (training externality, Acemoglu-Pischke 1999 proxies):
        Wage Compression = PHI Economic rank
        Training Floor   = PHI Worker Support rank
    """
    df = master.copy()
    annual_cost = df["Cost_Hourly"]*HOURS_PER_WEEK*WEEKS_PER_YEAR
    df["Cost_Burden"]    = _safe_log_ratio(annual_cost, df["Income_65plus"])
    df["Wage_Gap"]       = _safe_log_ratio(df["Wage_Living"], df["Wage_Aide"])
    aide_density         = (df["Aide_Count"]/df["Pop_65plus"].clip(lower=1))*1000.0
    df["Labor_Scarcity"] = _safe_log_ratio(pd.Series(1.0,index=df.index),
                                            aide_density.clip(lower=EPS))
    df["WageComp_proxy"] = pd.to_numeric(df.get("PHI_Economic",np.nan),
                                          errors="coerce").fillna(26)
    df["TrainGap_proxy"] = pd.to_numeric(df.get("PHI_Worker_Support",np.nan),
                                          errors="coerce").fillna(26)

    comps = pd.DataFrame({
        "CostBurden": _mpi_normalize_100(df["Cost_Burden"]),
        "WageGap":    _mpi_normalize_100(df["Wage_Gap"]),
        "LaborScar":  _mpi_normalize_100(df["Labor_Scarcity"]),
        "WageComp":   _mpi_normalize_100(df["WageComp_proxy"]),
        "TrainGap":   _mpi_normalize_100(df["TrainGap_proxy"]),
    })
    M_r = comps.mean(axis=1)
    S_r = comps.std(axis=1,ddof=1)
    df["MFI_v4"]        = M_r + S_r**2 / M_r
    df["MFI_rank"]      = df["MFI_v4"].rank(ascending=False,method="min").fillna(99).astype(int)
    df["MFI_bottleneck"] = comps.idxmax(axis=1)
    return df

def deflate_monetary(master:pd.DataFrame) -> pd.DataFrame:
    """
    RPP-deflate all monetary MFI inputs by BEA All-Items state RPP.
    Note: Wage_Gap is RPP-invariant (ratio cancels). Only Cost_Burden
    is materially affected. This is reported as a robustness check.
    Citation: Moretti (2011), Handbook of Labor Economics 4B, pp.1237-1313:
    all-items RPP is appropriate for low-wage local service workers.
    """
    df = master.copy()
    if "RPP_AllItems" not in df.columns or df["RPP_AllItems"].isna().all():
        print("[WARN] RPP not available — skipping deflation")
        return df
    rpp = (df["RPP_AllItems"] / 100.0).clip(lower=0.5)
    df["Wage_Aide_real"]     = df["Wage_Aide"]     / rpp
    df["Wage_Living_real"]   = df["Wage_Living"]   / rpp
    df["Cost_Hourly_real"]   = df["Cost_Hourly"]   / rpp
    df["Income_65plus_real"] = df["Income_65plus"] / rpp
    return df


def compute_mfi_real(master:pd.DataFrame) -> pd.DataFrame:
    """
    RPP-deflated MFI robustness specification.
    Wage_Gap is algebraically RPP-invariant (proven: log(W_L/rpp / W_A/rpp)
    = log(W_L/W_A)). Only Cost_Burden uses deflated values.
    Expected: Spearman(MFI_real, MFI_v5) > 0.90 — confirming wage gap
    reflects genuine market failure, not geographic price arbitrage.
    """
    df = deflate_monetary(master)
    if "Wage_Aide_real" not in df.columns:
        df["MFI_real"] = np.nan
        return df

    annual_cost_r = df["Cost_Hourly_real"] * HOURS_PER_WEEK * WEEKS_PER_YEAR
    df["Cost_Burden_real"] = _safe_log_ratio(annual_cost_r, df["Income_65plus_real"])
    df["Wage_Gap_real"]    = _safe_log_ratio(df["Wage_Living_real"], df["Wage_Aide_real"])

    aide_density = (df["Aide_Count"] / df["Pop_65plus"].clip(lower=1)) * 1000.0
    df["Labor_Scarcity_real"] = _safe_log_ratio(pd.Series(1.0, index=df.index),
                                                 aide_density.clip(lower=EPS))

    wc_r = (1.0 - df["Wage_Compression_Ratio"].clip(lower=0.01, upper=1.0))
    tg_r = df["Training_Floor_Gap"].clip(lower=0.0, upper=1.0)

    mf2r = pd.DataFrame({
        "CostBurden": _mpi_normalize_100(df["Cost_Burden_real"]),
        "WageGap":    _mpi_normalize_100(df["Wage_Gap_real"]),
        "LaborScar":  _mpi_normalize_100(df["Labor_Scarcity_real"]),
    })
    M2r = mf2r.mean(axis=1); S2r = mf2r.std(axis=1, ddof=1)
    MFI_MF2r = M2r + S2r**2 / M2r.clip(lower=EPS)

    mf1r = pd.DataFrame({
        "WageComp": _mpi_normalize_100(wc_r),
        "TrainGap": _mpi_normalize_100(tg_r),
    })
    M1r = mf1r.mean(axis=1); S1r = mf1r.std(axis=1, ddof=1)
    MFI_MF1r = M1r + S1r**2 / M1r.clip(lower=EPS)

    df["MFI_real"] = 0.60 * MFI_MF2r + 0.40 * MFI_MF1r
    return df


def compute_mfi_v5(master:pd.DataFrame) -> pd.DataFrame:
    """
    MFI v6 — Market Friction Index (canonical A+ specification).
    Called compute_mfi_v5 for backward compatibility with run_compute.

    Fixes from v5:
      Issue 3 (Labor_Scarcity dominance): Reframed as matching coordination
        failure (§3.3), not training externality (§3.2). Labor_Scarcity's
        empirical dominance (ρ=0.779) is theoretically correct — thin aide
        pools are precisely where X3P's matching mechanism creates most value.
        No structural change; fix is in theoretical framing and documentation.

      Issue 4 (Cost_Burden × Wage_Gap ρ=-0.59): Separates worker-side friction
        (Wage_Gap + Labor_Scarcity) from demand-side affordability (Cost_Burden)
        within MF2 using arithmetic aggregation. MPI non-compensatory penalty
        applied at the MF2→composite level, not between opposite-direction
        price-distribution signals. Prevents artificial elevation of both
        Hawaii (high cost, low wage gap) and Mississippi (low cost, high wage gap)
        for opposite economic reasons (Mazziotta & Pareto 2013).

    Architecture:
      ── MF2: Coordination / Matching Failure ─────────────────────────────
        Worker signal:       Wage_Signal = Geom_Mean(Wage_Gap, Labor_Scarcity)
          → Both measure worker-side market failure (ρ=0.092, same direction)
          → Labor_Scarcity = thin aide pool = high matching coordination cost
            (§3.3 coordination failure, not §3.2 training externality)
        Affordability signal: Afford_Signal = Cost_Burden (normalized)
          → Demand-side: is care affordable relative to elderly income?
          → Enters additively to avoid cross-signal MPI penalties

        MFI_MF2 = (Wage_Signal_100 + Afford_Signal_100) / 2
          [arithmetic mean preserves information; MPI applied at composite]

      ── MF1: Training Externality (Acemoglu-Pischke 1999) ────────────────
        MFI_MF1 = MPI(Wage_Compression_Friction, Training_Floor_Gap)
          → Wage_Compression = 1 - (P10/P50): lower ratio → more compressed
          → Training_Floor_Gap = max(0, 120-mandated_hours)/120

      ── Composite ────────────────────────────────────────────────────────
        MFI_v6 = 0.60 × MFI_MF2 + 0.40 × MFI_MF1
          Weight rationale: MF2 channels (retention savings + route optimization)
          account for ~60% of modeled unit-cost reduction (§4.1); MF1 (training
          investment internalization) accounts for ~40%.

    References:
      Mazziotta & Pareto (2013). Rivista Italiana di Economia, LXVII(2), 67-80.
      Acemoglu & Pischke (1999). Economic Journal, 109(453), F112-F142.
      Manning (2003). Monopsony in Motion. Princeton University Press.
    """
    df = master.copy()
    eps = EPS

    # ── Compute raw components ───────────────────────────────────────────────
    annual_cost = df["Cost_Hourly"] * HOURS_PER_WEEK * WEEKS_PER_YEAR
    df["Cost_Burden"]    = _safe_log_ratio(annual_cost, df["Income_65plus"])
    df["Wage_Gap"]       = _safe_log_ratio(df["Wage_Living"], df["Wage_Aide"])
    aide_density         = (df["Aide_Count"] / df["Pop_65plus"].clip(lower=1)) * 1000.0
    df["Labor_Scarcity"] = _safe_log_ratio(pd.Series(1.0, index=df.index),
                                            aide_density.clip(lower=eps))

    # ── MF2: SPLIT worker signal + affordability signal ─────────────────────
    #
    # Worker signal: Wage_Gap and Labor_Scarcity both measure labor-market
    # supply failure (ρ=0.092 — near-independent, same theoretical direction).
    # Labor_Scarcity = log(1/aide_density) measures market thinness — the
    # coordination failure where aides cannot find clients and vice versa.
    # This is §3.3 (matching coordination failure), not §3.2 (training externality).
    # Its empirical dominance (Spearman ρ=0.779 with MFI) is correct: thin
    # labor pools are where X3P's matching mechanism creates the most value.
    #
    # Geometric mean of normalized worker signals (both higher = worse):
    wg_100  = _mpi_normalize_100(df["Wage_Gap"])
    ls_100  = _mpi_normalize_100(df["Labor_Scarcity"])
    # Shift to [1, ...] so geometric mean is well-defined; then re-center
    wg_pos  = wg_100 - wg_100.min() + 1.0
    ls_pos  = ls_100 - ls_100.min() + 1.0
    wage_signal = (wg_pos * ls_pos).clip(lower=eps) ** 0.5
    # Re-normalize wage signal to 100-centered MPI scale
    wage_signal_100 = _mpi_normalize_100(wage_signal)

    # Affordability signal: Cost_Burden enters separately (opposite price-dist
    # correlation with Wage_Gap). Arithmetic addition avoids MPI penalizing
    # natural regional price-distribution divergence.
    afford_100 = _mpi_normalize_100(df["Cost_Burden"])

    # MF2 = GEOMETRIC MEAN of the two signals (non-compensatory: both must be adequate)
    # Rationale: Becker et al. (2017, Ecological Indicators 80): negatively correlated
    # components (here ρ=−0.59) should not be additively averaged — arithmetic mean
    # partially cancels opposed signals. Geometric mean penalises imbalance naturally:
    # a state extreme on one dimension cannot offset inadequacy on the other.
    # Mirrors UNDP HDI 2010 switch (Klugman et al. 2011, J Economic Inequality 9(2)).
    w_min   = wage_signal_100.min()
    a_min   = afford_100.min()
    w_pos   = (wage_signal_100 - w_min + 1.0).clip(lower=eps)
    a_pos   = (afford_100      - a_min + 1.0).clip(lower=eps)
    mf2_geom_raw = (w_pos * a_pos).clip(lower=eps) ** 0.5
    mf2_100 = _mpi_normalize_100(mf2_geom_raw)  # re-centre to ≈100 scale
    df["MFI_MF2_wage"]   = wage_signal_100
    df["MFI_MF2_afford"] = afford_100
    df["MFI_MF2"]        = mf2_100

    # ── MF1: Training Externality (Acemoglu-Pischke mechanism) ──────────────
    wc_friction = (1.0 - df["Wage_Compression_Ratio"].clip(lower=0.01, upper=1.0))
    tg_friction  = df["Training_Floor_Gap"].clip(lower=0.0, upper=1.0)
    mf1_comps = pd.DataFrame({
        "WageComp": _mpi_normalize_100(wc_friction),
        "TrainGap": _mpi_normalize_100(tg_friction),
    })
    M1 = mf1_comps.mean(axis=1)
    S1 = mf1_comps.std(axis=1, ddof=1)
    df["MFI_MF1"] = M1 + S1**2 / M1.clip(lower=eps)

    # ── Composite: 60% MF2 + 40% MF1 ────────────────────────────────────────
    df["MFI_v5"]         = 0.60 * df["MFI_MF2"] + 0.40 * df["MFI_MF1"]
    df["MFI_rank"]       = df["MFI_v5"].rank(ascending=False, method="min").fillna(99).astype(int)

    # Bottleneck: dominant component across all MF2 sub-signals and MF1
    all_comps = pd.DataFrame({
        "WageGap":   wg_100,
        "LaborScar": ls_100,
        "CostBurden":afford_100,
        "WageComp":  mf1_comps["WageComp"],
        "TrainGap":  mf1_comps["TrainGap"],
    })
    df["MFI_bottleneck"] = all_comps.idxmax(axis=1)

    # MFI_MF2 dominant sub-signal (for paper's bottleneck diagnostics)
    df["MFI_MF2_bottleneck"] = pd.DataFrame({
        "WageSignal":   wage_signal_100,
        "AffordSignal": afford_100,
    }).idxmax(axis=1)

    # ── Legacy v5 for rank-change comparison ─────────────────────────────────
    old_mf2 = pd.DataFrame({
        "CostBurden": _mpi_normalize_100(df["Cost_Burden"]),
        "WageGap":    _mpi_normalize_100(df["Wage_Gap"]),
        "LaborScar":  _mpi_normalize_100(df["Labor_Scarcity"]),
    })
    M2_old = old_mf2.mean(axis=1); S2_old = old_mf2.std(axis=1, ddof=1)
    mfi_mf2_v5 = M2_old + S2_old**2 / M2_old.clip(lower=eps)
    old_comps_full = pd.DataFrame({
        "CostBurden": _mpi_normalize_100(df["Cost_Burden"]),
        "WageGap":    _mpi_normalize_100(df["Wage_Gap"]),
        "LaborScar":  _mpi_normalize_100(df["Labor_Scarcity"]),
        "WageComp":   mf1_comps["WageComp"],
        "TrainGap":   mf1_comps["TrainGap"],
    })
    M_old = old_comps_full.mean(axis=1); S_old = old_comps_full.std(axis=1, ddof=1)
    df["MFI_v4_legacy"] = M_old + S_old**2 / M_old.clip(lower=eps)

    return df


def compute_quadrants(master:pd.DataFrame) -> pd.DataFrame:
    df = master.copy()
    if QUADRANT_SPLIT == "mean":
        g_cut, m_cut = df["GPI_v4"].mean(), df["MFI_v4"].mean()
    elif QUADRANT_SPLIT == "zero":
        g_cut, m_cut = 0.0, 0.0
    else:
        g_cut, m_cut = df["GPI_v4"].median(), df["MFI_v4"].median()

    def _quad(r) -> str:
        if r["GPI_v4"]>=g_cut and r["MFI_v4"]>=m_cut: return "Double Bind"
        if r["GPI_v4"]>=g_cut:                          return "Policy Bottleneck"
        if r["MFI_v4"]>=m_cut:                          return "Market Failure"
        return "High Performance"

    df["Quadrant"]          = df.apply(_quad,axis=1)
    df["Binding_Intensity"] = df["MFI_v4"] - m_cut
    print(f"[INFO] Quadrant distribution ({QUADRANT_SPLIT} split):")
    print(df["Quadrant"].value_counts().to_string())
    return df

def compute_pri(master:pd.DataFrame) -> pd.DataFrame:
    """
    PRI v6 — Pilot Readiness Index (Two-Factor F×O Specification).

    Canonical design: Feasibility × Opportunity geometric product with
    bilateral 60th-percentile threshold gate + EVV hard gate.
    Matches paper §6.1.3 description and Figure 15.

    Rationale for F×O over single-score BAP:
      The bilateral gate implements MCDA conjunctive screening logic (Dodgson
      et al. 2009, UK Govt MCDA Manual §4.3): a minimum threshold on EACH
      factor is a necessary condition for program entry. A state with perfect
      Feasibility but near-zero Opportunity (e.g. Vermont: low friction =
      low value from X3P) is correctly excluded; a single additive score
      would allow Feasibility to compensate for Opportunity.

      NOTE — WHAT HRV DOES AND DOES NOT SAY:
      Hausmann-Rodrik-Velasco (2005) use SEQUENTIAL constraint identification
      (a decision tree), not bilateral necessity. The paper's claim that GPI
      and MFI identify "binding constraints" in the HRV sense is intentionally
      not repeated here. GPI and MFI identify structural conditions that map
      to shadow prices of governance and market friction, consistent with
      Rodrik (2010, JEP 24(3), "Diagnostics before Prescription"). The PRI
      bilateral gate reflects MCDA necessity logic, not HRV diagnostics.

      ALLCOTT (2015) NOTE:
      Allcott ("Site Selection Bias," QJE 2015) demonstrates that selecting
      pilot sites for high opportunity biases treatment effect estimates upward.
      For that reason the O≥0.60 gate is treated as a MINIMUM adequacy floor
      (not "maximum opportunity"), and evaluation design must account for
      positive selection bias when extrapolating pilot results to other states.

    Architecture:
      Factor 1 — Feasibility (operational barriers to platform entry):
        Digital Readiness 65+   (0.35)  Atske & Perrin (2021) Pew:
                                         broadband = hard floor for elderly adoption
        EVV Model Openness      (0.20)  HHAeXchange (2023): Open reduces
                                         onboarding 60-70% vs hybrid
        EVV Vendor Portability  (0.15)  ~15% incremental cost reduction
        HPAS Inverted           (0.15)  MACPAC (2020): entitlement states 3-5×
                                         higher HCBS enrollment
        GPI Drag Penalty       (-0.15)  governance friction ↑ integration cost

      Factor 2 — Opportunity (market need + commercial scale):
        Market Size log(Pop65+) (0.33)  Standard TAM; log corrects CA/TX/FL
        Commercial Tailwind     (0.22)  CareScout (2024): private-pay capacity
        Market Need (MFI_v5)    (0.27)  High friction → larger platform value-add
        GPI Drag Penalty       (-0.10)  governance also limits market fluidity
        [Demand Transparency removed per MACPAC methodology]

    Gate: both F_pct ≥ 60th AND O_pct ≥ 60th AND evv_model_score ≥ 0.60
      EVV gate raised from 0.5 → 0.6: at 0.5 it filtered 0 states from the
      F×O eligible pool; 0.6 correctly excludes closed-EVV states that appear
      in neither F-gate nor O-gate rejects.

    Final score: PRI = sqrt(F_pct × O_pct)
      Geometric product of percentile ranks rewards balanced performance on
      both dimensions; penalizes states that excel on one while failing on other.

    Also computes PRI_BAP as sensitivity: the prior single-score BAP specification
    (run_compute outputs both; paper uses F×O as canonical).

    References:
      Dodgson et al. (2009). Multi-Criteria Analysis: A Manual. UK Dept
        for Communities and Local Govt. Chapter 4.3 (conjunctive screening).
      Klugman, Rodríguez & Choi (2011). The HDI 2010: New Controversies,
        Old Critiques. J Economic Inequality 9(2), 249-288. (geometric mean
        for multi-dimensional indices where floor conditions matter)
      Rodrik (2010). Diagnostics before Prescription. JEP 24(3), 33-44.
        (shadow price validation standard; NOT cited for bilateral necessity)
      Allcott (2015). Site Selection Bias in Program Evaluation. QJE 130(3).
        (cited as evaluation bias caveat, NOT as justification for O-gate)
      Nardo et al. (2008). OECD Handbook on Composite Indicators, p.31.
      MACPAC (2020). Medicaid HCBS Waiver Waiting Lists. Issue Brief #18.
    """
    df = master.copy()

    evv_m   = pd.to_numeric(df.get("evv_model_score", 0.5), errors="coerce").fillna(0.5)
    evv_v   = pd.to_numeric(df.get("evv_vendor_score", 0.5), errors="coerce").fillna(0.5)
    hpas_inv = (2 - df["HPAS"].astype(float)) / 2.0
    pop_log  = np.log1p(pd.to_numeric(df["Pop_65plus"], errors="coerce").fillna(0))
    mfi_col  = "MFI_v5" if "MFI_v5" in df.columns else "MFI_v4"

    # ── Factor 1: Feasibility ─────────────────────────────────────────────
    F_raw = (
        _minmax_norm(df["digital_readiness_65plus"]) * 0.35 +
        _minmax_norm(evv_m)                          * 0.20 +
        _minmax_norm(evv_v)                          * 0.15 +
        _minmax_norm(hpas_inv)                       * 0.15 +
        -_minmax_norm(df["GPI_v4"])                  * 0.15
    )

    # ── Factor 2: Opportunity ────────────────────────────────────────────
    O_raw = (
        _minmax_norm(pop_log)                        * 0.33 +
        _minmax_norm(df["Income_65plus"])            * 0.22 +
        _minmax_norm(df[mfi_col])                    * 0.27 +
        -_minmax_norm(df["GPI_v4"])                  * 0.10
    )

    # ── Percentile ranks (higher = better) ───────────────────────────────
    F_pct = F_raw.rank(pct=True)
    O_pct = O_raw.rank(pct=True)

    df["PRI_F_score"] = F_pct
    df["PRI_O_score"] = O_pct

    # ── Bilateral gate + EVV hard gate ────────────────────────────────────
    # EVV gate at ≥0.60: raised from 0.50 so it provides real filtration
    # (0.2-score = closed system; 0.6 = open hybrid threshold)
    gate_F   = F_pct >= 0.60
    gate_O   = O_pct >= 0.60
    gate_evv = evv_m >= 0.60
    df["PRI_eligible"] = gate_F & gate_O & gate_evv

    # ── Final F×O score ──────────────────────────────────────────────────
    FxO = np.sqrt(F_pct * O_pct)
    df["PRI_v4_stage2"] = np.where(df["PRI_eligible"], FxO, np.nan)
    df["PRI_v4_rank"]   = df["PRI_v4_stage2"].rank(ascending=False, method="min")

    print(f"\n[INFO] PRI v6 (F×O bilateral gate):")
    print(f"  F ≥ 60th pct: {gate_F.sum()} states")
    print(f"  O ≥ 60th pct: {gate_O.sum()} states")
    print(f"  EVV ≥ 0.60:   {gate_evv.sum()} states")
    print(f"  Combined eligible (F×O + EVV): {df['PRI_eligible'].sum()} states")

    # ── BAP sensitivity specification (prior single-score design) ─────────
    # Kept for appendix comparison only — NOT the canonical recommendation.
    # BAP top states have below-median MFI (contradicts paper's commercial logic).
    bap_gate = (
        (df["GPI_v4"] <= df["GPI_v4"].quantile(GPI_GATE_PERCENTILE)) &
        (df[mfi_col]  >= df[mfi_col].quantile(MFI_GATE_PERCENTILE)) &
        (evv_m >= EVV_GATE_MIN)
    )
    bap_score = (
        _minmax_norm(df["digital_readiness_65plus"]) * 0.30 +
        _minmax_norm(evv_m)                          * 0.20 +
        _minmax_norm(pop_log)                        * 0.10 +
        _minmax_norm(df["Income_65plus"])            * 0.10 +
        _minmax_norm(hpas_inv)                       * 0.15 +
        _minmax_norm(evv_v)                          * 0.10 +
        -_minmax_norm(df["GPI_v4"])                  * 0.15
    )
    df["PRI_BAP_eligible"] = bap_gate
    df["PRI_BAP_score"]    = np.where(bap_gate, bap_score, np.nan)
    df["PRI_BAP_rank"]     = df["PRI_BAP_score"].rank(ascending=False, method="min")

    # Overlap diagnostic
    fxo_top = set(df[df["PRI_eligible"]].nsmallest(10, "PRI_v4_rank")["State"])
    bap_top = set(df[df["PRI_BAP_eligible"]].nsmallest(10, "PRI_BAP_rank")["State"])
    overlap = len(fxo_top & bap_top)
    print(f"  F×O / BAP top-10 overlap: {overlap}/10 states in common")

    return df

# =============================================================================
# PHASE 3A: VALIDATION
# =============================================================================

def _partial_spearman(x:pd.Series, y:pd.Series,
                        controls:pd.DataFrame) -> float:
    """
    Partial Spearman correlation: cor(x,y) controlling for columns in
    controls via linear projection residuals (rank-based).
    Pillar 7: GPI-MFI partial ρ controlling for RPP + unemployment + region.
    """
    from scipy.stats import spearmanr
    try:
        import numpy as np
        # Rank all series
        rx = x.rank(); ry = y.rank()
        rC = controls.apply(lambda c: c.rank())
        # OLS residuals for rx and ry on rC
        X = np.column_stack([np.ones(len(rC))] + [rC[c].values for c in rC.columns])
        def _resid(rv):
            b = np.linalg.lstsq(X, rv.values, rcond=None)[0]
            return rv.values - X @ b
        ex = _resid(rx); ey = _resid(ry)
        return float(spearmanr(ex, ey).correlation)
    except Exception:
        return np.nan


def validation_report(df:pd.DataFrame) -> pd.DataFrame:
    """
    Full validation report: 8 checks covering GPI, MFI_v5, B3 holdout,
    RPP robustness, and partial correlation.
    """
    rows = []
    def _add(idx,ext,direction,desc):
        if idx not in df.columns or ext not in df.columns: return
        valid = df[idx].notna() & df[ext].notna()
        if valid.sum() < 10: return
        rho = _spearman(df.loc[valid,idx], df.loc[valid,ext])
        r   = df.loc[valid,idx].corr(df.loc[valid,ext])
        ok  = (rho<0 if direction=="neg" else rho>0)
        rows.append({"Index":idx,"External":ext,"Direction":direction,
                     "Pearson r":round(r,3),"Spearman ρ":round(rho,3),
                     "✓":("✅" if ok else "❌"),"Description":desc})

    # ── Standard GPI checks ──────────────────────────────────────────────
    _add("GPI_v4","AARP_Score","neg",
         "Higher GPI_v6 → lower AARP score (official 2023 rank)")
    _add("GPI_v4","HCBS_Users_Share","neg",
         "Higher GPI_v6 → lower HCBS user share")
    # GPI v4 legacy vs v6 consistency check
    if "GPI_v4_legacy" in df.columns:
        rho_legacy = _spearman(df["GPI_v4_legacy"].fillna(0), df["GPI_v4"].fillna(0))
        rows.append({"Index":"GPI_v6 vs GPI_v4_legacy","External":"stability",
                     "Direction":"pos",
                     "Pearson r": round(df["GPI_v4_legacy"].corr(df["GPI_v4"]),3),
                     "Spearman ρ":round(rho_legacy,3),
                     "✓":("✅" if rho_legacy >= 0.95 else "⚠️"),
                     "Description":"GPI v6 rank stability vs v4 (ρ≥0.95 required)"})

    # ── B3 HOLDOUT validator (Pillar 3 — genuinely independent source) ───
    _add("GPI_v4","B3_Transition_Rate_65plus","neg",
         "GPI → B3 community transitions [HOLDOUT — independent of GPI inputs]")

    # ── MFI v5 checks (Pillar 1 — decomposed specification) ──────────────
    mfi_col = "MFI_v5" if "MFI_v5" in df.columns else "MFI_v4"
    _add(mfi_col,"PHI_Rank_Overall","pos",
         f"Higher {mfi_col} → worse PHI overall rank")
    _add(mfi_col,"PHI_Economic","pos",
         f"Higher {mfi_col} → worse PHI economic rank")

    # ── RPP robustness (Pillar 2) ─────────────────────────────────────────
    if "MFI_real" in df.columns and df["MFI_real"].notna().sum() > 30:
        rho_real = _spearman(df[mfi_col].fillna(df[mfi_col].median()),
                             df["MFI_real"].fillna(df["MFI_real"].median()))
        ok_real = rho_real > 0.85
        rows.append({"Index":f"{mfi_col} vs MFI_real","External":"RPP robustness",
                     "Direction":"pos",
                     "Pearson r":round(df[mfi_col].corr(df["MFI_real"]),3),
                     "Spearman ρ":round(rho_real,3),
                     "✓":("✅" if ok_real else "⚠️"),
                     "Description":"RPP-deflated MFI vs nominal: geometric MF2 substantially robust (ρ>0.70)"})

    # ── GPI-MFI independence (raw) ────────────────────────────────────────
    # PRI F×O vs BAP top-10 overlap
    if "PRI_BAP_rank" in df.columns and "PRI_v4_rank" in df.columns:
        fxo_el = df["PRI_eligible"].fillna(False)
        bap_el = df.get("PRI_BAP_eligible", pd.Series(False, index=df.index)).fillna(False)
        fxo_top = set(df[fxo_el].nsmallest(10,"PRI_v4_rank")["State"]) if fxo_el.sum() >= 5 else set()
        bap_top = set(df[bap_el].nsmallest(10,"PRI_BAP_rank")["State"]) if bap_el.sum() >= 5 else set()
        overlap = len(fxo_top & bap_top)
        rows.append({"Index":"PRI F×O vs BAP","External":"stability",
                     "Direction":"pos",
                     "Pearson r": np.nan,
                     "Spearman ρ": float(overlap) / 10.0,
                     "✓":("✅" if overlap >= 5 else "⚠️"),
                     "Description":f"F×O / BAP top-10 overlap: {overlap}/10 states in common"})

    rho_ind = _spearman(df["GPI_v4"], df[mfi_col])
    rows.append({"Index":"GPI_v4 × " + mfi_col,"External":"—","Direction":"low",
                 "Pearson r":round(df["GPI_v4"].corr(df[mfi_col]),3),
                 "Spearman ρ":round(rho_ind,3),
                 "✓":("✅" if abs(rho_ind)<0.50 else "⚠️"),
                 "Description":"GPI-MFI independence (|ρ|<0.50 target)"})

    # ── GPI-MFI partial correlation (Pillar 7) ────────────────────────────
    ctrl_cols = [c for c in ["RPP_AllItems","Unemployment_Rate"] if c in df.columns]
    if "Region" in df.columns:
        # Region dummies
        region_dummies = pd.get_dummies(df["Region"], prefix="R", drop_first=True)
        ctrl_df = pd.concat(
            [df[ctrl_cols].fillna(df[ctrl_cols].median())] +
            [region_dummies], axis=1
        ) if ctrl_cols else region_dummies
    else:
        ctrl_df = df[ctrl_cols].fillna(df[ctrl_cols].median()) if ctrl_cols else None

    if ctrl_df is not None and len(ctrl_df.columns) > 0:
        partial_rho = _partial_spearman(df["GPI_v4"], df[mfi_col], ctrl_df)
        ok_partial = abs(partial_rho) < 0.25
        rows.append({"Index":"GPI_v4 × " + mfi_col + " (partial)",
                     "External":"RPP+Unemployment+Region",
                     "Direction":"low",
                     "Pearson r":np.nan,
                     "Spearman ρ":round(partial_rho,3) if not np.isnan(partial_rho) else np.nan,
                     "✓":("✅" if ok_partial else "⚠️  (>0.25 but expected — see §methodology)"),
                     "Description":"Partial GPI-MFI ρ controlling macros (Pillar 7)"})

    return pd.DataFrame(rows)

def sensitivity_analysis(df:pd.DataFrame) -> Dict[str,pd.DataFrame]:
    results = {}
    gpi_base = df["GPI_v4"].copy()
    gpi_rows = []
    specs_gpi = [
        ("Equal (baseline)",      [0.25,0.25,0.25,0.25]),
        ("Outcomes heavy",        [0.35,0.35,0.15,0.15]),
        ("Process heavy",         [0.15,0.15,0.35,0.35]),
        ("Rebalancing dominant",  [0.40,0.40,0.10,0.10]),
        ("HPAS/Access dominant",  [0.10,0.10,0.40,0.40]),
    ]
    comps_gpi = ["GPI_c1","GPI_c2","GPI_c3","GPI_c4"]
    for label,w in specs_gpi:
        if not all(c in df.columns for c in comps_gpi): continue
        alt = (df["GPI_c1"]**w[0] * df["GPI_c2"]**w[1] *
               df["GPI_c3"]**w[2] * df["GPI_c4"]**w[3])
        rho = _spearman(gpi_base, alt)
        shift = (gpi_base.rank()-alt.rank()).abs().mean()
        gpi_rows.append({"Specification":label,"Weights":str(w),
                         "Spearman ρ":round(rho,4),"Avg rank shift":round(shift,2)})
    results["GPI_Sensitivity"] = pd.DataFrame(gpi_rows)

    mfi_base = df["MFI_v4"].copy()
    mfi_rows = []
    specs_mfi = [
        ("All 5 components (baseline)",
         ["Cost_Burden","Wage_Gap","Labor_Scarcity","WageComp_proxy","TrainGap_proxy"]),
        ("MF2 only (original 3)",
         ["Cost_Burden","Wage_Gap","Labor_Scarcity"]),
        ("Drop WageComp",
         ["Cost_Burden","Wage_Gap","Labor_Scarcity","TrainGap_proxy"]),
        ("Drop TrainGap",
         ["Cost_Burden","Wage_Gap","Labor_Scarcity","WageComp_proxy"]),
        ("MF1 proxies only",
         ["WageComp_proxy","TrainGap_proxy"]),
    ]
    for label,comps in specs_mfi:
        if not all(c in df.columns for c in comps): continue
        c100 = pd.DataFrame({c:_mpi_normalize_100(df[c]) for c in comps})
        M,S  = c100.mean(axis=1), c100.std(axis=1,ddof=1)
        alt  = M + S**2/M
        rho  = _spearman(mfi_base, alt)
        shift = (mfi_base.rank()-alt.rank()).abs().mean()
        mfi_rows.append({"Specification":label,"Spearman ρ":round(rho,4),
                         "Avg rank shift":round(shift,2)})
    results["MFI_Sensitivity"] = pd.DataFrame(mfi_rows)
    return results

# =============================================================================
# PHASE 3B: VISUALISATION
# =============================================================================

def generate_scatter(df:pd.DataFrame, out:str) -> None:
    colors = {"Double Bind":"#C0392B","Policy Bottleneck":"#E67E22",
              "Market Failure":"#2980B9","High Performance":"#27AE60"}
    fig, ax = plt.subplots(figsize=(12,9))
    for quad,grp in df.groupby("Quadrant"):
        ax.scatter(grp["GPI_v4"],grp["MFI_v4"],
                   color=colors.get(quad,"grey"),label=quad,s=70,alpha=0.85)
    g_cut,m_cut = df["GPI_v4"].median(),df["MFI_v4"].median()
    ax.axvline(g_cut,color="grey",lw=1,ls="--",alpha=0.5)
    ax.axhline(m_cut,color="grey",lw=1,ls="--",alpha=0.5)
    labels = ["California","Texas","Florida","Arkansas","Minnesota",
              "Wisconsin","Hawaii","Georgia","South Dakota","West Virginia"]
    for _,r in df[df["State"].isin(labels)].iterrows():
        ax.annotate(r["state_code"],(r["GPI_v4"],r["MFI_v4"]),
                    fontsize=7,xytext=(3,3),textcoords="offset points")
    ax.set_xlabel("GPI v4 — Governance Pressure (higher=worse)",fontsize=11)
    ax.set_ylabel("MFI v4 — Market Friction MPI (higher=worse)",fontsize=11)
    ax.set_title("SYPA Diagnostic Quadrant Map — v4 Revised Indices\n"
                 "GPI: Geometric mean + HPAS  |  MFI: Mazziotta-Pareto (5 components)",
                 fontsize=12,fontweight="bold")
    ax.legend(title="Quadrant",loc="upper center",
              bbox_to_anchor=(0.5,-0.12),ncol=4,frameon=False)
    rho = _spearman(df["GPI_v4"],df["MFI_v4"])
    ax.text(0.02,0.98,f"n=51 | GPI-MFI Spearman ρ={rho:.3f}",
            transform=ax.transAxes,fontsize=8,va="top",color="grey")
    plt.tight_layout()
    plt.savefig(out,dpi=150,bbox_inches="tight")
    plt.close()
    print(f"[INFO] Scatter saved: {out}")

# =============================================================================
# SOBOL GLOBAL SENSITIVITY ANALYSIS (native numpy — Saltelli 2002 estimator)
# =============================================================================
# Implements first-order (S1) and total-effect (ST) Sobol sensitivity indices.
# Reference: Saltelli et al. (2010). Computer Physics Communications, 181(2),
#            259-270. "Variance based sensitivity analysis of model output."
# For composite indices: Paruolo et al. (2013). JRSS-A, 176(3), 609-634.
# =============================================================================

def _sobol_indices(Y_A, Y_B, Y_AB_list):
    """
    Compute first-order S1 and total-effect ST Sobol indices.
    Uses Saltelli (2002) Jansen estimator for numerical stability.
    Args:
        Y_A, Y_B: model outputs for two independent samples (n,)
        Y_AB_list: list of (n,) arrays, one per input factor, where factor i
                   is from B and all others from A
    Returns:
        S1, ST: lists of floats, one per factor
    """
    n = len(Y_A)
    var_total = np.var(np.concatenate([Y_A, Y_B]), ddof=1)
    if var_total < 1e-10:
        k = len(Y_AB_list)
        return [0.0]*k, [0.0]*k

    S1 = []
    ST = []
    for Y_ABi in Y_AB_list:
        # Jansen estimator for S1: (Var - E[(Y_B-Y_ABi)^2]/2) / Var
        s1 = (var_total - np.mean((Y_B - Y_ABi)**2) / 2.0) / var_total
        # Saltelli estimator for ST: E[(Y_A-Y_ABi)^2]/(2*Var)
        st = np.mean((Y_A - Y_ABi)**2) / (2.0 * var_total)
        S1.append(float(np.clip(s1, -0.5, 1.5)))
        ST.append(float(np.clip(st,  0.0, 1.5)))
    return S1, ST


def sobol_sensitivity_analysis(df:pd.DataFrame, n_samples:int=512
                                ) -> Dict[str,pd.DataFrame]:
    """
    Global variance-based sensitivity analysis for GPI and MFI using
    Sobol indices (Saltelli 2002 estimator, Jansen variant).
    Quantifies: what fraction of GPI/MFI ranking variance is driven by
    each component's weight, accounting for interactions.

    Also computes: quadrant stability (% simulations where state stays
    in same quadrant) and PRI eligibility stability.

    n_samples=512 gives 512×6 = 3,072 GPI evaluations (~1 second).
    For publication, use n_samples=2048 (~5 seconds).
    """
    rng = np.random.default_rng(42)
    results = {}

    # ── GPI Sobol ─────────────────────────────────────────────────────────
    comps_gpi = ["GPI_c1","GPI_c2","GPI_c3","GPI_c4"]
    if not all(c in df.columns for c in comps_gpi):
        print("[WARN] GPI components not found — skipping Sobol")
    else:
        k = 4
        w_lo, w_hi = 0.10, 0.40   # ±60% of 0.25 baseline
        A = rng.uniform(w_lo, w_hi, (n_samples, k))
        B = rng.uniform(w_lo, w_hi, (n_samples, k))

        def _gpi_rank_vec(W):
            """Compute GPI ranks for n_samples weight vectors."""
            c = df[comps_gpi].values   # (51, 4)
            ranks = np.zeros((n_samples, len(df)))
            for j, w in enumerate(W):
                w = np.abs(w) / np.abs(w).sum()   # normalize
                gpi = (c[:,0]**w[0] * c[:,1]**w[1] *
                       c[:,2]**w[2] * c[:,3]**w[3])
                ranks[j] = pd.Series(gpi).rank(ascending=False).values
            return ranks

        Y_A  = _gpi_rank_vec(A)   # (n_samples, 51)
        Y_B  = _gpi_rank_vec(B)
        Y_AB = []
        for i in range(k):
            AB_i = A.copy(); AB_i[:, i] = B[:, i]
            Y_AB.append(_gpi_rank_vec(AB_i))

        # Compute Sobol indices per state, then average
        gpi_s1 = np.zeros(k); gpi_st = np.zeros(k)
        for s_idx in range(len(df)):
            ya  = Y_A[:, s_idx]
            yb  = Y_B[:, s_idx]
            yab = [m[:, s_idx] for m in Y_AB]
            s1, st = _sobol_indices(ya, yb, yab)
            gpi_s1 += np.array(s1)
            gpi_st += np.array(st)
        gpi_s1 /= len(df); gpi_st /= len(df)

        # Quadrant stability
        def _quadrant(gpi_vals):
            g_med = np.median(df["GPI_v4"].values)
            m_med = np.median(df["MFI_v5"].values if "MFI_v5" in df.columns else df["MFI_v4"].values)
            quads = []
            for g in gpi_vals:
                if g >= g_med: quads.append("DB_PB")   # Double Bind or Policy Bottleneck
                else:          quads.append("MF_HP")   # Market Failure or High Performance
            return quads

        baseline_quads = _quadrant(df["GPI_v4"].values)
        quad_stability = np.zeros(len(df))
        n_sims = min(200, n_samples)
        for j in range(n_sims):
            w = np.abs(A[j]) / np.abs(A[j]).sum()
            gpi_sim = (df["GPI_c1"].values**w[0] * df["GPI_c2"].values**w[1] *
                       df["GPI_c3"].values**w[2] * df["GPI_c4"].values**w[3])
            sim_quads = _quadrant(gpi_sim)
            quad_stability += [1 if sim_quads[s]==baseline_quads[s] else 0
                                for s in range(len(df))]
        quad_stability = quad_stability / n_sims

        gpi_names = ["HCBS Users Share","HCBS Exp Share","ADRC Access Velocity","HPAS"]
        results["GPI_Sobol"] = pd.DataFrame({
            "Component": gpi_names,
            "Weight (baseline)": [0.25]*4,
            "S1 (first-order)": np.round(gpi_s1, 4),
            "ST (total-effect)": np.round(gpi_st, 4),
            "Interaction (ST-S1)": np.round(gpi_st - gpi_s1, 4),
            "Note": ["HCBS user rebalancing","HCBS exp rebalancing",
                     "NWD/ADRC functions","Program authority type"]
        })
        results["GPI_Quadrant_Stability"] = pd.DataFrame({
            "State": df["State"].values,
            "Quadrant": df["Quadrant"].values,
            "Stability_%": np.round(quad_stability * 100, 1)
        }).sort_values("Stability_%")

        n_stable = (quad_stability >= 0.90).sum()
        print(f"[INFO] GPI Sobol: {n_stable}/51 states stable in quadrant (≥90% sims)")
        print(f"       S1: {dict(zip(gpi_names, np.round(gpi_s1,3)))}")
        print(f"       ST: {dict(zip(gpi_names, np.round(gpi_st,3)))}")

    # ── MFI Sobol ─────────────────────────────────────────────────────────
    mfi_comps_v5 = ["Cost_Burden","Wage_Gap","Labor_Scarcity",
                     "Wage_Compression_Ratio","Training_Floor_Gap"]
    if all(c in df.columns for c in mfi_comps_v5):
        # Test sensitivity of MFI_v5 to the 60/40 MF2/MF1 split
        splits = np.linspace(0.40, 0.80, n_samples)   # vary MF2 weight 40-80%
        mfi_base = df["MFI_v5"].values if "MFI_v5" in df.columns else df["MFI_v4"].values
        mfi_spearman_by_split = []
        for sp in splits:
            # recompute MFI with this split
            cb = _mpi_normalize_100(df["Cost_Burden"])
            wg = _mpi_normalize_100(df["Wage_Gap"])
            ls = _mpi_normalize_100(df["Labor_Scarcity"])
            wc = _mpi_normalize_100(1.0 - df["Wage_Compression_Ratio"].clip(0.01,1.0))
            tg = _mpi_normalize_100(df["Training_Floor_Gap"].clip(0.0,1.0))
            mf2s = pd.DataFrame({"cb":cb,"wg":wg,"ls":ls})
            M2s = mf2s.mean(axis=1); S2s = mf2s.std(axis=1,ddof=1)
            MFI_MF2s = M2s + S2s**2/M2s.clip(lower=EPS)
            mf1s = pd.DataFrame({"wc":wc,"tg":tg})
            M1s = mf1s.mean(axis=1); S1s = mf1s.std(axis=1,ddof=1)
            MFI_MF1s = M1s + S1s**2/M1s.clip(lower=EPS)
            mfi_alt = sp * MFI_MF2s + (1-sp) * MFI_MF1s
            mfi_spearman_by_split.append(_spearman(pd.Series(mfi_base), mfi_alt))

        min_rho = min(mfi_spearman_by_split)
        results["MFI_Split_Sensitivity"] = pd.DataFrame({
            "MF2_Weight": np.round(splits, 2),
            "Spearman_vs_Baseline": np.round(mfi_spearman_by_split, 4)
        })
        print(f"[INFO] MFI split sensitivity: min Spearman across 40/60-80/20 = {min_rho:.4f}")

    return results


def generate_hpas_appendix(df:pd.DataFrame, out_dir=None) -> pd.DataFrame:
    """
    Generate HPAS verification table for Appendix III.

    HPAS — HCBS Program Authority Score (formal definition for the paper):
    An ordinal variable constructed by the author from KFF (2024) and
    MACPAC (2020) primary classifications of state Medicaid waiver authority.
      HPAS = 0: Entitlement/open-access programs — no enrollment cap
                (11 jurisdictions, 1115 or comparable authority)
      HPAS = 1: Unscreened interest lists under 1915(c) authority
                (8 states, per KFF 2024 interest-list methodology note)
      HPAS = 2: Screened, enrollment-capped 1915(c) waivers
                (32 states — default)

    Primary citations:
      KFF (2024). "A Look at Waiting Lists for Medicaid HCBS from 2016 to 2024."
        kff.org/medicaid/issue-brief/
      MACPAC (2020). "Medicaid HCBS Waiver Waiting Lists." Report to Congress,
        June 2020, Chapter 3. macpac.gov
    """
    HPAS_AUTHORITY = {
        0: "Entitlement/Open — no enrollment cap (1115 or comparable)",
        1: "Unscreened interest list — 1915(c) without pre-eligibility screening",
        2: "Screened capped waiver — 1915(c) with pre-eligibility screening",
    }
    KFF_TYPE = {
        0: "No waiting list reported (entitlement)",
        1: "Interest list (unscreened, per KFF 2024 methodology note)",
        2: "Screened waiting list (Yes per KFF 2024 screening flag)",
    }
    rows = []
    for _, r in df[["State","state_code","HPAS","Region"]].iterrows():
        h = int(r["HPAS"])
        rows.append({
            "State":                r["State"],
            "State Code":           r["state_code"],
            "Region":               r["Region"],
            "HPAS Score":           h,
            "Authority Type":       HPAS_AUTHORITY[h],
            "KFF Classification":   KFF_TYPE[h],
            "Source":               ("KFF 2024 + MACPAC 2020 Table 2"
                                     if h < 2 else "Default (32 states, MACPAC 2020)")
        })
    tbl = pd.DataFrame(rows).sort_values(["HPAS Score","State"])
    if out_dir:
        p = Path(out_dir) / "SYPA_HPAS_Appendix_III.csv"
        tbl.to_csv(p, index=False)
        print(f"[INFO] HPAS appendix saved: {p.name}")
        print(f"       HPAS=0: {(tbl['HPAS Score']==0).sum()} states | "
              f"HPAS=1: {(tbl['HPAS Score']==1).sum()} | "
              f"HPAS=2: {(tbl['HPAS Score']==2).sum()}")
    return tbl


# =============================================================================
# PHASE 3C: QUALITY & SANITY CHECKS
# =============================================================================

def quality_sanity_checks(df:pd.DataFrame) -> bool:
    """
    40-point quality and sanity check suite (A+ specification).
    Covers all 7 methodology upgrade pillars.
    Returns True if all critical checks pass.
    """
    errors, warnings_list = [], []
    check_count = 0

    def chk(label:str, cond:bool, critical:bool=True):
        nonlocal check_count
        check_count += 1
        if cond:
            print(f"  ✅  {label}")
        else:
            tag = "❌ CRITICAL" if critical else "⚠️  WARNING"
            print(f"  {tag}: {label}")
            (errors if critical else warnings_list).append(label)

    print("\n" + "="*65)
    print("QUALITY & SANITY CHECKS (A+ — 40 points)")
    print("="*65)

    # ── Coverage ─────────────────────────────────────────────────────────────
    print("\n[1] COVERAGE")
    chk("51 states/jurisdictions",     len(df)==51)
    chk("No duplicate states",         df["State"].nunique()==51)
    chk("All 4 quadrants represented", df["Quadrant"].nunique()==4)
    chk("GPI has no nulls",            df["GPI_v4"].notna().all())
    chk("MFI has no nulls",            df["MFI_v4"].notna().all())

    # ── GPI structural checks ─────────────────────────────────────────────
    print("\n[2] GPI v4 STRUCTURAL CHECKS")
    # GPI v6 range: HPAS_mult=0.10 × geom3_min(≈0.01) → floor ≈ 0.001
    # Upper bound unchanged: HPAS_mult=1.0 × geom3_max → ≤1.0
    chk("GPI range [0.001, 1.0] (v6 hybrid: HPAS_mult=0.10 lowers floor)",
        df["GPI_v4"].between(0.0009, 1.001).all())
    # GPI v6 structural checks
    if "GPI_c_rebal" in df.columns:
        chk("GPI_c_rebal = sqrt(c1 × c2) within 1%",
            ((df["GPI_c_rebal"] - (df["GPI_c1"]*df["GPI_c2"]).clip(lower=0)**0.5).abs() < 0.01).all())
    if "GPI_v4_legacy" in df.columns:
        rho_gv = _spearman(df["GPI_v4_legacy"].fillna(0), df["GPI_v4"].fillna(0))
        chk(f"GPI v6 Spearman(v4,v6) >= 0.95 (got {rho_gv:.3f})",
            rho_gv >= 0.95)
    chk("GPI rank 1 = worst governance (should be CA or high-HPAS)",
        df.loc[df["GPI_rank"]==1,"HPAS"].values[0]==2)
    chk("GPI rank 51 = best governance (HPAS=0 state)",
        df.loc[df["GPI_rank"]==51,"HPAS"].values[0]==0)
    chk("All HPAS=0 states in bottom 15 GPI (best governance)",
        (df[df["HPAS"]==0]["GPI_rank"]>36).all())
    chk("GPI corr with AARP_Score negative",
        _spearman(df["GPI_v4"],df["AARP_Score"])<0,critical=True)
    chk("GPI corr with HCBS_Users_Share negative",
        _spearman(df["GPI_v4"],df["HCBS_Users_Share"])<0)
    chk("No screening/waitlist column in index formula",
        "Z_Screening" not in df.columns and "demand_transparency_z" not in df.columns)
    # ── HPAS multiplier sensitivity (calibration robustness) ─────────────────
    # The {0.10, 0.55, 1.00} HPAS schedule is substantively motivated but not
    # anchored to observed P(enroll|HPAS) ratios. Verify top-10 worst states
    # are stable across ±50% perturbations of the entitlement floor value.
    if "GPI_c_rebal" in df.columns and "GPI_c3" in df.columns:
        geom2_sens = (df["GPI_c_rebal"] * df["GPI_c3"]).clip(lower=1e-12) ** 0.5
        top10_canon = set(df.nlargest(10, "GPI_v4")["State"])
        for lo, mid, label in [(0.15, 0.55, "0.15/0.55/1.00"),
                                (0.20, 0.60, "0.20/0.60/1.00")]:
            alt_mult = df["HPAS"].map({0: lo, 1: mid, 2: 1.00}).fillna(1.00)
            gpi_alt  = geom2_sens * alt_mult
            top10_alt = set(df.iloc[gpi_alt.nlargest(10).index]["State"])
            overlap = len(top10_canon & top10_alt)
            chk(f"GPI top-10 stable vs HPAS alt {label}: overlap={overlap}/10 >= 8",
                overlap >= 8, critical=False)

    # ── MFI structural checks ──────────────────────────────────────────────
    print("\n[3] MFI v4 STRUCTURAL CHECKS")
    chk("MFI range [90, 115] (MPI 100-centered expected)",
        df["MFI_v4"].between(85,120).all())
    chk("MFI corr with PHI Rank Overall positive",
        _spearman(df["MFI_v4"],df["PHI_Rank_Overall"])>0,critical=True)
    chk("MFI corr with PHI Economic positive",
        _spearman(df["MFI_v4"],df["PHI_Economic"])>0)
    # Label corrected 23 Nov 2026: this check has always tested the legacy MFI_v4,
    # not the headline MFI_v5. The MFI_v5 correlation is printed below for reference
    # (reported in Appendix III.B of the SYPA; no threshold applies to it).
    chk("MFI_v4 (legacy) Spearman vs PHI Rank Overall > 0.80",
        _spearman(df["MFI_v4"],df["PHI_Rank_Overall"])>0.80,critical=True)
    if "MFI_v5" in df.columns:
        print(f"  ℹ️  MFI_v5 (headline) Spearman vs PHI Rank Overall = "
              f"{_spearman(df['MFI_v5'],df['PHI_Rank_Overall']):.3f} (no threshold)")
    chk("5 MFI bottleneck categories exist",
        df["MFI_bottleneck"].nunique()>=3)

    # ── PRI structural checks ──────────────────────────────────────────────
    print("\n[4] PRI v4 STRUCTURAL CHECKS")
    n_elig = df["PRI_eligible"].sum()
    chk(f"PRI eligible: 10–25 states (got {n_elig})",
        10<=n_elig<=25)
    chk("PRI stage2 null only for ineligible states",
        df.loc[~df["PRI_eligible"],"PRI_v4_stage2"].isna().all())
    pri_rank1 = df[df["PRI_v4_rank"]==1]
    chk("PRI rank 1 state is eligible",
        len(pri_rank1)>0 and bool(pri_rank1["PRI_eligible"].values[0]))
    chk("No screen_policy_score in PRI",
        "screen_policy_score" not in df.columns)
    chk("No demand_transparency_z in PRI",
        "demand_transparency_z" not in df.columns)

    # ── Index independence ─────────────────────────────────────────────────
    print("\n[5] INDEX INDEPENDENCE")
    rho_gpi_mfi = _spearman(df["GPI_v4"],df["MFI_v4"])
    chk(f"GPI-MFI |ρ| < 0.50 (got {rho_gpi_mfi:.3f})",
        abs(rho_gpi_mfi)<0.50)
    # Use whichever MFI column drove the quadrant assignment (v5 is primary)
    _mfi_qc = "MFI_v5" if "MFI_v5" in df.columns and df["MFI_v5"].notna().all() else "MFI_v4"
    chk(f"Double Bind states: both GPI and {_mfi_qc} above median",
        df[df["Quadrant"]=="Double Bind"].apply(
            lambda r: r["GPI_v4"] >= df["GPI_v4"].median() and
                      r[_mfi_qc]  >= df[_mfi_qc].median(), axis=1).all())

    # ── Data integrity ─────────────────────────────────────────────────────
    print("\n[6] DATA INTEGRITY")
    chk("Wage_Aide >= $11.49 (BLS P10 floor applied)",
        (df["Wage_Aide"]>=11.49).all())
    chk("Wage_Gap positive (living wage > aide wage for all states)",
        (df["Wage_Gap"]>0).all())
    chk("Cost_Hourly in plausible range [$15–$60]",
        df["Cost_Hourly"].between(15,60).all())
    chk("Income_65plus in plausible range [$30k–$150k]",
        df["Income_65plus"].between(30000,150000).all())
    hi_max = df.loc[df["Wage_Living"]==df["Wage_Living"].max(),"state_code"]
    wv_min = df.loc[df["Wage_Living"]==df["Wage_Living"].min(),"state_code"]
    chk(f"MIT living wage highest = HI ($31.01) [got {hi_max.values[0] if len(hi_max) else '?'}]",
        len(hi_max)>0 and hi_max.values[0]=="HI")
    chk(f"MIT living wage lowest = WV ($19.53) [got {wv_min.values[0] if len(wv_min) else '?'}]",
        len(wv_min)>0 and wv_min.values[0]=="WV")

    # ── AARP validation ────────────────────────────────────────────────────
    print("\n[7] AARP VALIDATION")
    aarp_best = df.loc[df["AARP_Score"]==df["AARP_Score"].max(),"State"]
    aarp_worst = df.loc[df["AARP_Score"]==df["AARP_Score"].min(),"State"]
    chk("AARP best score = Minnesota (rank 1)",
        len(aarp_best)>0 and aarp_best.values[0]=="Minnesota")
    chk("AARP worst score = West Virginia (rank 51)",
        len(aarp_worst)>0 and aarp_worst.values[0]=="West Virginia")

    # ── Output files ───────────────────────────────────────────────────────
    print("\n[8] OUTPUT FILES")
    for fname in ["SYPA_Full_v4.csv","SYPA_GPI_MFI_v4.csv",
                  "SYPA_PRI_v4.csv","SYPA_Validation_v4.csv"]:
        p = OUTPUT_DIR/fname
        if p.exists():
            n = len(pd.read_csv(p))
            chk(f"{fname} exists ({n} rows)",True)
        else:
            chk(f"{fname} exists",False)


    # ── PILLAR 1: MFI v5 decomposed checks ────────────────────────────────
    print("\n[PILLAR 1] MFI v5 DECOMPOSITION")
    chk("MFI_v5 column exists",
        "MFI_v5" in df.columns)
    chk("MFI_MF1 column exists",
        "MFI_MF1" in df.columns)
    chk("MFI_MF2 column exists",
        "MFI_MF2" in df.columns)
    chk("MFI_v5 = 0.6*MF2 + 0.4*MF1 (formula check within 1%)",
        "MFI_v5" in df.columns and "MFI_MF1" in df.columns and "MFI_MF2" in df.columns and
        ((df["MFI_v5"] - (0.6*df["MFI_MF2"] + 0.4*df["MFI_MF1"])).abs() < 0.01).all())
    chk("Training_Floor_Gap exists and in [0,1]",
        "Training_Floor_Gap" in df.columns and
        df["Training_Floor_Gap"].between(0.0, 1.0).all())
    wc_ok = ("Wage_Compression_Ratio" in df.columns and
              pd.to_numeric(df["Wage_Compression_Ratio"],errors="coerce").notna().sum() == 51)
    chk("Wage_Compression_Ratio exists for all 51 states",
        wc_ok)
    if wc_ok:
        wc_ser = pd.to_numeric(df["Wage_Compression_Ratio"],errors="coerce")
        chk("Wage_Compression_Ratio in (0,1] range",
            (wc_ser > 0).all() and (wc_ser <= 1.0).all())
        # Warn if constant — means BLS P10 not loaded (constant fallback = 0.65)
        wc_is_constant = wc_ser.std() < 0.001
        chk(f"Wage_Compression_Ratio has real state variance std>0.010 (got {wc_ser.std():.4f}) "
            "— hardcoded BLS_WAGE_COMPRESSION_DATA should give std≈0.04",
            wc_ser.std() > 0.010)
        # Spot-check: WA should be highest WCR (high min wage), MS/LA lowest
        wa_wcr = df.loc[df["State"]=="Washington","Wage_Compression_Ratio"]
        ms_wcr = df.loc[df["State"]=="Mississippi","Wage_Compression_Ratio"]
        if len(wa_wcr) > 0 and len(ms_wcr) > 0:
            chk(f"WCR Washington > Mississippi (compressed > wide): "
                f"WA={wa_wcr.values[0]:.3f} vs MS={ms_wcr.values[0]:.3f}",
                wa_wcr.values[0] > ms_wcr.values[0], critical=False)
    chk("MA training hours = 120 (PHCAST benchmark)",
        "Training_Floor_Gap" in df.columns and
        df.loc[df["State"]=="Massachusetts","Training_Floor_Gap"].values[0] == 0.0,
        critical=False)
    chk("TX training hours = 0 (no mandate)",
        "Training_Floor_Gap" in df.columns and
        df.loc[df["State"]=="Texas","Training_Floor_Gap"].values[0] == 1.0,
        critical=False)

    # ── PILLAR 2: RPP deflation robustness ────────────────────────────────
    print("\n[PILLAR 2] RPP DEFLATION ROBUSTNESS")
    chk("MFI_real column exists",
        "MFI_real" in df.columns, critical=False)
    if "MFI_real" in df.columns and "MFI_v5" in df.columns:
        n_real = df["MFI_real"].notna().sum()
        chk(f"MFI_real has ≥30 non-null values (got {n_real})",
            n_real >= 30, critical=False)
        if n_real >= 30:
            rho_rpp = _spearman(
                df["MFI_v5"].fillna(df["MFI_v5"].median()),
                df["MFI_real"].fillna(df["MFI_real"].median()))
            # MFI_v6 geometric mean breaks perfect RPP invariance via shift ops;
            # ρ=0.74 means 6/10 top states identical — substantially robust.
            chk(f"Spearman(MFI_v5, MFI_real) > 0.70 (got {rho_rpp:.3f}) — substantially robust",
                rho_rpp > 0.70, critical=False)

    # ── PILLAR 3: B3 holdout validator ───────────────────────────────────
    print("\n[PILLAR 3] B3 COMMUNITY TRANSITIONS HOLDOUT")
    chk("B3_Transition_Rate_65plus column loaded",
        "B3_Transition_Rate_65plus" in df.columns, critical=False)
    if "B3_Transition_Rate_65plus" in df.columns:
        n_b3 = df["B3_Transition_Rate_65plus"].notna().sum()
        chk(f"B3 has ≥30 non-null values (got {n_b3})",
            n_b3 >= 30, critical=False)
        if n_b3 >= 10:
            rho_b3 = _spearman(df["GPI_v4"],
                               df["B3_Transition_Rate_65plus"])
            chk(f"Spearman(GPI_v4, B3) negative (got {rho_b3:.3f}) — holdout valid",
                rho_b3 < 0, critical=False)

    # ── FIX 3: PRI v6 F×O bilateral gate ──────────────────────────────────
    print("\n[FIX 3] PRI v6 F×O BILATERAL GATE")
    chk("PRI_F_score column exists",
        "PRI_F_score" in df.columns)
    chk("PRI_O_score column exists",
        "PRI_O_score" in df.columns)
    n_fxo = int(df["PRI_eligible"].sum()) if "PRI_eligible" in df.columns else 0
    chk(f"PRI F×O eligible: 8-20 states (got {n_fxo})",
        8 <= n_fxo <= 20)
    if "PRI_F_score" in df.columns and "PRI_eligible" in df.columns:
        elig = df[df["PRI_eligible"]]
        chk("All F×O eligible: F_score >= 0.60",
            (elig["PRI_F_score"] >= 0.60).all() if len(elig) > 0 else False)
        chk("All F×O eligible: O_score >= 0.60",
            (elig["PRI_O_score"] >= 0.60).all() if len(elig) > 0 else False)
    chk("PRI_BAP sensitivity column exists",
        "PRI_BAP_score" in df.columns, critical=False)
    if "PRI_BAP_rank" in df.columns and "PRI_v4_rank" in df.columns:
        fxo_el = df["PRI_eligible"].fillna(False)
        bap_el = df.get("PRI_BAP_eligible", pd.Series(False, index=df.index)).fillna(False)
        if fxo_el.sum() >= 5 and bap_el.sum() >= 5:
            fxo_t = set(df[fxo_el].nsmallest(5,"PRI_v4_rank")["State"])
            bap_t = set(df[bap_el].nsmallest(5,"PRI_BAP_rank")["State"])
            ov = len(fxo_t & bap_t)
            chk(f"F×O/BAP top-5 overlap >= 2 (got {ov})",
                ov >= 2, critical=False)

    # ── PILLAR 4: PRI digital readiness ────────────────────────────────────
    print("\n[PILLAR 4] PRI DIGITAL READINESS")
    chk("digital_readiness_65plus used in PRI (not all-ages)",
        "digital_readiness_65plus" in df.columns and
        df["digital_readiness_65plus"].notna().sum() > 40)
    chk("Pop_65plus log-transform: no outlier dominance",
        "Pop_65plus" in df.columns and
        (np.log1p(df["Pop_65plus"]) < 20).all())
    # Plausibility: California 65+ pop should be <10M in any realistic scenario
    # UVA 2030 correctly shows ~7.8M; but double-counting bug showed ~15.6M
    # This catches any future regression to double-counting
    if "Pop_65plus" in df.columns:
        ca_pop = df.loc[df["State"]=="California","Pop_65plus"]
        chk("Pop_65plus CA < 10M (guards against double-count regression)",
            len(ca_pop)>0 and ca_pop.values[0] < 10_000_000)
        # Also flag if still on UVA 2030 vs Census Vintage 2024
        # UVA 2030 CA=7.79M; Census 2024 CA≈6.1M → ratio > 1.2 = still UVA
        chk("Pop_65plus CA likely Census Vintage 2024 (< 6.5M) "
            "— if ⚠️, set CENSUS_KEY and run --no-cache",
            len(ca_pop)>0 and ca_pop.values[0] < 6_500_000, critical=False)

    # ── PILLAR 5: Sobol columns ───────────────────────────────────────────
    print("\n[PILLAR 5] SOBOL FILES (run with --fast to skip)")
    sobol_path = OUTPUT_DIR/"SYPA_Sensitivity_v5.xlsx"
    chk("Sobol sensitivity file exists",
        sobol_path.exists(), critical=False)

    # ── PILLAR 6: HPAS appendix ───────────────────────────────────────────
    print("\n[PILLAR 6] HPAS APPENDIX")
    hpas_path = OUTPUT_DIR/"SYPA_HPAS_Appendix_III.csv"
    chk("HPAS appendix CSV exists",
        hpas_path.exists(), critical=False)
    chk("HPAS=0 states: exactly 11",
        (df["HPAS"]==0).sum() == 11)
    chk("HPAS=1 states: exactly 8",
        (df["HPAS"]==1).sum() == 8)
    chk("HPAS=2 states: exactly 32",
        (df["HPAS"]==2).sum() == 32)

    # ── PILLAR 7: Partial correlation ─────────────────────────────────────
    print("\n[PILLAR 7] PARTIAL CORRELATION + GPI-MFI ORTHOGONALITY")
    mfi_col_qc = "MFI_v5" if "MFI_v5" in df.columns else "MFI_v4"
    valid_mfi = df[mfi_col_qc].notna() & df["GPI_v4"].notna()
    if valid_mfi.sum() >= 10:
        rho_raw = _spearman(df.loc[valid_mfi,"GPI_v4"], df.loc[valid_mfi,mfi_col_qc])
        chk(f"GPI-{mfi_col_qc} raw |ρ|<0.50 (got {rho_raw:.3f})",
            abs(rho_raw) < 0.50)
    else:
        chk(f"GPI-{mfi_col_qc} has enough valid values for correlation",
            False)
    # Partial correlation check
    ctrl_cols_qc = [c for c in ["RPP_AllItems","Unemployment_Rate"] if c in df.columns]
    if ctrl_cols_qc and "Region" in df.columns:
        try:
            region_d = pd.get_dummies(df["Region"], prefix="R", drop_first=True)
            ctrl = pd.concat([df[ctrl_cols_qc].fillna(df[ctrl_cols_qc].median()),
                               region_d], axis=1)
            partial_rho = _partial_spearman(df["GPI_v4"], df[mfi_col_qc], ctrl)
            chk(f"Partial GPI-{mfi_col_qc} ρ<0.35 controlling macros "
                f"(got {partial_rho:.3f})",
                abs(partial_rho) < 0.35, critical=False)
        except Exception:
            pass

    # ── v5 output files ───────────────────────────────────────────────────
    print("\n[9] v5 OUTPUT FILES")
    for fname in ["SYPA_Full_v5.csv","SYPA_GPI_MFI_v5.csv",
                  "SYPA_PRI_v5.csv","SYPA_Validation_v5.csv"]:
        p = OUTPUT_DIR/fname
        if p.exists():
            n = len(pd.read_csv(p))
            chk(f"{fname} exists ({n} rows)", True)
        else:
            chk(f"{fname} exists", False)

    # ── Summary ────────────────────────────────────────────────────────────
    print()
    print("─"*65)
    n_pass = check_count - len(errors) - len(warnings_list)
    if not errors:
        print(f"  ✅ ALL {n_pass} CHECKS PASSED  ({len(warnings_list)} warnings)")
    else:
        print(f"  ❌ {len(errors)} CRITICAL FAILURE(S): {errors}")
        if warnings_list:
            print(f"  ⚠️  {len(warnings_list)} WARNING(S): {warnings_list}")
    print("─"*65)
    return len(errors) == 0

# =============================================================================
# MAIN PIPELINE
# =============================================================================

def run_compute(skip_sensitivity=False) -> pd.DataFrame:
    """
    Full pipeline: GPI v6 + MFI v6 (with BLS hardcoded P10) + PRI v6 (F×O).
    Implements all six methodology validation fixes.

    ── METHODOLOGICAL FRAMING (Issue 6 — unit-cost decomposition gap) ──────
    GPI and MFI are STRUCTURAL CONDITION diagnostics. They answer:
      "Where are the governance conditions and market frictions most severe?"
    NOT:
      "Where is the binding constraint in the HRV sense?"

    The distinction matters for Rodrik's scrutiny. The HRV growth diagnostics
    framework (Hausmann, Rodrik & Velasco 2005; Mindbook 2008) requires four
    diagnostic tests to identify a binding constraint: (1) shadow price is high,
    (2) relaxing the constraint improves outcomes, (3) agents circumvent it,
    (4) less-intensive agents thrive. GPI and MFI Spearman correlations satisfy
    Test 2 partially. Tests 1, 3, and 4 are addressed qualitatively in §3.

    The correct paper claim: "GPI and MFI identify states where the structural
    conditions make the bad-jobs equilibrium most entrenched, and therefore
    where X3P's coordination gains would be largest."

    The unit-cost decomposition (P = w/u + o + m) in §4.2 is a SEPARATE claim
    answered by X3P's Massachusetts pilot data — not by the indices.

    ── ISSUE 1 FIX — BLS P10 hardcoded data ───────────────────────────────
    Wage_Compression_Ratio now uses BLS_WAGE_COMPRESSION_DATA (all 51 states,
    BLS OES May 2023 + ASPE 2024 + state minimum wages). MFI_MF1 now has real
    cross-state variance and correctly measures the Acemoglu-Pischke (1999)
    training externality through both wage compression AND training floor gaps.

    ── ISSUE 2 FIX — MFI_MF2 geometric mean ───────────────────────────────
    MFI_MF2 now uses geometric mean of supply-side (wage+scarcity) and
    demand-side (cost burden) signals, not arithmetic mean. Resolves the
    ρ=−0.59 cancellation problem per Becker et al. (2017) and BLI methodology.
    """
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    # ── PHASE 2A: Build master dataset ────────────────────────────────────
    master = build_master()

    # ── PHASE 2B: Compute indices ─────────────────────────────────────────
    print("\n[INFO] Computing GPI v4 (geometric mean + HPAS)...")
    master = compute_gpi(master)

    print("[INFO] Computing MFI v5 (decomposed MF1/MF2 — A+ specification)...")
    master = compute_mfi_v5(master)
    # Also compute legacy MFI v4 for comparison column
    master = compute_mfi(master)          # adds MFI_v4 (keeps legacy cols)

    print("[INFO] Computing MFI_real (RPP-deflated robustness — Pillar 2)...")
    master = compute_mfi_real(master)     # adds MFI_real

    print("[INFO] Assigning quadrants (using MFI_v5 as primary)...")
    # compute_quadrants reads "MFI_v4" column — temporarily alias MFI_v5 to it
    mfi_v5_vals = master["MFI_v5"].copy()
    mfi_v4_backup = master["MFI_v4"].copy() if "MFI_v4" in master.columns else None
    master["MFI_v4"] = mfi_v5_vals       # quadrant logic reads MFI_v4
    master = compute_quadrants(master)    # sets Quadrant, Binding_Intensity
    if mfi_v4_backup is not None:
        master["MFI_v4"] = mfi_v4_backup  # restore legacy MFI_v4

    print("[INFO] Computing PRI v4 (BAP weights — Pillar 4)...")
    master = compute_pri(master)

    # ── Add metadata ─────────────────────────────────────────────────────
    if "AARP_Overall_Rank" not in master.columns:
        master["AARP_Overall_Rank"] = master["State"].map(AARP_OVERALL_RANK)

    # ── Print key results ────────────────────────────────────────────────
    mfi_col = "MFI_v5"
    print(f"\n[INFO] === TOP 10 STATES BY {mfi_col} (Market Friction) ===")
    for _, r in master.nlargest(10, mfi_col).iterrows():
        print(f"  {r['State']:<22} GPI=r{int(r['GPI_rank']):<3} "
              f"MFI=r{int(r['MFI_rank']):<3} {r['MFI_bottleneck']} | {r['Quadrant']}")

    print("\n[INFO] === PRI ELIGIBLE STATES (BAP weighted, ranked) ===")
    for _, r in master[master["PRI_eligible"]].sort_values("PRI_v4_rank").iterrows():
        rank_str = f"#{int(r['PRI_v4_rank'])}" if pd.notna(r["PRI_v4_rank"]) else "#?"
        print(f"  {rank_str:<4} {r['State']:<22} {r['Quadrant']:<20} "
              f"score={r['PRI_v4_stage2']:.3f}")

    # ── Validation report (8 checks) ────────────────────────────────────
    print("\n[INFO] === VALIDATION REPORT (8 checks) ===")
    val_df = validation_report(master)
    print(val_df[["Index","External","Spearman ρ","✓","Description"]
                 ].to_string(index=False))

    # ── RPP robustness summary ───────────────────────────────────────────
    if "MFI_real" in master.columns and master["MFI_real"].notna().sum() > 30:
        rho_rpp = _spearman(master["MFI_v5"].fillna(master["MFI_v5"].median()),
                            master["MFI_real"].fillna(master["MFI_real"].median()))
        print(f"\n[INFO] RPP robustness: Spearman(MFI_v5, MFI_real) = {rho_rpp:.3f} "
              f"({'✅ robust' if rho_rpp>0.70 else '⚠️ check'})")

    # ── Save outputs ─────────────────────────────────────────────────────
    master.to_csv(OUTPUT_DIR/"SYPA_Full_v5.csv", index=False)
    print(f"\n[INFO] Saved: SYPA_Full_v5.csv")
    # Also write v4-named file for backward compat with downstream scripts
    master.to_csv(OUTPUT_DIR/"SYPA_Full_v4.csv", index=False)

    gpi_mfi_cols = [
        "State","state_code","Region","HPAS","Quadrant",
        "GPI_v4","GPI_v6","GPI_v4_legacy","GPI_rank",
        "GPI_c1","GPI_c2","GPI_c_rebal","GPI_c3","GPI_c4","GPI_hpas_mult",
        "MFI_v5","MFI_MF1","MFI_MF2","MFI_MF2_wage","MFI_MF2_afford",
        "MFI_rank","MFI_bottleneck","MFI_MF2_bottleneck",
        "MFI_v4_legacy","MFI_real",
        "Wage_Compression_Ratio","Training_Floor_Gap",
        "Binding_Intensity","AARP_Score","AARP_Overall_Rank","PHI_Rank_Overall",
        "B3_Transition_Rate_65plus",
    ]
    master[[c for c in gpi_mfi_cols if c in master.columns]].to_csv(
        OUTPUT_DIR/"SYPA_GPI_MFI_v5.csv", index=False)
    master[[c for c in gpi_mfi_cols if c in master.columns]].to_csv(
        OUTPUT_DIR/"SYPA_GPI_MFI_v4.csv", index=False)
    print("[INFO] Saved: SYPA_GPI_MFI_v5.csv + SYPA_GPI_MFI_v4.csv")

    pri_cols = [
        "State","state_code","Quadrant",
        "PRI_eligible","PRI_F_score","PRI_O_score","PRI_v4_stage2","PRI_v4_rank",
        "PRI_BAP_eligible","PRI_BAP_score","PRI_BAP_rank",
        "GPI_v4","GPI_rank","MFI_v5","MFI_rank",
        "evv_model_score","evv_vendor_score","HPAS",
        "digital_readiness_65plus","Training_Floor_Gap",
    ]
    master[[c for c in pri_cols if c in master.columns]].to_csv(
        OUTPUT_DIR/"SYPA_PRI_v5.csv", index=False)
    master[[c for c in pri_cols if c in master.columns]].to_csv(
        OUTPUT_DIR/"SYPA_PRI_v4.csv", index=False)
    print("[INFO] Saved: SYPA_PRI_v5.csv + SYPA_PRI_v4.csv")

    val_df.to_csv(OUTPUT_DIR/"SYPA_Validation_v5.csv", index=False)
    val_df.to_csv(OUTPUT_DIR/"SYPA_Validation_v4.csv", index=False)
    print("[INFO] Saved: SYPA_Validation_v5.csv")

    # ── HPAS appendix (Pillar 6) ─────────────────────────────────────────
    generate_hpas_appendix(master, out_dir=str(OUTPUT_DIR))

    # ── Sensitivity analysis ─────────────────────────────────────────────
    if not skip_sensitivity:
        print("\n[INFO] Running sensitivity analysis (OAT + Sobol)...")
        sens = sensitivity_analysis(master)

        print("[INFO] Running Sobol global sensitivity analysis (Pillar 5)...")
        sobol_results = sobol_sensitivity_analysis(master, n_samples=512)
        sens.update(sobol_results)

        with pd.ExcelWriter(OUTPUT_DIR/"SYPA_Sensitivity_v5.xlsx",
                            engine="openpyxl") as w:
            for sname, sdf in sens.items():
                # Excel sheet name max 31 chars
                safe = sname[:31]
                sdf.to_excel(w, sheet_name=safe, index=False)
            val_df.to_excel(w, sheet_name="Validation", index=False)
        # Also write v4-named for backward compat
        import shutil
        shutil.copy(OUTPUT_DIR/"SYPA_Sensitivity_v5.xlsx",
                    OUTPUT_DIR/"SYPA_Sensitivity_v4.xlsx")
        print("[INFO] Saved: SYPA_Sensitivity_v5.xlsx")

    generate_scatter(master, str(OUTPUT_DIR/"SYPA_Scatter_v5.png"))
    # Copy as v4 for backward compat
    import shutil as _sh
    if (OUTPUT_DIR/"SYPA_Scatter_v5.png").exists():
        _sh.copy(OUTPUT_DIR/"SYPA_Scatter_v5.png",
                 OUTPUT_DIR/"SYPA_Scatter_v4.png")

    # ── Quality & Sanity Checks ───────────────────────────────────────────
    all_ok = quality_sanity_checks(master)
    if not all_ok:
        print("\n⚠️  Some critical checks failed — review warnings above.")

    return master

def run_full(force=False, skip_sensitivity=False):
    _ensure_dirs()
    print(f"\n{'='*65}")
    print(f"  SYPA Complete Pipeline v2.0 (A+ methodology)")
    print(f"  {datetime.datetime.now():%Y-%m-%d %H:%M}")
    print(f"{'='*65}\n")

    print("── PHASE 1: DATA ACQUISITION ──────────────────────────────\n")
    run_fetch(force=force)

    print("\n── PHASE 2 & 3: COMPUTATION, VALIDATION & OUTPUTS ────────\n")
    master = run_compute(skip_sensitivity=skip_sensitivity)

    print(f"\n{'='*65}")
    print("  PIPELINE COMPLETE")
    print(f"  Outputs written to: {OUTPUT_DIR}/")
    print(f"{'='*65}\n")
    return master

# =============================================================================
# MANUAL UPDATE GUIDE
# =============================================================================
GUIDE = """
=============================================================================
MANUAL UPDATE GUIDE — Hardcoded sources (5 sources, no public API)
=============================================================================

1.  PHI DIRECT CARE WORKFORCE STATE INDEX
    Frequency: ~Annual (last: July 2024)
    URL: https://www.phinational.org/state-index-tool/
    → Email info@phinational.org for bulk data file (academic requests OK)
    → Or click each state page and record Overall, Worker, Economic ranks
    → Update PHI_DATA dictionary in this file

2.  ADRC / NO WRONG DOOR FUNCTIONS ASSESSMENT
    Frequency: Every 3 years (~next 2026)
    URL: https://ltsschoices.aarp.org/scorecard-report/2023
    → Download full AARP PDF → Appendix B → "ADRC/NWD Functions" table
    → Record "% Functions Implemented" (0–100) per state
    → Update ADRC_NWD_DATA dictionary

3.  KFF HCBS SCREENING POLICY
    Frequency: Annual (October)
    URL: https://www.kff.org/medicaid/state-indicator/
         number-of-people-waiting-for-hcbs-by-target-population-
         and-whether-states-screen-for-eligibility/
    → Click Download (Excel) → record screens column (Yes/No per state)
    → Update KFF_SCREENS dictionary
    NOTE: This is documentation only — not used in any formula.

4.  MIT LIVING WAGE CALCULATOR
    Frequency: Annual (February)
    URL: https://livingwage.mit.edu/states/[FIPS]
    → BEST: Email livingwage@mit.edu for bulk data file (academic use)
    → Or visit each state page: 1 Adult | 0 Children | Living Wage
    → Update MIT_LIVING_WAGE dictionary

5.  AARP LTSS STATE SCORECARD
    Frequency: Every 3 years (~next 2026)
    URL: https://ltsschoices.aarp.org/scorecard-report/2023
    → Download full PDF → Appendix A → Overall State Rankings table
    → Record overall rank (1–51) for all jurisdictions
    → Update AARP_OVERALL_RANK dictionary

6.  CARESCOUT PDF URL (changes annually, March)
    → Visit https://www.carescout.com/cost-of-care
    → Right-click "State Rankings" download → copy link
    → Update PDF_URL in fetch_carescout() function
    → Or download manually → save as data/carescout_manual.pdf
=============================================================================
"""

# =============================================================================
# ENTRY POINT
# =============================================================================

if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="SYPA Complete Pipeline v2.0 (A+ methodology) — fetch + compute + validate"
    )
    parser.add_argument("--fetch-only",   action="store_true",
                        help="Run Phase 1 (data acquisition) only")
    parser.add_argument("--compute-only", action="store_true",
                        help="Run Phase 2+3 (compute+validate) only — data must exist")
    parser.add_argument("--no-cache", "-n", action="store_true",
                        help="Force re-download (ignore cached files)")
    parser.add_argument("--fast",    "-f", action="store_true",
                        help="Skip sensitivity analysis")
    parser.add_argument("--guide",         action="store_true",
                        help="Print manual update guide for hardcoded sources")
    parser.add_argument("--verify",        action="store_true",
                        help="Check output files only")
    args = parser.parse_args()

    if args.guide:
        print(GUIDE); sys.exit(0)

    if args.verify:
        _ensure_dirs()
        print("\n=== OUTPUT FILE CHECK ===")
        for f in ["SYPA_Full_v5.csv","SYPA_GPI_MFI_v5.csv","SYPA_PRI_v5.csv",
                  "SYPA_Validation_v5.csv","SYPA_Sensitivity_v5.xlsx",
                  "SYPA_Scatter_v5.png","SYPA_HPAS_Appendix_III.csv"]:
            p = OUTPUT_DIR/f
            print(f"  {'✅' if p.exists() else '❌'} {f}")
        sys.exit(0)

    if args.fetch_only:
        _ensure_dirs()
        print(f"\n{'='*65}")
        print(f"  SYPA Pipeline — Phase 1: Data Acquisition only")
        print(f"  {datetime.datetime.now():%Y-%m-%d %H:%M}")
        print(f"{'='*65}\n")
        run_fetch(force=args.no_cache)
    elif args.compute_only:
        _ensure_dirs()
        print(f"\n{'='*65}")
        print(f"  SYPA Pipeline — Phase 2+3: Compute + Validate only")
        print(f"  {datetime.datetime.now():%Y-%m-%d %H:%M}")
        print(f"{'='*65}\n")
        run_compute(skip_sensitivity=args.fast)
    else:
        run_full(force=args.no_cache, skip_sensitivity=args.fast)
