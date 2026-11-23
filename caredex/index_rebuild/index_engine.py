"""CareDex index engine: GPI v6 / MFI v5 / quadrants / sensitivity.
Same formulas as SYPA_Complete_Pipeline.py (compute_gpi, compute_mfi, compute_quadrants);
reproduces SYPA_GPI_MFI_v5.csv exactly when given that run's inputs. Inputs come from one CSV, every column sourced."""
import numpy as np, pandas as pd
EPS = 1e-9
HPAS_MULT = {0: 0.10, 1: 0.55, 2: 1.00}
def lr(a, b): return np.log((a / b.clip(lower=EPS)).clip(lower=EPS))
def logit(p): p = p.clip(EPS, 1 - EPS); return np.log(p / (1 - p))
def mm(s, f=0.01, c=1.0):
    return ((s - s.min()) / (s.max() - s.min())).clip(f, c)
def n100(s):
    s = s.fillna(s.median()); return 100 + (s - s.mean()) / s.std(ddof=1) * 10
def mpi(df):
    M = df.mean(axis=1); S = df.std(axis=1, ddof=1); return M + S ** 2 / M.clip(lower=EPS)

def compute(I):
    d = I.copy()
    c1 = mm(-logit(d.HCBS_Users_Share)); c2 = mm(-logit(d.HCBS_Exp_Share)); c3 = mm(-logit(d.ADRC_Share))
    d['GPI_c_rebal'] = (c1 * c2).clip(lower=EPS ** 2) ** 0.5
    d['GPI_c3'] = c3
    d['GPI_hpas_mult'] = d.HPAS.map(HPAS_MULT)
    d['GPI'] = (d.GPI_c_rebal * c3).clip(lower=EPS ** 2) ** 0.5 * d.GPI_hpas_mult
    c4 = mm(d.HPAS.astype(float))
    d['GPI_legacy'] = (c1 * c2 * c3 * c4) ** 0.25
    cost = lr(d.Cost_Hourly * 30 * 52, d.Income_65plus)
    gap = lr(d.Wage_Living, d.Wage_Aide)
    ls = lr(pd.Series(1.0, index=d.index), ((d.Aide_Count / d.Pop_65plus.clip(lower=1)) * 1000).clip(lower=EPS))
    wg = n100(gap); l = n100(ls)
    ws = n100(((wg - wg.min() + 1) * (l - l.min() + 1)).clip(lower=EPS) ** 0.5)
    af = n100(cost)
    d['MFI_MF2_wage'] = ws; d['MFI_MF2_afford'] = af
    d['MFI_MF2'] = n100((((ws - ws.min() + 1) * (af - af.min() + 1)).clip(lower=EPS)) ** 0.5)
    d['Wage_Compression_Ratio'] = (d.Wage_P10 / d.Wage_Median_for_P10).clip(0.01, 1.0)
    d['Training_Floor_Gap'] = ((120 - d.Training_Hours).clip(lower=0) / 120).round(4)
    wc = n100(1 - d.Wage_Compression_Ratio.clip(0.01, 1)); tg = n100(d.Training_Floor_Gap.clip(0, 1))
    d['MFI_MF1'] = mpi(pd.DataFrame({'a': wc, 'b': tg}))
    d['MFI'] = 0.6 * d.MFI_MF2 + 0.4 * d.MFI_MF1
    allc = pd.DataFrame({'WageGap': wg, 'LaborScar': l, 'CostBurden': af, 'WageComp': wc, 'TrainGap': tg})
    d['MFI_bottleneck'] = allc.idxmax(axis=1)
    d['MFI_legacy'] = mpi(pd.DataFrame({'a': n100(cost), 'b': wg, 'c': l, 'd': wc, 'e': tg}))
    d['Quadrant'] = quad(d.GPI, d.MFI)
    # sensitivity: 2 GPI x 4 MFI variants, each split at its own median
    G = {'h': d.GPI, 'l': d.GPI_legacy}
    Mv = {'h': d.MFI, '55': 0.5 * d.MFI_MF2 + 0.5 * d.MFI_MF1, '73': 0.7 * d.MFI_MF2 + 0.3 * d.MFI_MF1, 'l': d.MFI_legacy}
    holds = pd.Series(0, index=d.index)
    for g in G.values():
        for m in Mv.values():
            holds += (quad(g, m) == d.Quadrant).astype(int)
    d['QuadrantHolds'] = holds
    gr = pd.DataFrame({k: v.rank(ascending=False, method='min') for k, v in G.items()})
    mr = pd.DataFrame({k: v.rank(ascending=False, method='min') for k, v in Mv.items()})
    d['GPI_rank_min'] = gr.min(axis=1).astype(int); d['GPI_rank_max'] = gr.max(axis=1).astype(int)
    d['MFI_rank_min'] = mr.min(axis=1).astype(int); d['MFI_rank_max'] = mr.max(axis=1).astype(int)
    return d

def quad(g, m):
    gc, mc = g.median(), m.median()
    return pd.Series(np.where((g >= gc) & (m >= mc), 'Double Bind', np.where(g >= gc, 'Policy Bottleneck',
                     np.where(m >= mc, 'Market Failure', 'High Performance'))), index=g.index)
