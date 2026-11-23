"""Rebuild GPI, MFI, quadrants and the 8-variant sensitivity from index_inputs_2026-11-23.csv.
Usage (from the repository root): python caredex/index_rebuild/run_rebuild.py"""
import os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from index_engine import compute
I = pd.read_csv(os.path.join(HERE, 'index_inputs_2026-11-23.csv'))
R = compute(I)
old = pd.read_csv(os.path.join(ROOT, 'results/offline_rerun_2026-11-23/SYPA_GPI_MFI_v5.csv'))
R['Quadrant_old'] = R.state_code.map(dict(zip(old.state_code, old.Quadrant)))
cols = ['State','state_code','HPAS','GPI','MFI','Quadrant','GPI_c_rebal','GPI_c3','GPI_hpas_mult','MFI_MF2_wage','MFI_MF2_afford','MFI_MF2','MFI_MF1','MFI_bottleneck',
        'Wage_Compression_Ratio','Training_Floor_Gap','GPI_legacy','MFI_legacy','QuadrantHolds','GPI_rank_min','GPI_rank_max','MFI_rank_min','MFI_rank_max','Quadrant_old']
out = os.path.join(ROOT, 'results/index_rebuild_2026-11-23/index_results_2026-11-23.csv')
R[cols].to_csv(out, index=False)
print(R.Quadrant.value_counts().to_dict(), '| quadrant changes vs thesis:', int((R.Quadrant != R.Quadrant_old).sum()))
