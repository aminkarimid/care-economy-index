#!/usr/bin/env python3
"""
SYPA — Care Economy Dual-Index Engine (Comprehensive + Benchmarks + PRI v3.2)
============================================================================

This script builds TWO conceptual indices for US states (+ DC):

  1) Governance Pressure Index (GPI)  -> "policy / system pressure"
  2) Market Friction Index (MFI)      -> "market / labor wedge"

PLUS (add-on):
  3) Pilot Readiness Index (PRI v3.2) -> "where X3P can realistically pilot first"

Key design choice ("bifurcation"):
---------------------------------
GPI reflects *governance levers* (system structure + access management).
MFI reflects *market constraints* (cost burden, wage competitiveness, labor scarcity).

Waitlist magnitude is kept OUTSIDE the indices (incomparable reporting),
but retained as diagnostics AND used inside PRI as a "demand transparency" signal.

Main outcomes (canonical):
-------------------------
- GPI_weighted : weighted arithmetic mean of governance z-components
- MFI_mpi      : non-compensatory "Mazziotta–Pareto style" penalty
                 MFI_mpi = mean(z_components) + LAMBDA * std(z_components)

PRI v3.2 outputs (add-on):
-------------------------
- PRI_commercial_v3, PRI_policy_v3 + ranks
- Produces:
    * SYPA_PRI_v3_ranking.csv
    * SYPA_PRI_v3_highBI_commercial.csv
    * SYPA_PRI_v3_highBI_policy.csv
- Also includes EVV regulatory map auto-generated to outputs/evv_regulatory_map.csv
  (unless you provide your own).

Benchmarks / validation:
------------------------
- AARP overall score (higher = better) -> expect NEG correlation with GPI variants
- AARP domain ranks (lower = better)   -> expect POS correlation with relevant indices
- PHI workforce ranks (lower = better) -> expect POS correlation with MFI variants

Inputs (expected in /data by default):
--------------------------------------
Required:
  - GPI_MFI.xlsx
  - B1_LTSSUsrRebalMeasr_2023.xlsx
  - B2_LTSSExpRebalMeasr_2023.xlsx

Optional (if present, used automatically):
  - ADRC NWD Functions.csv
  - SARPP.xlsx
  - PHI.csv
  - Affordability and Access .xlsx
  - Choice of Setting and Provider .xlsx
  - macro.xlsx (unemployment + other macro controls)
  - outputs/evv_regulatory_map.csv (if missing, the script will auto-generate one)

Outputs (written to /outputs):
------------------------------
  - SYPA_Final_Indices_GPI_MFI.csv  (includes PRI columns too)
  - SYPA_Correlation_Audit.xlsx
  - SYPA_Diagnostic_Scatter.png
  - SYPA_Diagnostic_Scatter.html
  - SYPA_Diagnostic_Scatter_65plus.html (if Pop_65plus_Pct exists)
  - SYPA_Geographic_Map.html
  - SYPA_PRI_v3_ranking.csv
  - SYPA_PRI_v3_highBI_commercial.csv
  - SYPA_PRI_v3_highBI_policy.csv
  - outputs/evv_regulatory_map.csv (auto-generated if missing or if forced)

Command-line flags:
-------------------
  - --skip-sensitivity / -x   Build primary outputs only (skip robustness workbook).
  - --sensitivity / -s        Run robustness workbook only (legacy behavior).
  - --skip-pri                Skip PRI outputs.
  - --build-evv-map           Force rebuild of outputs/evv_regulatory_map.csv (overwrites).

Implementation notes:
---------------------
- No SciPy dependency. Spearman correlation is computed as Pearson correlation of ranks.
- GPI/MFI: "higher = worse" (more pressure / more friction).
- PRI: "higher = better" (more pilot-ready) with negative weights for “drag” variables.
- Missing numeric inputs are imputed by *regional median* (4 Census regions), then
  national median as fallback. We preserve missingness flags.
"""

from __future__ import annotations

import os
import sys
import re
from typing import Dict, Tuple, Optional, List, Any

import numpy as np
import pandas as pd
import matplotlib.pyplot as plt
import json
import urllib.request
import urllib.parse

# Optional, but nice-to-have
try:
    import seaborn as sns  # type: ignore
except Exception:
    sns = None  # fallback later

try:
    import plotly.express as px  # type: ignore
except Exception:
    px = None

# =============================================================================
# CONFIG
# =============================================================================

# ---- Required inputs
INPUT_FILE = "GPI_MFI.xlsx"
LTSS_USER_FILE = "B1_LTSSUsrRebalMeasr_2023.xlsx"
LTSS_EXP_FILE  = "B2_LTSSExpRebalMeasr_2023.xlsx"

# ---- Optional diagnostics / validation files
ADRC_FILE  = "ADRC NWD Functions.csv"                 # Access Velocity proxy (optional)
SARPP_FILE = "SARPP.xlsx"                             # BEA SARPP export (optional; diagnostics only)
PHI_FILE   = "PHI.csv"                                # Workforce ranks (optional)

AARP_AFFORD_FILE = "Affordability and Access .xlsx"   # AARP domain rank (optional)
AARP_CHOICE_FILE = "Choice of Setting and Provider .xlsx"  # AARP domain rank (optional)

# ---- Optional macro controls (scenario/partial-corr analysis)
MACRO_FILE = "macro.xlsx"

# ---- IMPORTANT: macro-adjusted outputs are sensitivity checks (NOT canonical)
INCLUDE_MACRO_ADJUSTED_IN_HOVER = False
INCLUDE_MACRO_ADJUSTED_IN_PRINT_AUDIT = True

# Search paths for inputs
# Prefer /data. Still allow /outputs (for EVV map or prior outputs). Fall back to current dir.
INPUT_SEARCH_PATHS: Tuple[str, ...] = ("data", "outputs", "")

# ---- Sheets in GPI_MFI.xlsx (compiled workbook)
SHEET_MAP = {
    "STATE_LIST": "State_List",
    "POP": "Raw_UVA_2030",
    "WAIT": "Raw_KFF_Waitlist",
    "COST": "Raw_CareCost",
    "INCOME": "Raw_ACS_Income65",
    "WAGE": "Raw_BLS_Wage",
    "LIVING": "Raw_LivingWage",
    "EMP": "Raw_Employment",
    "AARP": "Raw_AARP_HCBS",  # overall score for validation
}

# ---- LTSS rebalancing sheets (AARP appendices format)
LTSS_USER_SHEET = "B.1.1 BalanceByAge"
LTSS_EXP_SHEET  = "B.2.1 BalanceByAge"

# ---- Governance weights (canonical GPI_weighted)
GPI_WEIGHTS = {
    "Pressure_Users": 0.35,
    "Pressure_Exp": 0.35,
    "Screening": 0.15,
    "Access_Velocity": 0.15,
}

# ---- Market weights (used for MFI_mean, MFI_mpi, etc.)
MFI_WEIGHTS = {"Cost_Burden": 1/3, "Wage_Gap": 1/3, "Labor_Scarcity": 1/3}

# ---- MPI-style non-compensatory penalty coefficient
LAMBDA = 1.0

# ---- Standardization
Z_CAP = 2.5    # winsorization cap in SD units (robust to outliers)
Z_DDOF = 1     # ddof for z-score SD (sample SD)

# ---- Bounded-share transform
USE_LOGIT_FOR_REBAL = True
EPS = 1e-6

# ---- MFI assumptions (paid care "annualized")
HOURS_PER_WEEK = 30
WEEKS_PER_YEAR = 52

# ---- Quadrant split for scatter diagnostics (canonical axes)
QUADRANT_SPLIT = "median"  # {"median","mean","zero"}

# ---- Output directory
OUTPUT_DIR = "outputs"
SENSITIVITY_OUTPUT_DIR = OUTPUT_DIR
SENSITIVITY_XLSX_NAME = "SYPA_Sensitivity_Tests.xlsx"
CORRELATION_XLSX_NAME = "SYPA_Correlation_Audit.xlsx"

# =============================================================================
# REGION MAP (for regional-median imputation)
# =============================================================================

_STATE_TO_REGION = {
    # Northeast
    "Connecticut":"Northeast","Maine":"Northeast","Massachusetts":"Northeast","New Hampshire":"Northeast",
    "Rhode Island":"Northeast","Vermont":"Northeast","New Jersey":"Northeast","New York":"Northeast",
    "Pennsylvania":"Northeast",
    # Midwest
    "Illinois":"Midwest","Indiana":"Midwest","Michigan":"Midwest","Ohio":"Midwest","Wisconsin":"Midwest",
    "Iowa":"Midwest","Kansas":"Midwest","Minnesota":"Midwest","Missouri":"Midwest","Nebraska":"Midwest",
    "North Dakota":"Midwest","South Dakota":"Midwest",
    # South
    "Delaware":"South","District of Columbia":"South","Florida":"South","Georgia":"South","Maryland":"South",
    "North Carolina":"South","South Carolina":"South","Virginia":"South","West Virginia":"South",
    "Alabama":"South","Kentucky":"South","Mississippi":"South","Tennessee":"South",
    "Arkansas":"South","Louisiana":"South","Oklahoma":"South","Texas":"South",
    # West
    "Arizona":"West","Colorado":"West","Idaho":"West","Montana":"West","Nevada":"West","New Mexico":"West",
    "Utah":"West","Wyoming":"West","Alaska":"West","California":"West","Hawaii":"West","Oregon":"West",
    "Washington":"West",
}

# =============================================================================
# HELPERS
# =============================================================================

CENSUS_ACS_YEAR = 2023
CENSUS_ACS_DATASET = "acs/acs1/subject"   # for states, acs1 is fine
CENSUS_API_KEY = os.getenv("CENSUS_API_KEY", "")  # optional but recommended

ACS_S2801_SMARTPHONE_PCT = "S2801_C02_005E"  # % households with smartphone
ACS_S2801_BROADBAND_PCT  = "S2801_C02_017E"  # % households with broadband

def _die(msg: str, code: int = 1) -> None:
    print(f"[FATAL] {msg}")
    sys.exit(code)

def _resolve_input_path(filename: str) -> str:
    """
    Resolve an input filename by searching common data directories.

    Important behavior:
    - If `filename` already contains a directory component (e.g. "outputs/foo.csv"),
      we do NOT try to prefix search paths (to avoid outputs/outputs/foo.csv).
    """
    if not filename:
        return filename

    # Already a path (abs or relative with a folder)
    if os.path.isabs(filename) or os.path.dirname(filename):
        return filename

    # Exists in CWD
    if os.path.exists(filename):
        return filename

    # Search common dirs
    for folder in INPUT_SEARCH_PATHS:
        if folder is None:
            continue
        folder = str(folder)
        if folder.strip() == "":
            candidate = filename
        else:
            candidate = os.path.join(folder, filename)
        if os.path.exists(candidate):
            return candidate

    return filename

def _check_required_files() -> None:
    required = (INPUT_FILE, LTSS_USER_FILE, LTSS_EXP_FILE)
    missing = []
    for f in required:
        resolved = _resolve_input_path(f)
        if not os.path.exists(resolved):
            missing.append(f if resolved == f else f"{f} (looked for {resolved})")
    if missing:
        _die("Missing required file(s): " + ", ".join(missing))

def _standardize_state(s) -> str:
    """Normalize state names for merges."""
    if pd.isna(s):
        return np.nan
    s = str(s).strip()
    s = s.title()
    s = s.replace("District Of Columbia", "District of Columbia")
    s = s.replace("Dist. Of Columbia", "District of Columbia")
    return s

def _validate_weights(w: Dict[str, float], name: str) -> None:
    s = float(sum(w.values()))
    if not np.isclose(s, 1.0, atol=1e-6):
        _die(f"{name} weights must sum to 1.0 (got {s}).")

def _winsorized_z(series: pd.Series, cap: Optional[float] = None, invert: bool = False, ddof: Optional[int] = None) -> pd.Series:
    """Z-score with robust clipping (winsorization-style) and optional sign inversion."""
    if cap is None:
        cap = Z_CAP
    if ddof is None:
        ddof = Z_DDOF

    s = pd.to_numeric(series, errors="coerce")
    mu = s.mean()
    sigma = s.std(ddof=int(ddof))
    if pd.isna(sigma) or sigma == 0:
        z = s * 0
    else:
        z = (s - mu) / sigma
    if invert:
        z = -z
    return z.clip(-float(cap), float(cap))

def _safe_div(numer, denom, eps: float = 1e-9) -> pd.Series:
    numer = pd.to_numeric(numer, errors="coerce")
    denom = pd.to_numeric(denom, errors="coerce")
    return (numer + eps) / (denom + eps)

def _logit(p: pd.Series, eps: Optional[float] = None) -> pd.Series:
    """Logit transform for proportions; keeps values finite via clipping."""
    if eps is None:
        eps = EPS
    p = pd.to_numeric(p, errors="coerce").clip(float(eps), 1 - float(eps))
    return np.log(p / (1 - p))

def _spearman_corr(a: pd.Series, b: pd.Series) -> float:
    """Spearman without SciPy: Pearson correlation of ranks (average ranks for ties)."""
    a = pd.to_numeric(a, errors="coerce")
    b = pd.to_numeric(b, errors="coerce")
    return a.rank(method="average").corr(b.rank(method="average"))

def _geometric_mean_shifted_z(z_df: pd.DataFrame, eps: Optional[float] = None) -> pd.Series:
    """Geometric-mean aggregation for z-scores (diagnostic)."""
    if eps is None:
        eps = EPS

    z_pos = z_df.copy()
    for c in z_pos.columns:
        mn = z_pos[c].min(skipna=True)
        if pd.isna(mn):
            mn = 0.0
        z_pos[c] = (z_pos[c] - float(mn) + float(eps)).clip(lower=float(eps))
    geom = np.exp(np.log(z_pos).mean(axis=1))
    return _winsorized_z(np.log(pd.Series(geom, index=z_df.index)))

def _load_excel_sheet_guess_state(excel_path: str, sheet_name: str) -> pd.DataFrame:
    """Read an Excel sheet and ensure a 'State' column exists (guess if needed)."""
    path = _resolve_input_path(excel_path)
    df = pd.read_excel(path, sheet_name=sheet_name)
    if "State" not in df.columns:
        cand = [c for c in df.columns if "state" in str(c).lower() and "code" not in str(c).lower()]
        if cand:
            df = df.rename(columns={cand[0]: "State"})
    if "State" not in df.columns:
        _die(f"Could not find a State column in {path} / {sheet_name}")
    df["State"] = df["State"].apply(_standardize_state)
    return df

def _load_from_workbook(sheet: str, wanted: Dict[str, str]) -> pd.DataFrame:
    """
    Load a sheet from INPUT_FILE and rename selected columns.
    `wanted` is {raw_col_name: new_col_name}.
    Returns at minimum: State + requested columns (if found).
    """
    df = _load_excel_sheet_guess_state(INPUT_FILE, sheet)
    ren = {}
    keep = ["State"]
    for raw_col, new_col in wanted.items():
        if raw_col in df.columns:
            ren[raw_col] = new_col
            keep.append(new_col)
    df = df.rename(columns=ren)
    keep = list(dict.fromkeys(keep))
    return df[keep].copy()

def _find_header_row(df: pd.DataFrame, needle: str = "State", max_scan: int = 40) -> int:
    """Find the row index whose first cell equals 'State' (AARP appendix style)."""
    for i in range(min(max_scan, len(df))):
        v = df.iloc[i, 0]
        if isinstance(v, str) and v.strip().lower() == needle.lower():
            return i
    return -1

def _parse_aarp_style_table(excel_path: str, sheet_name: str) -> pd.DataFrame:
    """
    Many AARP/CMS appendix exports include a title row and then a header row.
    We detect the header row where col0 == 'State' and use it as column names.
    """
    path = _resolve_input_path(excel_path)
    raw = pd.read_excel(path, sheet_name=sheet_name, header=None)
    hdr = _find_header_row(raw, needle="State")
    if hdr < 0:
        df = pd.read_excel(path, sheet_name=sheet_name)
        if "State" not in df.columns:
            df = df.rename(columns={df.columns[0]: "State"})
    else:
        df = raw.iloc[hdr+1:].copy()
        df.columns = raw.iloc[hdr].tolist()
        df = df.rename(columns={df.columns[0]: "State"})
    df["State"] = df["State"].apply(_standardize_state)
    df = df[df["State"].notna()]
    df = df[df["State"].str.lower() != "national"]
    return df.reset_index(drop=True)

def _pick_hcbs_percent_cols(df: pd.DataFrame) -> Tuple[Optional[str], Optional[str]]:
    """
    Find "% HCBS" columns:
      - overall % HCBS (often named exactly "% HCBS")
      - 65+ % HCBS (contains '% HCBS' and '65' + 'older/65+')
    """
    cols = [c for c in df.columns if isinstance(c, str)]
    overall = None
    for c in cols:
        if c.strip() == "% HCBS":
            overall = c
            break
    if overall is None:
        hcbs_cols = [c for c in cols if "% hcbs" in c.lower()]
        if hcbs_cols:
            overall = sorted(hcbs_cols, key=len)[0]

    age65 = None
    for c in cols:
        cl = c.lower()
        if "% hcbs" in cl and ("65" in cl) and ("older" in cl or "65+" in cl or "and older" in cl):
            age65 = c
            break

    return overall, age65

def _parse_percent_string(x) -> float:
    """Parse '92%' or '92.0' into float(92.0)."""
    if pd.isna(x):
        return np.nan
    if isinstance(x, (int, float, np.integer, np.floating)):
        return float(x)
    s = str(x).strip().replace(",", "")
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*%?$", s)
    return float(m.group(1)) if m else np.nan

def _load_adrc_access_velocity(path: str) -> pd.DataFrame:
    """
    ADRC/NWD Functions file:
    - expected columns: State + an "Overall Performance" column (often as percent).
    - output: State, Access_Velocity_Share in [0,1]
    """
    resolved = _resolve_input_path(path)
    df = pd.read_csv(resolved)
    if "State" not in df.columns:
        df = df.rename(columns={df.columns[0]: "State"})
    df["State"] = df["State"].apply(_standardize_state)

    perf_col = None
    for c in df.columns:
        if isinstance(c, str) and "overall" in c.lower() and "performance" in c.lower():
            perf_col = c
            break
    if perf_col is None:
        _die(f"ADRC file found but could not identify an overall performance column: {resolved}")

    out = df[["State"]].copy()
    out["Access_Velocity_Share"] = df[perf_col].apply(_parse_percent_string) / 100.0
    out["Access_Velocity_Share"] = out["Access_Velocity_Share"].clip(0, 1)
    return out

def _load_sarpp_rpp_all_items(path: str) -> pd.DataFrame:
    """
    Parse SARPP.xlsx exported from BEA iTable and extract LineCode==5 ('RPPs: All items').
    Uses the latest available year column (e.g., 2023).
    """
    resolved = _resolve_input_path(path)
    raw = pd.read_excel(resolved, sheet_name=0, header=None)

    hdr = None
    for i in range(min(60, len(raw))):
        v = raw.iloc[i, 0]
        if isinstance(v, str) and v.strip().lower() == "geofips":
            hdr = i
            break
    df = pd.read_excel(resolved, sheet_name=0, header=hdr) if hdr is not None else pd.read_excel(resolved, sheet_name=0)

    if not {"GeoName", "LineCode"}.issubset(set(df.columns)):
        _die("SARPP.xlsx is missing expected columns GeoName/LineCode. Re-export SARPP with these fields.")

    year_cols = []
    for c in df.columns:
        if isinstance(c, (int, np.integer)):
            year_cols.append(int(c))
        elif isinstance(c, str) and c.isdigit():
            year_cols.append(int(c))
    if not year_cols:
        _die("SARPP.xlsx parsed but no year columns detected (e.g., 2023).")

    latest_year = max(year_cols)
    year_label = latest_year if latest_year in df.columns else str(latest_year)

    keep = df.loc[pd.to_numeric(df["LineCode"], errors="coerce") == 5, ["GeoName", year_label]].copy()
    keep = keep.rename(columns={"GeoName": "State", year_label: f"RPP_AllItems_{latest_year}"})
    keep["State"] = keep["State"].apply(_standardize_state)
    keep[f"RPP_AllItems_{latest_year}"] = pd.to_numeric(keep[f"RPP_AllItems_{latest_year}"], errors="coerce")
    keep = keep[keep["State"].notna()]
    keep = keep[keep["State"].str.lower() != "united states"]
    return keep.reset_index(drop=True)

def _load_aarp_domain_rank(path: str, prefix: str) -> pd.DataFrame:
    """
    Parse the AARP domain spreadsheets (51 rows).
    Expected columns include:
      - StateSort descending (state)
      - Rank
      - Tier (optional)
    """
    resolved = _resolve_input_path(path)
    df = pd.read_excel(resolved)
    st_col = None
    for c in df.columns:
        if isinstance(c, str) and "state" in c.lower():
            st_col = c
            break
    if st_col is None:
        st_col = df.columns[0]
    df = df.rename(columns={st_col: "State"})
    df["State"] = df["State"].apply(_standardize_state)

    out = df[["State"]].copy()
    if "Rank" in df.columns:
        out[f"{prefix}_Rank"] = pd.to_numeric(df["Rank"], errors="coerce")
    for c in df.columns:
        if isinstance(c, str) and c.lower().strip() == "tier":
            out[f"{prefix}_Tier"] = pd.to_numeric(df[c], errors="coerce")
            break
    return out

def _load_phi(path: str) -> pd.DataFrame:
    """Parse PHI.csv."""
    resolved = _resolve_input_path(path)
    df = pd.read_csv(resolved)
    st_col = None
    for c in df.columns:
        if isinstance(c, str) and c.lower().strip() == "state":
            st_col = c
            break
    if st_col is None:
        st_col = df.columns[1]
    df = df.rename(columns={st_col: "State"})
    df["State"] = df["State"].apply(_standardize_state)

    out = df[["State"]].copy()
    if "Rank" in df.columns:
        out["PHI_Rank_Overall"] = pd.to_numeric(df["Rank"], errors="coerce")

    for c in df.columns:
        cl = str(c).lower()
        if "worker supportive" in cl:
            out["PHI_Rank_WorkerSupport"] = pd.to_numeric(df[c], errors="coerce")
        if "economic" in cl and "index" in cl:
            out["PHI_Rank_Economic"] = pd.to_numeric(df[c], errors="coerce")
        if "wages" in cl and "benefits" in cl:
            out["PHI_Rank_WagesBenefits"] = pd.to_numeric(df[c], errors="coerce")

    return out

def _add_state_codes(master: pd.DataFrame) -> pd.DataFrame:
    """Add a two-letter state code for mapping."""
    if "state_code" in master.columns and master["state_code"].notna().all():
        master["State_Code"] = master["state_code"]
        return master

    us_state_to_abbrev = {
        "Alabama":"AL","Alaska":"AK","Arizona":"AZ","Arkansas":"AR","California":"CA",
        "Colorado":"CO","Connecticut":"CT","Delaware":"DE","Florida":"FL","Georgia":"GA",
        "Hawaii":"HI","Idaho":"ID","Illinois":"IL","Indiana":"IN","Iowa":"IA",
        "Kansas":"KS","Kentucky":"KY","Louisiana":"LA","Maine":"ME","Maryland":"MD",
        "Massachusetts":"MA","Michigan":"MI","Minnesota":"MN","Mississippi":"MS","Missouri":"MO",
        "Montana":"MT","Nebraska":"NE","Nevada":"NV","New Hampshire":"NH","New Jersey":"NJ",
        "New Mexico":"NM","New York":"NY","North Carolina":"NC","North Dakota":"ND","Ohio":"OH",
        "Oklahoma":"OK","Oregon":"OR","Pennsylvania":"PA","Rhode Island":"RI","South Carolina":"SC",
        "South Dakota":"SD","Tennessee":"TN","Texas":"TX","Utah":"UT","Vermont":"VT",
        "Virginia":"VA","Washington":"WA","West Virginia":"WV","Wisconsin":"WI","Wyoming":"WY",
        "District of Columbia":"DC"
    }
    master["State_Code"] = master["State"].map(us_state_to_abbrev)
    return master

def _add_region(master: pd.DataFrame) -> pd.DataFrame:
    master["Region"] = master["State"].map(_STATE_TO_REGION).fillna("Unknown")
    return master

def _impute_regional_median(master: pd.DataFrame, col: str, flag_suffix: str = "_Missing") -> None:
    """
    Impute missing values using:
      1) Census-region median, then
      2) national median
    and create/overwrite a missingness flag.
    """
    master[f"{col}{flag_suffix}"] = master[col].isna().astype(int)
    if master[col].isna().any():
        reg_meds = master.groupby("Region")[col].median()
        nat_med = master[col].median()

        def fill_row(r):
            if pd.notna(r[col]):
                return r[col]
            reg = r["Region"]
            v = reg_meds.get(reg, np.nan)
            return v if pd.notna(v) else nat_med

        master[col] = master.apply(fill_row, axis=1)

def _load_macro_controls(path: str) -> pd.DataFrame:
    """
    Load optional macro controls from macro.xlsx.
    Expected:
    - State column (or first column treated as State)
    - Unemployment rate column (various names accepted)
    """
    resolved = _resolve_input_path(path)
    xls = pd.read_excel(resolved, sheet_name=None)

    sheet_name = None
    for k in xls.keys():
        if isinstance(k, str) and "unemp" in k.lower():
            sheet_name = k
            break
    if sheet_name is None:
        sheet_name = list(xls.keys())[0]

    df = xls[sheet_name].copy()

    st_col = None
    for c in df.columns:
        if isinstance(c, str) and c.strip().lower() == "state":
            st_col = c
            break
    if st_col is None:
        for c in df.columns:
            if isinstance(c, str) and "state" in c.lower():
                st_col = c
                break
    if st_col is None:
        st_col = df.columns[0]

    df = df.rename(columns={st_col: "State"})
    df["State"] = df["State"].apply(_standardize_state)

    rate_col = None
    for c in df.columns:
        if not isinstance(c, str):
            continue
        cl = c.lower()
        if "unemployment" in cl and "rate" in cl:
            rate_col = c
            break
    if rate_col is None:
        for c in df.columns:
            if not isinstance(c, str):
                continue
            cl = c.lower()
            if "unemp" in cl and "rate" in cl:
                rate_col = c
                break
    if rate_col is None:
        for c in df.columns:
            if not isinstance(c, str):
                continue
            if c.strip().lower() == "rate":
                rate_col = c
                break

    if rate_col is None:
        exclude = {"state", "rank"}
        candidates = []
        for c in df.columns:
            if c == "State":
                continue
            if isinstance(c, str) and c.strip().lower() in exclude:
                continue
            s = df[c]
            s_num = s.astype(str).str.replace("%", "", regex=False)
            s_num = pd.to_numeric(s_num, errors="coerce")
            numeric_share = float(s_num.notna().mean()) if len(s_num) else 0.0

            name_bonus = 0
            if isinstance(c, str):
                cl = c.lower()
                if "rate" in cl:
                    name_bonus += 2
                if "unemp" in cl or "unemployment" in cl:
                    name_bonus += 2
            score = name_bonus + numeric_share
            candidates.append((score, c))

        if candidates:
            candidates.sort(reverse=True, key=lambda t: t[0])
            best_score, best_col = candidates[0]
            if best_score > 0.2:
                rate_col = best_col

    rank_col = None
    for c in df.columns:
        if isinstance(c, str) and c.strip().lower() == "rank":
            rank_col = c
            break

    out = df[["State"]].copy()
    if rate_col is not None:
        cleaned = df[rate_col].astype(str).str.replace("%", "", regex=False)
        out["Unemployment_Rate"] = pd.to_numeric(cleaned, errors="coerce")
    else:
        out["Unemployment_Rate"] = np.nan

    if rank_col is not None:
        out["Unemployment_Rank"] = pd.to_numeric(df[rank_col], errors="coerce")

    return out

def _linear_residual(df: pd.DataFrame, y_col: str, x_cols: List[str]) -> pd.Series:
    """
    Residualize y on controls X via OLS (no statsmodels dependency).
    Returns Series aligned to df.index with NaNs where sample missing required values.
    """
    if not x_cols:
        return pd.Series(np.nan, index=df.index)

    cols = [y_col] + x_cols
    sub = df[cols].copy()
    sub = sub.apply(pd.to_numeric, errors="coerce")
    ok = sub.notna().all(axis=1)

    if ok.sum() < max(8, len(x_cols) + 3):
        return pd.Series(np.nan, index=df.index)

    y = sub.loc[ok, y_col].to_numpy(dtype=float)
    X = sub.loc[ok, x_cols].to_numpy(dtype=float)
    X = np.column_stack([np.ones(len(X)), X])  # intercept

    beta, *_ = np.linalg.lstsq(X, y, rcond=None)
    y_hat = X @ beta
    resid = y - y_hat

    out = pd.Series(np.nan, index=df.index)
    out.loc[ok] = resid
    return out

# =============================================================================
# ACS S2801 digital readiness
# =============================================================================

def _load_acs_s2801_digital(year: int = CENSUS_ACS_YEAR,
                           dataset: str = CENSUS_ACS_DATASET,
                           api_key: str = CENSUS_API_KEY) -> pd.DataFrame:
    """
    Pull state-level smartphone and broadband percentages from ACS S2801 via Census API.
    Returns: State, smartphone_share, broadband_share (shares in [0,1])
    """
    base = f"https://api.census.gov/data/{year}/{dataset}"

    get_vars = ["NAME", ACS_S2801_SMARTPHONE_PCT, ACS_S2801_BROADBAND_PCT]
    params = {
        "get": ",".join(get_vars),
        "for": "state:*",
    }
    if api_key:
        params["key"] = api_key

    url = base + "?" + urllib.parse.urlencode(params)

    with urllib.request.urlopen(url) as resp:
        raw = resp.read().decode("utf-8")
        data = json.loads(raw)

    header = data[0]
    rows = data[1:]
    df = pd.DataFrame(rows, columns=header)

    df = df.rename(columns={"NAME": "State"})
    df["State"] = df["State"].apply(_standardize_state)

    df["smartphone_share"] = pd.to_numeric(df[ACS_S2801_SMARTPHONE_PCT], errors="coerce") / 100.0
    df["broadband_share"]  = pd.to_numeric(df[ACS_S2801_BROADBAND_PCT], errors="coerce") / 100.0

    df["smartphone_share"] = df["smartphone_share"].clip(0, 1)
    df["broadband_share"]  = df["broadband_share"].clip(0, 1)

    return df[["State", "smartphone_share", "broadband_share"]]

# =============================================================================
# PRI v3.2 (Pilot Readiness Index) — add-on module
# =============================================================================

EVV_MAP_FILE = os.path.join(OUTPUT_DIR, "evv_regulatory_map.csv")  # outputs/evv_regulatory_map.csv

def _zscore(series: pd.Series) -> pd.Series:
    s = pd.to_numeric(series, errors="coerce")
    mu = s.mean(skipna=True)
    sd = s.std(skipna=True, ddof=0)
    if sd == 0 or np.isnan(sd):
        return pd.Series(np.nan, index=series.index)
    return (s - mu) / sd

def _weighted_sum_ignore_missing(row: pd.Series, weights: Dict[str, float]) -> float:
    """
    Weighted mean over available components only.
    Uses ABS(weight) to normalize so negative weights don't cancel denominator.
    """
    num = 0.0
    den = 0.0
    for k, w in weights.items():
        x = row.get(k, np.nan)
        if pd.isna(x):
            continue
        num += w * x
        den += abs(w)
    return num / den if den > 0 else np.nan

def _coverage_ratio(row: pd.Series, weights: Dict[str, float]) -> float:
    """Share of absolute weight covered by non-missing components (0..1)."""
    denom = float(sum(abs(w) for w in weights.values()))
    if denom <= 0:
        return np.nan
    numer = 0.0
    for k, w in weights.items():
        if not pd.isna(row.get(k, np.nan)):
            numer += abs(w)
    return numer / denom

def _score_evv_model(x: str) -> float:
    x = (x or "").strip().lower()
    return {"open": 1.0, "hybrid": 0.6, "closed": 0.0, "unknown": np.nan}.get(x, np.nan)

def _score_vendor_portability(x: str) -> float:
    x = (x or "").strip().lower()
    return {"national": 1.0, "mixed": 0.6, "state_specific": 0.0, "unknown": np.nan}.get(x, np.nan)

# Backward-compatible alias for older references
_score_evv_vendor = _score_vendor_portability

def build_evv_regulatory_map(out_path: str) -> str:
    """
    Generates evv_regulatory_map.csv from a hard-coded table.
    Output columns: State, evv_model, evv_vendor_portability
    """
    rows = [
        ("Alabama","Open Model","HHAeXchange"),
        ("Alaska","Hybrid Model","Therap"),
        ("Arizona","Open Model","AHCCCS In-House (from 10/01/2025; Sandata until 09/30/2025)"),
        ("Arkansas","Open Model","AuthentiCare (PCS) / Sandata (HHCS) / HHAX or CareBridge (PASSE)"),
        ("California","Hybrid Model","CalEVV Aggregator (Sandata)"),
        ("Colorado","Hybrid Model","Sandata"),
        ("Connecticut","Hybrid Model","Sandata"),
        ("Delaware","Hybrid Model","Sandata"),
        ("District of Columbia","Hybrid Model","Sandata"),
        ("Florida","Hybrid Model","Netsmart Technologies"),
        ("Georgia","Open Model","Netsmart"),
        ("Hawaii","Open Model","Sandata"),
        ("Idaho","Provider Choice","Sandata"),
        ("Illinois","Hybrid Model","HHAeXchange"),
        ("Indiana","Open Model","Sandata"),
        ("Iowa","Managed Care Choice","CareBridge"),
        ("Kansas","Provider Choice","Fiserv"),
        ("Kentucky","Hybrid Model","Therap"),
        ("Louisiana","Open Model","LaSRS"),
        ("Maine","Open Model","Sandata"),
        ("Maryland","State Mandated System","In-Home Supports Assurance System (ISAS)"),
        ("Massachusetts","Hybrid Model","Sandata"),
        ("Michigan","Open Model","HHAeXchange"),
        ("Minnesota","Open Model","HHAeXchange"),
        ("Mississippi","Open Model","HHAeXchange"),
        ("Missouri","Open Model","Sandata"),
        ("Montana","Open Model","Sandata"),
        ("Nebraska","Open Model","Netsmart"),
        ("Nevada","Open Model","Sandata"),
        ("New Hampshire","Open Model","AuthentiCare"),
        ("New Jersey","Open Model","HHAeXchange"),
        ("New Mexico","State Mandated System","AuthentiCare"),
        ("New York","Provider Choice","New York State EVV Data Aggregator"),
        ("North Carolina","Hybrid Model","Sandata"),
        ("North Dakota","Open Model","Sandata"),
        ("Ohio","Open Model","Sandata"),
        ("Oklahoma","Hybrid Model","AuthentiCare / HHAeXchange"),
        ("Oregon","Provider Choice","eXPRS Mobile-EVV"),
        ("Pennsylvania","Open Model","Sandata / DHS Aggregator"),
        ("Rhode Island","Open Model","Sandata"),
        ("South Carolina","State Mandated System","Authenticare - implementation partially postponed"),
        ("South Dakota","Open Model","Therap"),
        ("Tennessee","Hybrid Model","(Sandata/PPL)"),
        ("Texas","Hybrid Model","TMHP EVV Aggregator"),
        ("Utah","Provider Choice","Utah Department of Health and Human Services"),
        ("Vermont","Open Model","Sandata"),
        ("Virginia","Provider Choice","N/A"),
        ("Washington","Provider Choice","ProviderOne"),
        ("West Virginia","Open/Hybrid Model","HHAeXchange"),
        ("Wisconsin","Open Model","Sandata"),
        ("Wyoming","Open Model","CareBridge"),
    ]
    df = pd.DataFrame(rows, columns=["State", "evv_model_raw", "evv_aggregator_raw"])
    df["State"] = df["State"].apply(_standardize_state)

    openish_models = {"open model","hybrid model","provider choice","managed care choice","open/hybrid model"}
    df["evv_openish"] = df["evv_model_raw"].astype(str).str.lower().str.strip().isin(openish_models)

    portable_vendors = {"sandata","hhaexchange","therap","netsmart","authenticare","carebridge","fiserv","ppl","vesta"}
    state_specific_markers = ["in-house","aggregator","dhs","isas","lasrs","tmhp","providerone","exprs","utah","new york state","ahcccs"]

    def classify_portability(agg: str) -> bool:
        s = (agg or "").lower()
        if any(m in s for m in state_specific_markers):
            return False
        if any(v in s for v in portable_vendors):
            return True
        return False

    df["evv_portable_vendor"] = df["evv_aggregator_raw"].apply(classify_portability)

    def model_bucket(raw: str) -> str:
        s = (raw or "").strip().lower()
        if "open" in s and "hybrid" in s:
            return "hybrid"
        if "open" in s:
            return "open"
        if "hybrid" in s:
            return "hybrid"
        if "state mandated" in s or "closed" in s:
            return "closed"
        if "provider choice" in s or "managed care choice" in s:
            return "open"
        return "unknown"

    df["evv_model"] = df["evv_model_raw"].apply(model_bucket)
    df["evv_vendor_portability"] = df["evv_portable_vendor"].map({True: "national", False: "state_specific"}).fillna("unknown")

    df_out = df[["State", "evv_model", "evv_vendor_portability"]].copy()
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    df_out.to_csv(out_path, index=False)
    return out_path

def _merge_evv(master: pd.DataFrame) -> pd.DataFrame:
    """
    Merge EVV scores into master (by State name).
    If EVV map doesn't exist, keeps NaNs.
    """
    path = _resolve_input_path(EVV_MAP_FILE)
    if not os.path.exists(path):
        master["evv_model_score"] = np.nan
        master["evv_vendor_score"] = np.nan
        return master

    evv = pd.read_csv(path)
    if "State" not in evv.columns:
        if "state" in evv.columns:
            evv = evv.rename(columns={"state": "State"})
        else:
            master["evv_model_score"] = np.nan
            master["evv_vendor_score"] = np.nan
            return master

    evv["State"] = evv["State"].apply(_standardize_state)

    if "evv_model" in evv.columns:
        evv["evv_model_score"] = evv["evv_model"].apply(_score_evv_model)
    else:
        evv["evv_model_score"] = np.nan

    if "evv_vendor_portability" in evv.columns:
        evv["evv_vendor_score"] = evv["evv_vendor_portability"].apply(_score_vendor_portability)
    else:
        evv["evv_vendor_score"] = np.nan

    evv = evv[["State", "evv_model_score", "evv_vendor_score"]].drop_duplicates("State")
    return master.merge(evv, on="State", how="left")

def add_pri(master: pd.DataFrame) -> pd.DataFrame:
    """
    Adds PRI_commercial_v3 and PRI_policy_v3 + ranks (PRI v3.2).

    PRI is an operational feasibility overlay for piloting:
      - Digital readiness (ACS S2801: smartphone + broadband)
      - EVV feasibility (model openness + vendor portability)
      - Demand transparency (waitlist per 65+; if available)
      - Market need (MFI), governance drag (GPI), and screening friction

    Defensive behavior:
    - If some components are missing, PRI uses available components and reports coverage_*.
    """
    df = master.copy()

    # -----------------------------
    # Demand transparency (waitlist per 1k aged 65+)
    # -----------------------------
    if "demand_transparency_z" not in df.columns:
        if "waitlist_per_1k65" not in df.columns:
            wl = pd.to_numeric(df.get("Waitlist_Total", np.nan), errors="coerce")
            pop65 = pd.to_numeric(df.get("Pop_65plus", np.nan), errors="coerce").clip(lower=1)
            df["waitlist_per_1k65"] = (wl / pop65) * 1000.0
        df["demand_transparency_z"] = _zscore(df["waitlist_per_1k65"])

    # -----------------------------
    # Income proxy (commercial tailwind)
    # -----------------------------
    if "income65_z" not in df.columns and "Income_65plus" in df.columns:
        df["income65_z"] = _zscore(df["Income_65plus"])

    # -----------------------------
    # Governance drag + market need
    # -----------------------------
    if "gpi_drag_z" not in df.columns:
        gpi_col = "GPI_weighted_adj" if "GPI_weighted_adj" in df.columns else "GPI_weighted"
        if gpi_col in df.columns:
            df["gpi_drag_z"] = _zscore(df[gpi_col])

    if "mfi_need_z" not in df.columns:
        mfi_col = "MFI_mpi_adj" if "MFI_mpi_adj" in df.columns else "MFI_mpi"
        if mfi_col in df.columns:
            df["mfi_need_z"] = _zscore(df[mfi_col])

    # -----------------------------
    # Digital readiness
    # -----------------------------
    if "digital_readiness_z" not in df.columns:
        if "digital_readiness" in df.columns:
            df["digital_readiness_z"] = _zscore(df["digital_readiness"])
        else:
            s = pd.to_numeric(df.get("smartphone_share", np.nan), errors="coerce")
            b = pd.to_numeric(df.get("broadband_share", np.nan), errors="coerce")
            if s.notna().any() or b.notna().any():
                df["digital_readiness"] = (s + b) / 2.0
                df["digital_readiness_z"] = _zscore(df["digital_readiness"])
            else:
                df["digital_readiness_z"] = np.nan

    # -----------------------------
    # Screening friction (policy feasibility)
    # -----------------------------
    if "screen_policy_score" not in df.columns:
        if "Screening" in df.columns:
            scr = pd.to_numeric(df["Screening"], errors="coerce")
            df["screen_policy_score"] = 1.0 - scr.clip(lower=0, upper=1)

    # -----------------------------
    # EVV feasibility scores (if already merged via _merge_evv, these exist)
    # -----------------------------
    if "evv_model_score" not in df.columns and "EVV_Model" in df.columns:
        df["evv_model_score"] = df["EVV_Model"].astype(str).apply(_score_evv_model)
    if "evv_vendor_score" not in df.columns and "EVV_Vendor" in df.columns:
        df["evv_vendor_score"] = df["EVV_Vendor"].astype(str).apply(_score_vendor_portability)

    # -----------------------------
    # PRI v3.2 weights (canonical)
    # PRI higher = better pilot readiness
    # So: +digital, +EVV openness/portability, +demand transparency, +market need,
    #     -governance drag (harder to execute).
    # -----------------------------
    weights_comm: Dict[str, float] = {
        "digital_readiness_z": 0.25,
        "demand_transparency_z": 0.20,
        "evv_model_score": 0.10,
        "evv_vendor_score": 0.10,
        "mfi_need_z": 0.20,
        "income65_z": 0.10,
        "gpi_drag_z": -0.15,
    }
    weights_policy: Dict[str, float] = {
        "mfi_need_z": 0.20,
        "digital_readiness_z": 0.15,
        "evv_model_score": 0.10,
        "demand_transparency_z": 0.05,
        "screen_policy_score": 0.10,
        "gpi_drag_z": -0.20,
    }

    df["coverage_comm"] = df.apply(lambda r: _coverage_ratio(r, weights_comm), axis=1)
    df["coverage_policy"] = df.apply(lambda r: _coverage_ratio(r, weights_policy), axis=1)

    df["PRI_commercial_v3"] = df.apply(lambda r: _weighted_sum_ignore_missing(r, weights_comm), axis=1)
    df["PRI_policy_v3"] = df.apply(lambda r: _weighted_sum_ignore_missing(r, weights_policy), axis=1)

    df["rank_commercial_v3"] = df["PRI_commercial_v3"].rank(ascending=False, method="min")
    df["rank_policy_v3"] = df["PRI_policy_v3"].rank(ascending=False, method="min")

    return df

def generate_pri_outputs(df: pd.DataFrame) -> None:
    """Writes PRI outputs into OUTPUT_DIR, aligned with your existing pipeline."""
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    out = df.copy()

    if "PRI_commercial_v3" not in out.columns or "PRI_policy_v3" not in out.columns:
        out = add_pri(out)

    if "Binding_Intensity" in out.columns and pd.to_numeric(out["Binding_Intensity"], errors="coerce").notna().any():
        out["High_BI"] = out["Binding_Intensity"] >= out["Binding_Intensity"].quantile(0.70)
    else:
        out["High_BI"] = False

    out_path = os.path.join(OUTPUT_DIR, "SYPA_PRI_v3_ranking.csv")
    out.to_csv(out_path, index=False)

    hi = out[out["High_BI"]].copy()
    hi.sort_values("rank_commercial_v3").to_csv(os.path.join(OUTPUT_DIR, "SYPA_PRI_v3_highBI_commercial.csv"), index=False)
    hi.sort_values("rank_policy_v3").to_csv(os.path.join(OUTPUT_DIR, "SYPA_PRI_v3_highBI_policy.csv"), index=False)

    print(f"Saved: {out_path}")
    print("Saved: SYPA_PRI_v3_highBI_commercial.csv")
    print("Saved: SYPA_PRI_v3_highBI_policy.csv")

# =============================================================================
# BUILD MASTER + INDICES
# =============================================================================

def build_master() -> pd.DataFrame:
    _check_required_files()
    _validate_weights(GPI_WEIGHTS, "GPI")
    _validate_weights(MFI_WEIGHTS, "MFI")
    input_path = _resolve_input_path(INPUT_FILE)

    # --- base state frame from State_List (preferred)
    try:
        states = pd.read_excel(input_path, sheet_name=SHEET_MAP["STATE_LIST"]).copy()
    except Exception as e:
        _die(f"Could not read State_List sheet from {input_path}: {e}")

    if "state_name" in states.columns and "State" not in states.columns:
        states = states.rename(columns={"state_name": "State"})
    if "State" not in states.columns:
        cand = [c for c in states.columns if "state" in str(c).lower() and "code" not in str(c).lower()]
        if cand:
            states = states.rename(columns={cand[0]: "State"})
    if "State" not in states.columns:
        _die("State_List sheet missing a State/state_name column.")

    if "state_code" not in states.columns:
        cand = [c for c in states.columns if "code" in str(c).lower()]
        if cand:
            states = states.rename(columns={cand[0]: "state_code"})

    states["State"] = states["State"].apply(_standardize_state)
    if states["State"].duplicated().any():
        _die("Duplicate states in State_List sheet.")

    master = states[["State"] + (["state_code"] if "state_code" in states.columns else [])].copy()
    master = _add_region(master)

    # --- workbook inputs
    pop = _load_from_workbook(SHEET_MAP["POP"], {"Total_Population": "Pop_Total", "Total65plus": "Pop_65plus"})
    wait = _load_from_workbook(SHEET_MAP["WAIT"], {
        "Total Waitlist": "Waitlist_Total",
        "State Screens People on 1 or More Waiting Lists for Eligibility": "Screen_Policy",
    })
    cost = _load_from_workbook(SHEET_MAP["COST"], {"Hourly": "Cost_Hourly"})
    inc  = _load_from_workbook(SHEET_MAP["INCOME"], {"Income": "Income_65plus"})
    wage = _load_from_workbook(SHEET_MAP["WAGE"], {"Hourly median wage": "Wage_Aide"})
    liv  = _load_from_workbook(SHEET_MAP["LIVING"], {"HourlyLivableWageWithNoChildren_2025": "Wage_Living"})
    emp  = _load_from_workbook(SHEET_MAP["EMP"], {"Employment_311120": "Aide_Count"})
    aarp = _load_from_workbook(SHEET_MAP["AARP"], {"Overall Performance": "AARP_Score"})

    for df_ in (pop, wait, cost, inc, wage, liv, emp, aarp):
        master = master.merge(df_, on="State", how="left")

    # Population 65+ share
    if "Pop_65plus" in master.columns and "Pop_Total" in master.columns:
        denom = pd.to_numeric(master["Pop_Total"], errors="coerce")
        numer = pd.to_numeric(master["Pop_65plus"], errors="coerce")
        share = np.where(denom > 0, numer / denom, np.nan)
        master["Pop_65plus_Share"] = pd.to_numeric(share, errors="coerce")
        master["Pop_65plus_Pct"] = master["Pop_65plus_Share"] * 100.0

    # --- LTSS rebalancing measures (Users + Expenditures)
    usr = _parse_aarp_style_table(LTSS_USER_FILE, LTSS_USER_SHEET)
    exp = _parse_aarp_style_table(LTSS_EXP_FILE, LTSS_EXP_SHEET)

    usr_overall, usr_65 = _pick_hcbs_percent_cols(usr)
    exp_overall, exp_65 = _pick_hcbs_percent_cols(exp)

    if usr_overall is None and usr_65 is None:
        _die("Could not find any '% HCBS' column in LTSS user file. Check sheet name/export format.")
    if exp_overall is None and exp_65 is None:
        _die("Could not find any '% HCBS' column in LTSS expenditure file. Check sheet name/export format.")

    usr_sel = usr[["State"]].copy()
    if usr_overall is not None:
        usr_sel["Users_HCBS_AllAges_Pct"] = pd.to_numeric(usr[usr_overall], errors="coerce")
    if usr_65 is not None:
        usr_sel["Users_HCBS_65plus_Pct"] = pd.to_numeric(usr[usr_65], errors="coerce")

    exp_sel = exp[["State"]].copy()
    if exp_overall is not None:
        exp_sel["Exp_HCBS_AllAges_Pct"] = pd.to_numeric(exp[exp_overall], errors="coerce")
    if exp_65 is not None:
        exp_sel["Exp_HCBS_65plus_Pct"] = pd.to_numeric(exp[exp_65], errors="coerce")

    master = master.merge(usr_sel, on="State", how="left")
    master = master.merge(exp_sel, on="State", how="left")

    # --- Optional: ADRC access velocity
    adrc_path = _resolve_input_path(ADRC_FILE)
    if os.path.exists(adrc_path):
        try:
            adrc = _load_adrc_access_velocity(adrc_path)
            master = master.merge(adrc, on="State", how="left")
        except Exception as e:
            print(f"[WARN] Could not load ADRC file '{adrc_path}': {e}")
            master["Access_Velocity_Share"] = np.nan
    else:
        master["Access_Velocity_Share"] = np.nan

    # --- Optional: AARP domain ranks
    afford_path = _resolve_input_path(AARP_AFFORD_FILE)
    if os.path.exists(afford_path):
        try:
            aff = _load_aarp_domain_rank(afford_path, prefix="AARP_Afford")
            master = master.merge(aff, on="State", how="left")
        except Exception as e:
            print(f"[WARN] Could not load '{afford_path}': {e}")

    choice_path = _resolve_input_path(AARP_CHOICE_FILE)
    if os.path.exists(choice_path):
        try:
            ch = _load_aarp_domain_rank(choice_path, prefix="AARP_Choice")
            master = master.merge(ch, on="State", how="left")
        except Exception as e:
            print(f"[WARN] Could not load '{choice_path}': {e}")

    # --- Optional: PHI ranks
    phi_path = _resolve_input_path(PHI_FILE)
    if os.path.exists(phi_path):
        try:
            phi = _load_phi(phi_path)
            master = master.merge(phi, on="State", how="left")
        except Exception as e:
            print(f"[WARN] Could not load '{phi_path}': {e}")

    # --- Optional: SARPP RPP (diagnostic)
    sarpp_path = _resolve_input_path(SARPP_FILE)
    if os.path.exists(sarpp_path):
        try:
            rpp = _load_sarpp_rpp_all_items(sarpp_path)
            master = master.merge(rpp, on="State", how="left")
        except Exception as e:
            print(f"[WARN] Could not parse {sarpp_path}: {e}")

    # --- Optional: Digital readiness via ACS S2801 (smartphone + broadband)
    try:
        digital = _load_acs_s2801_digital()
        master = master.merge(digital, on="State", how="left")
    except Exception as e:
        print(f"[WARN] Could not load ACS S2801 digital readiness: {e}")
        master["smartphone_share"] = np.nan
        master["broadband_share"] = np.nan

    # --- Optional: macro controls
    macro_path = _resolve_input_path(MACRO_FILE)
    if os.path.exists(macro_path):
        try:
            macro = _load_macro_controls(macro_path)
            master = master.merge(macro, on="State", how="left")
        except Exception as e:
            print(f"[WARN] Could not load '{macro_path}': {e}")

    # --- Numeric casting for core inputs
    num_fields = [
        "Pop_Total","Pop_65plus","Cost_Hourly","Income_65plus","Wage_Aide","Wage_Living","Aide_Count",
        "Waitlist_Total","AARP_Score","Access_Velocity_Share",
        "AARP_Afford_Rank","AARP_Afford_Tier","AARP_Choice_Rank","AARP_Choice_Tier",
        "PHI_Rank_Overall","PHI_Rank_WorkerSupport","PHI_Rank_WagesBenefits",
        "Unemployment_Rate","Unemployment_Rank","smartphone_share","broadband_share",
    ]
    for c in num_fields:
        if c in master.columns:
            master[c] = pd.to_numeric(master[c], errors="coerce")

    # --- Waitlist diagnostics (not used in indices)
    master["Waitlist_Missing"] = master["Waitlist_Total"].isna().astype(int)
    master["Waitlist_ReportedZero"] = ((master["Waitlist_Total"] == 0) & (master["Waitlist_Missing"] == 0)).astype(int)

    # --- Screening (governance friction)
    master["Screening"] = np.where(
        master["Screen_Policy"].astype(str).str.contains("Yes", case=False, na=False), 1.0, 0.0
    )

    # --- Rebalancing percents -> proportions (prefer 65+; fallback to all-ages)
    master["HCBS_Users_Share"] = master["Users_HCBS_65plus_Pct"] / 100.0
    master["HCBS_Exp_Share"]   = master["Exp_HCBS_65plus_Pct"] / 100.0

    fb_users = master["HCBS_Users_Share"].isna() & master["Users_HCBS_AllAges_Pct"].notna()
    fb_exp   = master["HCBS_Exp_Share"].isna() & master["Exp_HCBS_AllAges_Pct"].notna()
    master.loc[fb_users, "HCBS_Users_Share"] = master.loc[fb_users, "Users_HCBS_AllAges_Pct"] / 100.0
    master.loc[fb_exp,   "HCBS_Exp_Share"]   = master.loc[fb_exp,   "Exp_HCBS_AllAges_Pct"] / 100.0

    for col in ("HCBS_Users_Share","HCBS_Exp_Share"):
        master[f"{col}_Missing"] = master[col].isna().astype(int)

    for col in ("HCBS_Users_Share","HCBS_Exp_Share"):
        bad = master[col].dropna()
        if ((bad < 0) | (bad > 1)).any():
            _die(f"{col} has values outside [0,1]. Check LTSS parsing.")

    # -------------------------------------------------------------------------
    # IMPUTATION (regional median)
    # -------------------------------------------------------------------------
    for col in ("HCBS_Users_Share","HCBS_Exp_Share","Access_Velocity_Share"):
        _impute_regional_median(master, col)

    for col in ("Cost_Hourly","Income_65plus","Wage_Aide","Wage_Living","Aide_Count","Pop_65plus"):
        _impute_regional_median(master, col)

    if "Unemployment_Rate" in master.columns:
        _impute_regional_median(master, "Unemployment_Rate")

    rpp_cols_present = [c for c in master.columns if isinstance(c, str) and c.startswith("RPP_AllItems_") and not c.endswith("_Missing")]
    for c in rpp_cols_present:
        _impute_regional_median(master, c)

    for col in ("smartphone_share","broadband_share"):
        _impute_regional_median(master, col)

    # --- Digital readiness composite (0..1), used by PRI
    master["digital_readiness"] = (
        pd.to_numeric(master.get("smartphone_share", np.nan), errors="coerce")
        + pd.to_numeric(master.get("broadband_share", np.nan), errors="coerce")
    ) / 2.0

    # =============================================================================
    # GOVERNANCE SIGNALS (higher = worse)
    # =============================================================================
    if USE_LOGIT_FOR_REBAL:
        master["Signal_Pressure_Users"] = -_logit(master["HCBS_Users_Share"])
        master["Signal_Pressure_Exp"]   = -_logit(master["HCBS_Exp_Share"])
        master["Signal_Access_Velocity"] = -_logit(master["Access_Velocity_Share"])
    else:
        master["Signal_Pressure_Users"] = 1.0 - master["HCBS_Users_Share"]
        master["Signal_Pressure_Exp"]   = 1.0 - master["HCBS_Exp_Share"]
        master["Signal_Access_Velocity"] = 1.0 - master["Access_Velocity_Share"]

    master["Z_Pressure_Users"]  = _winsorized_z(master["Signal_Pressure_Users"])
    master["Z_Pressure_Exp"]    = _winsorized_z(master["Signal_Pressure_Exp"])
    master["Z_Screening"]       = _winsorized_z(master["Screening"])
    master["Z_Access_Velocity"] = _winsorized_z(master["Signal_Access_Velocity"])

    gpi_z_cols_all = ["Z_Pressure_Users", "Z_Pressure_Exp", "Z_Screening", "Z_Access_Velocity"]
    gpi_z_cols_core = ["Z_Pressure_Users", "Z_Pressure_Exp", "Z_Screening"]

    master["GPI_weighted"] = (
        GPI_WEIGHTS["Pressure_Users"]  * master["Z_Pressure_Users"]
        + GPI_WEIGHTS["Pressure_Exp"]  * master["Z_Pressure_Exp"]
        + GPI_WEIGHTS["Screening"]     * master["Z_Screening"]
        + GPI_WEIGHTS["Access_Velocity"] * master["Z_Access_Velocity"]
    )

    gpi_z_all = master[gpi_z_cols_all]
    master["GPI_mean"] = gpi_z_all.mean(axis=1)
    master["GPI_std"]  = gpi_z_all.std(axis=1, ddof=0)
    master["GPI_mpi"]  = master["GPI_mean"] + LAMBDA * master["GPI_std"]

    master["GPI_bottleneck_core"] = master[gpi_z_cols_core].max(axis=1)
    master["GPI_bottleneck_all"]  = master[gpi_z_cols_all].max(axis=1)

    # =============================================================================
    # MARKET SIGNALS (higher = worse)
    # =============================================================================
    annual_cost = master["Cost_Hourly"] * HOURS_PER_WEEK * WEEKS_PER_YEAR

    master["Cost_Burden"] = np.log(_safe_div(annual_cost, master["Income_65plus"]))
    master["Wage_Gap"] = np.log(_safe_div(master["Wage_Living"], master["Wage_Aide"]))

    master["Aide_Density"] = (master["Aide_Count"] / master["Pop_65plus"].clip(lower=1)) * 1000.0
    master["Labor_Scarcity"] = np.log(_safe_div(1.0, master["Aide_Density"].clip(lower=EPS)))

    master["Z_Cost_Burden"]    = _winsorized_z(master["Cost_Burden"])
    master["Z_Wage_Gap"]       = _winsorized_z(master["Wage_Gap"])
    master["Z_Labor_Scarcity"] = _winsorized_z(master["Labor_Scarcity"])

    mfi_z_cols = ["Z_Cost_Burden", "Z_Wage_Gap", "Z_Labor_Scarcity"]
    z_mfi = master[mfi_z_cols]

    master["MFI_mean"] = (
        MFI_WEIGHTS["Cost_Burden"]      * master["Z_Cost_Burden"]
        + MFI_WEIGHTS["Wage_Gap"]       * master["Z_Wage_Gap"]
        + MFI_WEIGHTS["Labor_Scarcity"] * master["Z_Labor_Scarcity"]
    )

    master["MFI_std"] = z_mfi.std(axis=1, ddof=0)
    master["MFI_mpi"] = master["MFI_mean"] + LAMBDA * master["MFI_std"]  # CANONICAL

    master["MFI_bottleneck"] = z_mfi.max(axis=1)
    master["MFI_bottleneck_component"] = z_mfi.idxmax(axis=1)

    master["MFI_geom"] = _geometric_mean_shifted_z(z_mfi)

    # =============================================================================
    # MACRO-CONTROL SCENARIO (optional)
    # =============================================================================
    rpp_cols_present = [c for c in master.columns if isinstance(c, str) and c.startswith("RPP_AllItems_") and not c.endswith("_Missing")]
    if rpp_cols_present:
        rpp_col_latest = sorted(rpp_cols_present)[-1]
        master["Macro_RPP_AllItems"] = pd.to_numeric(master[rpp_col_latest], errors="coerce")
    else:
        master["Macro_RPP_AllItems"] = np.nan

    macro_controls = []
    if "Unemployment_Rate" in master.columns and master["Unemployment_Rate"].notna().sum() > 10:
        macro_controls.append("Unemployment_Rate")
    if master["Macro_RPP_AllItems"].notna().sum() > 10:
        macro_controls.append("Macro_RPP_AllItems")

    if macro_controls:
        master["GPI_weighted_adj"] = _linear_residual(master, "GPI_weighted", macro_controls)
        master["MFI_mpi_adj"]      = _linear_residual(master, "MFI_mpi", macro_controls)
    else:
        master["GPI_weighted_adj"] = np.nan
        master["MFI_mpi_adj"]      = np.nan

    # =============================================================================
    # CANONICAL QUADRANTS (GPI_weighted vs MFI_mpi)
    # =============================================================================
    if QUADRANT_SPLIT == "mean":
        g_cut = master["GPI_weighted"].mean()
        m_cut = master["MFI_mpi"].mean()
    elif QUADRANT_SPLIT == "zero":
        g_cut = 0.0
        m_cut = 0.0
    else:
        g_cut = master["GPI_weighted"].median()
        m_cut = master["MFI_mpi"].median()

    def quad(r) -> str:
        if r["GPI_weighted"] >= g_cut and r["MFI_mpi"] >= m_cut:
            return "Double Bind"
        if r["GPI_weighted"] >= g_cut:
            return "Policy Bottleneck"
        if r["MFI_mpi"] >= m_cut:
            return "Market Failure"
        return "High Performance"

    master["Quadrant"] = master.apply(quad, axis=1)

    story = {
        "Double Bind": "Double Bind (high policy + high market constraints)",
        "Policy Bottleneck": "Squandered Opportunity (market workable; policy blocks access)",
        "Market Failure": "Tragic Heroes (policy tries; market still constrains care)",
        "High Performance": "High Performance (low pressure + low friction)",
    }
    master["Quadrant_Story"] = master["Quadrant"].map(story)

    master = _add_state_codes(master)

    master["Binding_Intensity"] = np.sqrt(
        np.maximum(master["GPI_weighted"], 0) ** 2 + np.maximum(master["MFI_mpi"], 0) ** 2
    )

    master["GPI_rank"] = master["GPI_weighted"].rank(ascending=False, method="min")
    master["MFI_rank"] = master["MFI_mpi"].rank(ascending=False, method="min")

    return master

def _partial_corr(df: pd.DataFrame, x: str, y: str, controls: List[str]) -> Tuple[float, float]:
    """
    Partial correlation between x and y controlling for controls.
    Pearson partial corr: corr(resid(x|controls), resid(y|controls))
    Spearman partial corr: same but on rank-transformed variables.
    """
    controls = [c for c in controls if c in df.columns]
    if not controls:
        return (np.nan, np.nan)

    rx = _linear_residual(df, x, controls)
    ry = _linear_residual(df, y, controls)
    pear = rx.corr(ry)

    df_r = df.copy()
    df_r[x] = pd.to_numeric(df_r[x], errors="coerce").rank(method="average")
    df_r[y] = pd.to_numeric(df_r[y], errors="coerce").rank(method="average")
    for c in controls:
        df_r[c] = pd.to_numeric(df_r[c], errors="coerce").rank(method="average")
    rsx = _linear_residual(df_r, x, controls)
    rsy = _linear_residual(df_r, y, controls)
    spear = rsx.corr(rsy)

    return (float(pear) if pear is not None else np.nan, float(spear) if spear is not None else np.nan)

# =============================================================================
# CORRELATION / VALIDATION AUDIT
# =============================================================================

def _corr_pair(df: pd.DataFrame, x: str, y: str) -> Tuple[float, float]:
    """Return (pearson, spearman) for df[x], df[y]."""
    pear = df[x].corr(df[y])
    spear = _spearman_corr(df[x], df[y])
    return float(pear) if pear is not None else np.nan, float(spear) if spear is not None else np.nan

def correlation_audit(df: pd.DataFrame) -> Dict[str, pd.DataFrame]:
    results: Dict[str, pd.DataFrame] = {}

    macro_controls: List[str] = []
    if "Unemployment_Rate" in df.columns and df["Unemployment_Rate"].notna().sum() > 10:
        macro_controls.append("Unemployment_Rate")
    if "Macro_RPP_AllItems" in df.columns and df["Macro_RPP_AllItems"].notna().sum() > 10:
        macro_controls.append("Macro_RPP_AllItems")

    if macro_controls:
        print("\n--- MACRO-CONTROL SCENARIO (partial correlation) ---")
        print("Controls:", ", ".join(macro_controls))

        macro_rows: List[Dict[str, Any]] = []

        if INCLUDE_MACRO_ADJUSTED_IN_PRINT_AUDIT:
            if "GPI_weighted_adj" in df.columns and "MFI_mpi_adj" in df.columns:
                pear_adj = df["GPI_weighted_adj"].corr(df["MFI_mpi_adj"])
                spear_adj = _spearman_corr(df["GPI_weighted_adj"], df["MFI_mpi_adj"])
                print(f"Pearson  Corr(GPI_weighted_adj, MFI_mpi_adj)  = {pear_adj:+.3f}")
                print(f"Spearman Corr(GPI_weighted_adj, MFI_mpi_adj)  = {spear_adj:+.3f}")
                macro_rows.append({
                    "Pair": "GPI_weighted_adj vs MFI_mpi_adj",
                    "Pearson": float(pear_adj) if pear_adj is not None else np.nan,
                    "Spearman": float(spear_adj) if spear_adj is not None else np.nan,
                    "Notes": "Macro-adjusted residuals"
                })

        if "AARP_Score" in df.columns and df["AARP_Score"].notna().sum() > 10:
            p, s = _partial_corr(df, "GPI_weighted", "AARP_Score", macro_controls)
            print(f"Partial Corr(GPI_weighted, AARP_Score | macro) Pearson={p:+.3f}  Spearman={s:+.3f}")
            macro_rows.append({
                "Pair": "GPI_weighted vs AARP_Score",
                "Pearson": float(p),
                "Spearman": float(s),
                "Notes": f"Partial | controls: {', '.join(macro_controls)}"
            })

        if "PHI_Rank_Overall" in df.columns and df["PHI_Rank_Overall"].notna().sum() > 10:
            p, s = _partial_corr(df, "MFI_mpi", "PHI_Rank_Overall", macro_controls)
            print(f"Partial Corr(MFI_mpi, PHI_Rank_Overall | macro) Pearson={p:+.3f}  Spearman={s:+.3f}")
            macro_rows.append({
                "Pair": "MFI_mpi vs PHI_Rank_Overall",
                "Pearson": float(p),
                "Spearman": float(s),
                "Notes": f"Partial | controls: {', '.join(macro_controls)}"
            })

        if macro_rows:
            results["Macro_Control"] = pd.DataFrame(macro_rows)

    print("\n--- CANONICAL CORRELATIONS ---")
    p, s = _corr_pair(df, "GPI_weighted", "MFI_mpi")
    print(f"Pearson  Corr(GPI_weighted, MFI_mpi)  = {p:.3f}")
    print(f"Spearman Corr(GPI_weighted, MFI_mpi)  = {s:.3f}")
    results["Canonical"] = pd.DataFrame([
        {"Pair": "GPI_weighted vs MFI_mpi", "Pearson": float(p), "Spearman": float(s)}
    ])

    gpi_vars = ["GPI_weighted","GPI_mean","GPI_std","GPI_mpi","GPI_bottleneck_core","GPI_bottleneck_all"]
    mfi_vars = ["MFI_mean","MFI_std","MFI_mpi","MFI_bottleneck","MFI_geom"]

    if "AARP_Score" in df.columns and df["AARP_Score"].notna().sum() > 10:
        print("\n--- GPI VARIANTS vs AARP_Score (expect negative; higher AARP = better) ---")
        rows: List[Dict[str, Any]] = []
        for g in gpi_vars:
            p, s = _corr_pair(df, g, "AARP_Score")
            print(f"{g:<18} Pearson={p:+.3f}  Spearman={s:+.3f}")
            rows.append({"Index": g, "Pearson": float(p), "Spearman": float(s)})
        if rows:
            results["GPI_vs_AARP_Score"] = pd.DataFrame(rows)

    if "AARP_Afford_Rank" in df.columns and df["AARP_Afford_Rank"].notna().sum() > 10:
        print("\n--- INDEX VARIANTS vs AARP_Afford_Rank (expect positive; higher rank = worse) ---")
        rows = []
        for g in gpi_vars:
            p, s = _corr_pair(df, g, "AARP_Afford_Rank")
            print(f"{g:<18} Pearson={p:+.3f}  Spearman={s:+.3f}")
            rows.append({"Index": g, "Pearson": float(p), "Spearman": float(s), "Family": "GPI"})
        for m in mfi_vars:
            p, s = _corr_pair(df, m, "AARP_Afford_Rank")
            print(f"{m:<18} Pearson={p:+.3f}  Spearman={s:+.3f}")
            rows.append({"Index": m, "Pearson": float(p), "Spearman": float(s), "Family": "MFI"})
        if rows:
            results["Index_vs_AARP_Afford"] = pd.DataFrame(rows)

    if "AARP_Choice_Rank" in df.columns and df["AARP_Choice_Rank"].notna().sum() > 10:
        print("\n--- INDEX VARIANTS vs AARP_Choice_Rank (expect positive; higher rank = worse) ---")
        rows = []
        for g in gpi_vars:
            p, s = _corr_pair(df, g, "AARP_Choice_Rank")
            print(f"{g:<18} Pearson={p:+.3f}  Spearman={s:+.3f}")
            rows.append({"Index": g, "Pearson": float(p), "Spearman": float(s), "Family": "GPI"})
        for m in mfi_vars:
            p, s = _corr_pair(df, m, "AARP_Choice_Rank")
            print(f"{m:<18} Pearson={p:+.3f}  Spearman={s:+.3f}")
            rows.append({"Index": m, "Pearson": float(p), "Spearman": float(s), "Family": "MFI"})
        if rows:
            results["Index_vs_AARP_Choice"] = pd.DataFrame(rows)

    phi_cols = [c for c in df.columns if c.startswith("PHI_Rank_")]
    if phi_cols:
        for phi in phi_cols:
            if df[phi].notna().sum() > 10:
                print(f"\n--- MFI VARIANTS vs {phi} (expect positive if higher rank = worse) ---")
                rows = []
                for m in mfi_vars:
                    p, s = _corr_pair(df, m, phi)
                    print(f"{m:<18} Pearson={p:+.3f}  Spearman={s:+.3f}")
                    rows.append({"Index": m, "Pearson": float(p), "Spearman": float(s)})
                if rows:
                    results[f"MFI_vs_{phi}"] = pd.DataFrame(rows)

    rpp_cols = [c for c in df.columns if isinstance(c, str) and c.startswith("RPP_AllItems_") and not c.endswith("_Missing")]
    if rpp_cols:
        rpp_col = sorted(rpp_cols)[-1]
        if df[rpp_col].notna().sum() > 10:
            print(f"\n--- MFI VARIANTS vs {rpp_col} (diagnostic only) ---")
            rows = []
            for m in mfi_vars:
                p, s = _corr_pair(df, m, rpp_col)
                print(f"{m:<18} Pearson={p:+.3f}  Spearman={s:+.3f}")
                rows.append({"Index": m, "Pearson": float(p), "Spearman": float(s)})
            if rows:
                results[f"MFI_vs_{rpp_col}"] = pd.DataFrame(rows)

    cols_for_matrix = (
        gpi_vars + mfi_vars
        + [c for c in ["AARP_Score","AARP_Afford_Rank","AARP_Choice_Rank"] if c in df.columns]
        + phi_cols
        + rpp_cols
    )
    cols_for_matrix = [c for c in cols_for_matrix if c in df.columns]

    if len(cols_for_matrix) >= 3:
        print("\n--- FULL CORRELATION AUDIT (Pearson) ---")
        pearson_matrix = df[cols_for_matrix].corr()
        print(pearson_matrix.round(3))
        results["Matrix_Pearson"] = pearson_matrix

        print("\n--- FULL CORRELATION AUDIT (Spearman) ---")
        spearman = df[cols_for_matrix].rank(method="average").corr()
        print(spearman.round(3))
        results["Matrix_Spearman"] = spearman

    print("\n--- BOTTLENECK vs BOTTLENECK (explicit) ---")
    if "GPI_bottleneck_core" in df.columns and "MFI_bottleneck" in df.columns:
        p, s = _corr_pair(df, "GPI_bottleneck_core", "MFI_bottleneck")
        print(f"Pearson  Corr(GPI_bottleneck_core, MFI_bottleneck) = {p:.3f}")
        print(f"Spearman Corr(GPI_bottleneck_core, MFI_bottleneck) = {s:.3f}")
        results["Bottleneck_vs_Bottleneck"] = pd.DataFrame([
            {"Pair": "GPI_bottleneck_core vs MFI_bottleneck", "Pearson": float(p), "Spearman": float(s)}
        ])

    return results

# =============================================================================
# OUTPUTS (CSV + visuals + PRI outputs)
# =============================================================================

def _ensure_evv_map(force: bool = False) -> None:
    """Create EVV map if missing (or overwrite if force=True)."""
    path = _resolve_input_path(EVV_MAP_FILE)
    if force or not os.path.exists(path):
        try:
            build_evv_regulatory_map(EVV_MAP_FILE)
            print(f"[INFO] EVV map written: {EVV_MAP_FILE}")
        except Exception as e:
            print(f"[WARN] Could not generate EVV map '{EVV_MAP_FILE}': {e}")

def generate_outputs(df: pd.DataFrame, skip_pri: bool = False) -> pd.DataFrame:
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    corr_tables = correlation_audit(df)

    if corr_tables:
        corr_path = os.path.join(OUTPUT_DIR, CORRELATION_XLSX_NAME)
        used_sheet_names: set = set()

        def _excel_sheet_name(label: str) -> str:
            cleaned = re.sub(r"[^A-Za-z0-9 _-]", "_", label).strip() or "Sheet"
            cleaned = cleaned[:31]
            base = cleaned
            counter = 1
            while cleaned in used_sheet_names:
                suffix = f"_{counter}"
                cleaned = (base[:31 - len(suffix)] + suffix)
                counter += 1
            used_sheet_names.add(cleaned)
            return cleaned

        with pd.ExcelWriter(corr_path, engine="openpyxl") as writer:
            for name, table in corr_tables.items():
                if table is None or table.empty:
                    continue
                sheet_name = _excel_sheet_name(name)
                write_index = not isinstance(table.index, pd.RangeIndex)
                table.to_excel(writer, sheet_name=sheet_name, index=write_index)
        print(f"Saved: {corr_path}")

    print("\n--- DATA QUALITY (pre-impute flags) ---")
    for flag in [
        "HCBS_Users_Share_Missing","HCBS_Exp_Share_Missing","Access_Velocity_Share_Missing",
        "Waitlist_Missing","Waitlist_ReportedZero"
    ]:
        if flag in df.columns:
            print(f"{flag:<28}: {int(df[flag].sum())} states")

    df_out = df.copy()
    if not skip_pri:
        df_out = _merge_evv(df_out)
        df_out = add_pri(df_out)

    out_csv = os.path.join(OUTPUT_DIR, "SYPA_Final_Indices_GPI_MFI.csv")
    df_out.to_csv(out_csv, index=False)
    print(f"\nSaved: {out_csv}")

    if not skip_pri:
        generate_pri_outputs(df_out)

    show_cols = [
        "State","GPI_weighted","MFI_mpi","Quadrant","Quadrant_Story",
        "MFI_bottleneck_component","MFI_bottleneck","Binding_Intensity"
    ]
    show = df_out[[c for c in show_cols if c in df_out.columns]].copy()
    show = show.sort_values("Binding_Intensity", ascending=False)

    print("\nTop 10 by Binding_Intensity (canonical):")
    for _, r in show.head(10).iterrows():
        bn = r.get("MFI_bottleneck_component", "")
        bnsev = r.get("MFI_bottleneck", np.nan)
        print(
            f"  {r['State']:<20}  "
            f"GPI_weighted={r['GPI_weighted']:+.2f}  "
            f"MFI_mpi={r['MFI_mpi']:+.2f}  "
            f"Bottleneck={bn} ({bnsev:+.2f})  "
            f"{r['Quadrant']}"
        )

    # ---- Visuals
    print("\n--- GENERATING VISUALS ---")

    palette = {
        "Double Bind": "#ff5c8a",
        "Policy Bottleneck": "#ff9f43",
        "Market Failure": "#ffd166",
        "High Performance": "#06d6a0",
    }

    if QUADRANT_SPLIT == "mean":
        g_cut = df_out["GPI_weighted"].mean()
        m_cut = df_out["MFI_mpi"].mean()
    elif QUADRANT_SPLIT == "zero":
        g_cut = 0.0
        m_cut = 0.0
    else:
        g_cut = df_out["GPI_weighted"].median()
        m_cut = df_out["MFI_mpi"].median()

    labels = df_out["State_Code"].fillna(df_out["State"].astype(str).str[:3].str.upper())

    plt.style.use("default")
    fig, ax = plt.subplots(figsize=(12, 10), facecolor="white")
    ax.set_facecolor("white")

    if sns is not None:
        sns.scatterplot(
            data=df_out, x="GPI_weighted", y="MFI_mpi", hue="Quadrant",
            palette=palette, s=220, alpha=0.92, linewidth=0.8, edgecolor="white", ax=ax
        )
    else:
        for q, color in palette.items():
            sub = df_out[df_out["Quadrant"] == q]
            ax.scatter(sub["GPI_weighted"], sub["MFI_mpi"], s=220, alpha=0.92, label=q, c=color, edgecolors="white", linewidths=0.8)

    ax.axvline(g_cut, color="gray", linestyle="--", linewidth=1.2, alpha=0.6)
    ax.axhline(m_cut, color="gray", linestyle="--", linewidth=1.2, alpha=0.6)

    for (_, row), lab in zip(df_out.iterrows(), labels):
        ax.annotate(lab, (row["GPI_weighted"], row["MFI_mpi"]), xytext=(4, 4), textcoords="offset points",
                    fontsize=8, color="black", alpha=0.65)

    ax.set_title("GPI vs MFI — Canonical Diagnostic (GPI_weighted vs MFI_mpi)", fontsize=16, weight="bold")
    ax.set_xlabel("GPI_weighted (higher = worse governance pressure)", fontsize=12)
    ax.set_ylabel("MFI_mpi (higher = worse market friction)", fontsize=12)

    leg = ax.legend(title="", loc="upper center", bbox_to_anchor=(0.5, -0.12), ncol=4, frameon=False)
    fig.tight_layout()
    fig.savefig(os.path.join(OUTPUT_DIR, "SYPA_Diagnostic_Scatter.png"), dpi=300, facecolor=fig.get_facecolor())
    plt.close(fig)
    print("Saved: SYPA_Diagnostic_Scatter.png")

    if px is None:
        print("[WARN] plotly is not available; skipping interactive HTML outputs.")
        return df_out

    bubble = np.clip(df_out["Binding_Intensity"].fillna(0) * 10 + 8, 8, 34)

    hover_fmt = {
        "GPI_weighted":":.2f","MFI_mpi":":.2f",
        "Quadrant_Story": True,
        "Binding_Intensity":":.2f",
        "MFI_bottleneck_component": True,
        "MFI_bottleneck":":.2f",
        "MFI_mean":":.2f","MFI_std":":.2f","MFI_geom":":.2f",
        "GPI_mpi":":.2f","GPI_bottleneck_all":":.2f",
        "HCBS_Users_Share":":.2f","HCBS_Exp_Share":":.2f",
        "Access_Velocity_Share":":.2f",
        "Screening":":.0f",
        "Pop_65plus_Pct":":.2f",
        "Cost_Burden":":.2f","Wage_Gap":":.2f","Aide_Density":":.2f","Labor_Scarcity":":.2f",
        "Waitlist_Total": True,
        "AARP_Score": True,
        "AARP_Afford_Rank": True,
        "AARP_Choice_Rank": True,
        "PHI_Rank_Overall": True,
        "PHI_Rank_WorkerSupport": True,
        "PHI_Rank_WagesBenefits": True,
        "Unemployment_Rate":":.2f",
        "Macro_RPP_AllItems":":.2f",
        # PRI fields
        "digital_readiness":":.2f",
        "digital_readiness_z":":.2f",
        "PRI_commercial_v3":":.2f",
        "PRI_policy_v3":":.2f",
        "rank_commercial_v3": True,
        "rank_policy_v3": True,
        "coverage_comm":":.2f",
        "coverage_policy":":.2f",
        "waitlist_per_1k65":":.2f",
        "evv_model_score":":.2f",
        "evv_vendor_score":":.2f",
    }
    rpp_cols = [c for c in df_out.columns if isinstance(c, str) and c.startswith("RPP_AllItems_") and not c.endswith("_Missing")]
    for c in rpp_cols:
        hover_fmt[c] = True
    hover_data = {k: v for k, v in hover_fmt.items() if k in df_out.columns}

    if INCLUDE_MACRO_ADJUSTED_IN_HOVER:
        if "GPI_weighted_adj" in df_out.columns:
            hover_data["GPI_weighted_adj"] = ":.2f"
        if "MFI_mpi_adj" in df_out.columns:
            hover_data["MFI_mpi_adj"] = ":.2f"

    fig_sc = px.scatter(
        df_out,
        x="GPI_weighted", y="MFI_mpi", color="Quadrant",
        color_discrete_map=palette,
        hover_name="State",
        hover_data=hover_data,
        size=bubble,
        opacity=0.9,
        text=labels
    )

    x_min = min(-3.0, float(df_out["GPI_weighted"].min()) - 0.4)
    x_max = max(3.0, float(df_out["GPI_weighted"].max()) + 0.4)
    y_min = min(-3.0, float(df_out["MFI_mpi"].min()) - 0.6)
    y_max = max(3.5, float(df_out["MFI_mpi"].max()) + 0.6)

    fig_sc.update_layout(
        template="plotly_dark",
        title="GPI_weighted vs MFI_mpi — Interactive (canonical axes)",
        legend=dict(orientation="h", y=-0.22, x=0.5, xanchor="center"),
        xaxis=dict(range=[x_min, x_max]),
        yaxis=dict(range=[y_min, y_max]),
    )
    fig_sc.add_shape(type="line", x0=g_cut, x1=g_cut, y0=y_min, y1=y_max,
                     line=dict(color="rgba(255,255,255,0.25)", dash="dash"))
    fig_sc.add_shape(type="line", x0=x_min, x1=x_max, y0=m_cut, y1=m_cut,
                     line=dict(color="rgba(255,255,255,0.25)", dash="dash"))

    fig_sc.write_html(os.path.join(OUTPUT_DIR, "SYPA_Diagnostic_Scatter.html"))
    print("Saved: SYPA_Diagnostic_Scatter.html")

    if "Pop_65plus_Pct" in df_out.columns and pd.to_numeric(df_out["Pop_65plus_Pct"], errors="coerce").notna().any():
        fig_sc65 = px.scatter(
            df_out,
            x="GPI_weighted", y="MFI_mpi", color="Quadrant",
            color_discrete_map=palette,
            hover_name="State",
            hover_data=hover_data,
            size=pd.to_numeric(df_out["Pop_65plus_Pct"], errors="coerce"),
            size_max=48,
            opacity=0.85,
            text=labels,
        )
        fig_sc65.update_layout(
            template="plotly_dark",
            title="GPI_weighted vs MFI_mpi — Bubble = % Population 65+",
            legend=dict(orientation="h", y=-0.22, x=0.5, xanchor="center"),
            xaxis=dict(range=[x_min, x_max]),
            yaxis=dict(range=[y_min, y_max]),
        )
        fig_sc65.add_shape(type="line", x0=g_cut, x1=g_cut, y0=y_min, y1=y_max,
                           line=dict(color="rgba(255,255,255,0.25)", dash="dash"))
        fig_sc65.add_shape(type="line", x0=x_min, x1=x_max, y0=m_cut, y1=m_cut,
                           line=dict(color="rgba(255,255,255,0.25)", dash="dash"))

        fig_sc65.write_html(os.path.join(OUTPUT_DIR, "SYPA_Diagnostic_Scatter_65plus.html"))
        print("Saved: SYPA_Diagnostic_Scatter_65plus.html")
    else:
        print("[WARN] Population 65+ share not found; skipping 65+ bubble scatter.")

    map_hover_fmt = {
        "GPI_weighted":":.2f","MFI_mpi":":.2f","GPI_rank":True,"MFI_rank":True,
        "Binding_Intensity":":.2f","Quadrant_Story":True,
        "rank_commercial_v3": True, "rank_policy_v3": True,
    }
    map_hover = {k: v for k, v in map_hover_fmt.items() if k in df_out.columns}

    fig_map = px.choropleth(
        df_out,
        locations="State_Code",
        locationmode="USA-states",
        color="Quadrant",
        scope="usa",
        color_discrete_map=palette,
        hover_name="State",
        hover_data=map_hover,
        title="US Care Economy Diagnosis — Quadrants (canonical)"
    )
    fig_map.update_layout(margin={"r":0, "t":50, "l":0, "b":0})
    fig_map.write_html(os.path.join(OUTPUT_DIR, "SYPA_Geographic_Map.html"))
    print("Saved: SYPA_Geographic_Map.html")

    return df_out

# =============================================================================
# SENSITIVITY TESTS (one-factor-at-a-time robustness checks)
# =============================================================================

def run_sensitivity_tests(output_xlsx: Optional[str] = None,
                          top_k: int = 10) -> str:
    """Run a compact suite of sensitivity tests and save results to an Excel workbook."""
    os.makedirs(SENSITIVITY_OUTPUT_DIR, exist_ok=True)

    if output_xlsx is None or str(output_xlsx).strip() == "":
        output_xlsx = os.path.join(SENSITIVITY_OUTPUT_DIR, SENSITIVITY_XLSX_NAME)
    elif os.path.isabs(output_xlsx):
        pass
    else:
        output_xlsx = os.path.join(SENSITIVITY_OUTPUT_DIR, os.path.basename(output_xlsx))

    baseline = build_master()

    base_top = set(
        baseline.sort_values("Binding_Intensity", ascending=False)
                .head(top_k)["State"].tolist()
    )
    base_quadrant = baseline.set_index("State")["Quadrant"]

    def spearman_rank(a: pd.Series, b: pd.Series) -> float:
        return float(pd.to_numeric(a, errors="coerce").rank(method="average")
                     .corr(pd.to_numeric(b, errors="coerce").rank(method="average")))

    def apply_globals(changes: Dict[str, Any]) -> Dict[str, Any]:
        saved: Dict[str, Any] = {}
        for k, v in changes.items():
            saved[k] = globals().get(k)
            globals()[k] = v
        return saved

    def restore_globals(saved: Dict[str, Any]) -> None:
        for k, v in saved.items():
            globals()[k] = v

    gpi_equal = {"Pressure_Users": 0.25, "Pressure_Exp": 0.25, "Screening": 0.25, "Access_Velocity": 0.25}
    gpi_pressure_heavy = {"Pressure_Users": 0.40, "Pressure_Exp": 0.40, "Screening": 0.10, "Access_Velocity": 0.10}
    gpi_balanced = {"Pressure_Users": 0.30, "Pressure_Exp": 0.30, "Screening": 0.20, "Access_Velocity": 0.20}
    gpi_no_access = {
        "Pressure_Users": 0.35 / 0.85,
        "Pressure_Exp": 0.35 / 0.85,
        "Screening": 0.15 / 0.85,
        "Access_Velocity": 0.0,
    }

    mfi_cost_heavy = {"Cost_Burden": 0.50, "Wage_Gap": 0.25, "Labor_Scarcity": 0.25}
    mfi_wage_heavy = {"Cost_Burden": 0.25, "Wage_Gap": 0.50, "Labor_Scarcity": 0.25}
    mfi_labor_heavy = {"Cost_Burden": 0.25, "Wage_Gap": 0.25, "Labor_Scarcity": 0.50}

    scenarios: List[Dict[str, Any]] = [
        {"name": "Baseline", "changes": {}},

        {"name": "GPI weights: equal", "changes": {"GPI_WEIGHTS": gpi_equal}},
        {"name": "GPI weights: pressure-heavy", "changes": {"GPI_WEIGHTS": gpi_pressure_heavy}},
        {"name": "GPI weights: balanced", "changes": {"GPI_WEIGHTS": gpi_balanced}},
        {"name": "GPI weights: no access velocity", "changes": {"GPI_WEIGHTS": gpi_no_access}},

        {"name": "MFI weights: cost-heavy", "changes": {"MFI_WEIGHTS": mfi_cost_heavy}},
        {"name": "MFI weights: wage-heavy", "changes": {"MFI_WEIGHTS": mfi_wage_heavy}},
        {"name": "MFI weights: labor-heavy", "changes": {"MFI_WEIGHTS": mfi_labor_heavy}},

        {"name": "LAMBDA=0.0 (mean only)", "changes": {"LAMBDA": 0.0}},
        {"name": "LAMBDA=0.5", "changes": {"LAMBDA": 0.5}},
        {"name": "LAMBDA=1.5", "changes": {"LAMBDA": 1.5}},

        {"name": "Z_CAP=2.0", "changes": {"Z_CAP": 2.0}},
        {"name": "Z_CAP=3.0", "changes": {"Z_CAP": 3.0}},

        {"name": "Z_DDOF=0 (population SD)", "changes": {"Z_DDOF": 0}},
        {"name": "Z_DDOF=2", "changes": {"Z_DDOF": 2}},

        {"name": "Linear (1-p) shares", "changes": {"USE_LOGIT_FOR_REBAL": False}},
        {"name": "EPS=1e-3 (logit clip)", "changes": {"EPS": 1e-3, "USE_LOGIT_FOR_REBAL": True}},

        {"name": "Hours/week=20", "changes": {"HOURS_PER_WEEK": 20}},
        {"name": "Hours/week=40", "changes": {"HOURS_PER_WEEK": 40}},

        {"name": "Weeks/year=48", "changes": {"WEEKS_PER_YEAR": 48}},
        {"name": "Weeks/year=56", "changes": {"WEEKS_PER_YEAR": 56}},

        {"name": "Quadrant split=mean", "changes": {"QUADRANT_SPLIT": "mean"}},
        {"name": "Quadrant split=zero", "changes": {"QUADRANT_SPLIT": "zero"}},
    ]

    summary_rows: List[Dict[str, Any]] = []
    detail_frames: Dict[str, pd.DataFrame] = {}

    baseline_globals = {
        "GPI_WEIGHTS": dict(GPI_WEIGHTS),
        "MFI_WEIGHTS": dict(MFI_WEIGHTS),
        "LAMBDA": LAMBDA,
        "Z_DDOF": Z_DDOF,
        "Z_CAP": Z_CAP,
        "EPS": EPS,
        "USE_LOGIT_FOR_REBAL": USE_LOGIT_FOR_REBAL,
        "HOURS_PER_WEEK": HOURS_PER_WEEK,
        "WEEKS_PER_YEAR": WEEKS_PER_YEAR,
        "QUADRANT_SPLIT": QUADRANT_SPLIT,
    }

    for sc in scenarios:
        name = sc["name"]
        changes = sc["changes"]

        saved = apply_globals(changes)
        try:
            _validate_weights(GPI_WEIGHTS, "GPI")
            _validate_weights(MFI_WEIGHTS, "MFI")

            df_sc = baseline if name == "Baseline" else build_master()

            gpi_s = spearman_rank(df_sc["GPI_weighted"], baseline["GPI_weighted"])
            mfi_s = spearman_rank(df_sc["MFI_mpi"], baseline["MFI_mpi"])

            top = set(df_sc.sort_values("Binding_Intensity", ascending=False).head(top_k)["State"].tolist())
            top_overlap = len(top.intersection(base_top))

            quad = df_sc.set_index("State")["Quadrant"]
            quad_changes = int((quad != base_quadrant).sum())

            summary_rows.append({
                "Scenario": name,
                "Spearman(GPI vs baseline)": round(gpi_s, 4) if pd.notna(gpi_s) else np.nan,
                "Spearman(MFI vs baseline)": round(mfi_s, 4) if pd.notna(mfi_s) else np.nan,
                f"Top{top_k} BI overlap (count)": top_overlap,
                "Quadrant changes (count)": quad_changes,
                "Key parameter change": ", ".join([f"{k}={changes[k]}" for k in changes]) if changes else "(none)",
            })

            detail = df_sc[[
                "State","GPI_weighted","MFI_mpi","Binding_Intensity","Quadrant",
                "MFI_bottleneck_component","MFI_bottleneck"
            ]].copy()
            detail["GPI_rank"] = detail["GPI_weighted"].rank(ascending=False, method="min")
            detail["MFI_rank"] = detail["MFI_mpi"].rank(ascending=False, method="min")
            detail["BI_rank"]  = detail["Binding_Intensity"].rank(ascending=False, method="min")
            detail = detail.sort_values("BI_rank")
            detail_frames[name] = detail

        finally:
            restore_globals(saved)
            for k, v in baseline_globals.items():
                globals()[k] = v

    summary = pd.DataFrame(summary_rows)

    used: set = set()

    def safe_sheet_name(raw: str) -> str:
        base = re.sub(r"[^0-9A-Za-z]+", "_", str(raw)).strip("_") or "Sheet"
        base = base[:31]
        cand = base
        k = 2
        while cand in used or cand in {"Summary", "Baseline"}:
            suffix = f"_{k}"
            cand = (base[: max(0, 31 - len(suffix))] + suffix) or f"Sheet_{k}"
            k += 1
        used.add(cand)
        return cand

    with pd.ExcelWriter(output_xlsx, engine="openpyxl") as writer:
        summary.to_excel(writer, sheet_name="Summary", index=False)
        detail_frames["Baseline"].to_excel(writer, sheet_name="Baseline", index=False)

        for name, df_det in detail_frames.items():
            if name == "Baseline":
                continue
            sheet = safe_sheet_name(name)
            df_det.to_excel(writer, sheet_name=sheet, index=False)

    return output_xlsx

# =============================================================================
# MAIN
# =============================================================================

def main() -> None:
    args = {a.strip().lower() for a in sys.argv[1:]}

    sensitivity_only = bool({"--sensitivity", "-s"} & args)
    skip_sensitivity = bool({"--skip-sensitivity", "-x"} & args)

    skip_pri = "--skip-pri" in args
    force_evv = "--build-evv-map" in args

    if not skip_pri:
        _ensure_evv_map(force=force_evv)

    if sensitivity_only and not skip_sensitivity:
        out = run_sensitivity_tests()
        print(f"Saved sensitivity workbook to: {os.path.abspath(out)}")
        print("\n--- COMPLETE (SENSITIVITY) ---")
        return

    df = build_master()
    if df is None:
        _die("build_master() returned None. This indicates an upstream construction error.")

    generate_outputs(df, skip_pri=skip_pri)

    if not skip_sensitivity:
        out = run_sensitivity_tests()
        print(f"Saved sensitivity workbook to: {os.path.abspath(out)}")

    print("\n--- COMPLETE ---")

if __name__ == "__main__":
    main()
