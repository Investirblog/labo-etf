"""metrics.py — statistiques de performance à partir de rendements mensuels."""
from __future__ import annotations

import numpy as np
import pandas as pd


def _cagr(r: pd.Series) -> float:
    return float((1 + r).prod() ** (12 / len(r)) - 1) if len(r) else np.nan


def drawdown(r: pd.Series) -> pd.Series:
    """Baisse depuis le plus haut. Le capital de départ (1) compte comme premier sommet :
    une stratégie qui perd dès son premier mois est bien sous l'eau."""
    eq = (1 + r).cumprod()
    return eq / eq.cummax().clip(lower=1.0) - 1


def underwater(r: pd.Series) -> tuple[int, str | None, str | None, bool]:
    """Plus longue période sous un sommet précédent : (mois, début, fin, toujours en cours).
    Le capital de départ (1) compte comme premier sommet."""
    eq = (1 + r).cumprod().to_numpy()
    idx = list(r.index)
    peak, best, start, cur_start = 1.0, (0, None, None, False), None, None
    run = 0
    for k, v in enumerate(eq):
        if v >= peak - 1e-12:
            if run > best[0]:
                best = (run, str(idx[cur_start]), str(idx[k]), False)
            peak, run, cur_start = v, 0, None
        else:
            if cur_start is None:
                cur_start = k
            run += 1
    if run > best[0]:
        best = (run, str(idx[cur_start]), None, True)
    return best


def rolling_cagr(r: pd.Series, years: int) -> pd.Series:
    n = 12 * years
    return (1 + r).rolling(n).apply(np.prod, raw=True).pow(1 / years).sub(1).dropna()


def stats(r: pd.Series, rf: pd.Series) -> dict:
    """r : rendements mensuels ; rf : rendement mensuel du cash sur la même période."""
    r = r.dropna()
    rf = rf.reindex(r.index).fillna(0.0)
    ex = r - rf
    dd = drawdown(r)
    trough = dd.idxmin()
    eq_to_trough = (1 + r).cumprod().loc[:trough]
    # sommet : le capital de départ (mois précédant le début) s'il n'a jamais été dépassé
    peak = eq_to_trough.idxmax() if eq_to_trough.max() >= 1.0 else r.index[0] - 1
    after = dd.loc[trough:]
    recovered = after[after >= 0]
    downside = np.sqrt((np.minimum(ex, 0) ** 2).mean()) * np.sqrt(12)
    yearly = (1 + r).groupby(r.index.year).prod() - 1
    full_years = r.groupby(r.index.year).size().eq(12)
    yearly = yearly[full_years]
    out = {
        "start": str(r.index[0]), "end": str(r.index[-1]), "months": int(len(r)),
        "cagr": _cagr(r),
        "vol": float(r.std() * np.sqrt(12)),
        "sharpe": float(ex.mean() / ex.std() * np.sqrt(12)) if ex.std() > 0 else np.nan,
        "sortino": float(ex.mean() * 12 / downside) if downside > 0 else np.nan,
        "max_dd": float(dd.min()),
        "max_dd_peak": str(peak), "max_dd_trough": str(trough),
        "max_dd_recovery": str(recovered.index[0]) if len(recovered) else None,
        "ulcer": float(np.sqrt((dd ** 2).mean())),
        "best_year": float(yearly.max()) if len(yearly) else np.nan,
        "worst_year": float(yearly.min()) if len(yearly) else np.nan,
        "pct_pos_months": float((r > 0).mean()),
    }
    uw = underwater(r)
    out["underwater_months"], out["underwater_start"], out["underwater_end"], out["underwater_ongoing"] = uw
    out["calmar"] = out["cagr"] / abs(out["max_dd"]) if out["max_dd"] < 0 else np.nan
    # UPI (Ulcer Performance Index, Peter Martin) : rendement au-delà du cash, divisé par l'ulcer index.
    # Un « Sharpe » qui ne pénalise que les baisses, d'autant plus qu'elles sont profondes et longues.
    out["upi"] = (out["cagr"] - _cagr(rf)) / out["ulcer"] if out["ulcer"] > 0 else np.nan
    for y in (5, 10):
        rc = rolling_cagr(r, y)
        out[f"roll{y}_min"] = float(rc.min()) if len(rc) else np.nan
        out[f"roll{y}_median"] = float(rc.median()) if len(rc) else np.nan
    return out
