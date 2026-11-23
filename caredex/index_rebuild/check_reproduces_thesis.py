"""Feeds the thesis run's own inputs (results/offline_rerun_2026-11-23/SYPA_Full_v5.csv) through index_engine.py
and checks that GPI, MFI, components and quadrants match the thesis code's output."""
import os, sys
import pandas as pd
HERE = os.path.dirname(os.path.abspath(__file__)); ROOT = os.path.dirname(os.path.dirname(HERE))
sys.path.insert(0, HERE)
from index_engine import compute
F = pd.read_csv(os.path.join(ROOT, 'results/offline_rerun_2026-11-23/SYPA_Full_v5.csv'))
I = F[['State','state_code','HCBS_Users_Share','HCBS_Exp_Share','HPAS','Cost_Hourly','Income_65plus','Wage_Aide','Wage_Living','Aide_Count','Pop_65plus']].copy()
I['ADRC_Share'] = F.Access_Velocity_Share
I['Wage_P10'] = F.Wage_Compression_Ratio; I['Wage_Median_for_P10'] = 1.0
I['Training_Hours'] = 120 - F.Training_Floor_Gap * 120
r = compute(I)
G = pd.read_csv(os.path.join(ROOT, 'results/offline_rerun_2026-11-23/SYPA_GPI_MFI_v5.csv'))
worst = max(float((r[a] - G[b]).abs().max()) for a, b in [('GPI','GPI_v6'),('GPI_legacy','GPI_v4_legacy'),('MFI','MFI_v5'),('MFI_MF1','MFI_MF1'),('MFI_MF2','MFI_MF2'),
            ('MFI_MF2_wage','MFI_MF2_wage'),('MFI_MF2_afford','MFI_MF2_afford'),('MFI_legacy','MFI_v4_legacy'),('GPI_c_rebal','GPI_c_rebal'),('GPI_c3','GPI_c3')])
same_q = int((r.Quadrant == G.Quadrant).sum())
print(f'largest difference {worst:.1e}; quadrants equal {same_q}/51')
assert worst < 1e-9 and same_q == 51
