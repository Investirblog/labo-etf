"""
engine.py — moteur de backtest mensuel commun à toutes les stratégies.

Principe : à la fin de chaque mois t, la stratégie reçoit l'historique des
rendements jusqu'à t inclus et renvoie les poids cibles pour le mois t+1.
Le moteur applique ces poids, laisse dériver le portefeuille entre deux
rebalancements, déduit les frais de transaction et enregistre tout.

Une stratégie est un objet avec :
  id, name        identifiant court et nom affiché
  assets          liste des tickers utilisés (hors cash)
  lookback        nombre de mois d'historique nécessaires avant le 1er signal
  asset_lookback  {ticker: mois} : durée propre à certains actifs (sinon `lookback`)
  rebalance       "monthly", "quarterly" ou "annual" (fin décembre)
  weights(hist)   -> dict {ticker: poids}, somme = 1 ; "CASH" autorisé
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

CASH = "CASH"
CASH_CHAIN = ["BIL", "TBILL", "SHV", "SHY"]  # ETF T-bills, puis taux FRED avant 2007 (SHV/SHY en secours)


def load_returns(path: str | Path) -> pd.DataFrame:
    df = pd.read_csv(path, index_col=0)
    df.index = pd.PeriodIndex(df.index, freq="M")
    return df.sort_index()


def cash_series(returns: pd.DataFrame) -> pd.Series:
    """Rendement du cash : BIL, complété par les T-bills FRED (TBILL) avant son lancement."""
    s = pd.Series(np.nan, index=returns.index)
    for tk in CASH_CHAIN:
        if tk in returns:
            s = s.combine_first(returns[tk])
    return s.rename(CASH)


@dataclass
class Strategy:
    id: str
    name: str
    assets: list[str]
    weights: Callable[[pd.DataFrame], dict]
    lookback: int = 0
    rebalance: str = "monthly"
    family: str = ""
    meta: dict = field(default_factory=dict)
    uses_cash: bool = False     # True si la stratégie détient ou compare au cash (CASH)
    asset_lookback: dict = field(default_factory=dict)  # {ticker: mois} si un actif demande plus ou moins d'historique

    def is_rebalance_month(self, t: pd.Period) -> bool:
        return (self.rebalance == "monthly"
                or (self.rebalance == "quarterly" and t.month in (3, 6, 9, 12))
                or (self.rebalance == "annual" and t.month == 12))


@dataclass
class Result:
    strategy: Strategy
    returns: pd.Series          # rendement mensuel net de frais, indexé par le mois de détention
    weights: pd.DataFrame       # poids en début de mois (après rebalancement)
    turnover: pd.Series         # rotation au rebalancement (somme des |Δpoids|)
    costs: pd.Series            # frais déduits

    @property
    def equity(self) -> pd.Series:
        return (1 + self.returns).cumprod()


def first_decision_month(strategy: Strategy, returns: pd.DataFrame) -> pd.Period:
    """Premier mois t où la stratégie dispose de `lookback` mois pour tous ses actifs
    et où tous ses actifs ont un rendement au mois t+1."""
    has = returns[strategy.assets].notna()
    if strategy.uses_cash:
        has[CASH] = cash_series(returns).notna()
    ok = has.all(axis=1).shift(-1, fill_value=False)        # tout est disponible le mois suivant
    for col in has.columns:
        L = max(strategy.asset_lookback.get(col, strategy.lookback), 0)
        if L:
            ok &= has[col].rolling(L, min_periods=L).sum().eq(L)
    if not ok.any():
        raise ValueError(f"{strategy.id} : pas assez de données")
    return ok[ok].index[0]


def run(strategy: Strategy, returns: pd.DataFrame, start: str | None = None,
        end: str | None = None, cost: float = 0.0) -> Result:
    """cost = frais par unité échangée (0.001 = 0,10 % du montant acheté ou vendu)."""
    data = returns[[c for c in strategy.assets if c in returns]].copy()
    missing = set(strategy.assets) - set(data.columns)
    if missing:
        raise KeyError(f"{strategy.id} : actifs absents des données : {sorted(missing)}")
    data[CASH] = cash_series(returns)

    t0 = first_decision_month(strategy, returns)
    if start is not None:
        t0 = max(t0, pd.Period(start, "M") - 1)   # start = 1er mois de détention
    last = data.index[-1] if end is None else pd.Period(end, "M")
    cols = strategy.assets + [CASH]

    held = pd.Series(0.0, index=cols)
    out_r, out_w, out_to, out_c = {}, {}, {}, {}
    t = t0
    first = True
    while t < last:
        nxt = t + 1
        hist = data.loc[:t, strategy.assets + [CASH]]   # CASH disponible pour les comparaisons
        if first or strategy.is_rebalance_month(t):
            target = pd.Series(strategy.weights(hist), dtype=float).reindex(cols, fill_value=0.0)
            if abs(target.sum() - 1) > 1e-6 or (target < -1e-9).any():
                raise ValueError(f"{strategy.id} {t} : poids invalides {target.to_dict()}")
            turnover = 0.0 if first else float((target - held).abs().sum())
            held = target
            first = False
        else:
            turnover = 0.0
        r = data.loc[nxt, cols].fillna(0.0)
        if held[r.index[data.loc[nxt, cols].isna()]].abs().sum() > 1e-9:
            raise ValueError(f"{strategy.id} {nxt} : poids sur un actif sans donnée")
        gross = float((held * r).sum())
        c = cost * turnover
        out_r[nxt], out_w[nxt], out_to[nxt], out_c[nxt] = gross - c, held.copy(), turnover, c
        # dérive des poids pendant le mois
        held = held * (1 + r) / (1 + gross) if gross > -1 else held
        t = nxt

    idx = pd.PeriodIndex(list(out_r), freq="M")
    return Result(strategy,
                  pd.Series(list(out_r.values()), index=idx, name=strategy.id),
                  pd.DataFrame(list(out_w.values()), index=idx),
                  pd.Series(list(out_to.values()), index=idx),
                  pd.Series(list(out_c.values()), index=idx))
