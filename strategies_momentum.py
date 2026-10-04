"""
strategies_momentum.py — stratégies de momentum et de tendance.

Convention commune : le signal est calculé sur les rendements totaux
(dividendes réinvestis) jusqu'à la fin du mois t inclus, et la position est
détenue pendant le mois t+1. Rebalancement mensuel.
"""
from __future__ import annotations

import numpy as np
import pandas as pd

from engine import CASH, Strategy


# --------------------------------------------------------------------------
# Outils
# --------------------------------------------------------------------------
def trailing(hist: pd.DataFrame, n: int) -> pd.Series:
    """Rendement total sur les n derniers mois (jusqu'à t inclus)."""
    return (1 + hist.iloc[-n:]).prod() - 1


def tr_index(hist: pd.DataFrame) -> pd.DataFrame:
    """Indice de rendement total reconstruit à partir des rendements mensuels."""
    return (1 + hist.fillna(0)).cumprod()


def above_sma(hist: pd.DataFrame, months: int) -> pd.Series:
    """True si la valeur de fin de mois dépasse sa moyenne mobile sur `months` mois."""
    idx = tr_index(hist)
    return idx.iloc[-1] > idx.iloc[-months:].mean()


# --------------------------------------------------------------------------
# 1. Global Equities Momentum (Antonacci, « Dual Momentum Investing », 2014)
# --------------------------------------------------------------------------
def gem(us="SPY", intl="EFA", bonds="AGG", tbill=CASH, lookback=12):
    def w(hist):
        r = trailing(hist, lookback)
        if r[us] > r[tbill]:                       # momentum absolu : actions > T-bills
            return {us if r[us] >= r[intl] else intl: 1.0}  # momentum relatif US/intl
        return {bonds: 1.0}
    return w


# --------------------------------------------------------------------------
# 2. Accelerating Dual Momentum (EngineeredPortfolio, 2018)
# --------------------------------------------------------------------------
def adm(us="SPY", intl="SCZ", bonds="TLT"):
    def w(hist):
        score = (trailing(hist, 1) + trailing(hist, 3) + trailing(hist, 6)) / 3
        best = us if score[us] >= score[intl] else intl
        return {best: 1.0} if score[best] > 0 else {bonds: 1.0}
    return w


def adm_tip(us="SPY", intl="SCZ", bonds=("TLT", "TIP")):
    """Variante répandue (Allocate Smartly…) : en défensif, l'obligation au meilleur mois."""
    def w(hist):
        score = (trailing(hist, 1) + trailing(hist, 3) + trailing(hist, 6)) / 3
        best = us if score[us] >= score[intl] else intl
        if score[best] > 0:
            return {best: 1.0}
        r1 = trailing(hist, 1)
        return {max(bonds, key=lambda b: r1[b]): 1.0}
    return w


# --------------------------------------------------------------------------
# 3. GTAA 5 / Ivy Portfolio avec timing (Faber, 2007 ; Faber & Richardson, 2009)
# --------------------------------------------------------------------------
def sma_timing(assets, weights=None, months=10):
    weights = weights or {a: 1 / len(assets) for a in assets}

    def w(hist):
        up = above_sma(hist[assets], months)
        out = {a: weights[a] for a in assets if up[a]}
        rest = 1 - sum(out.values())
        if rest > 1e-12:
            out[CASH] = rest
        return out
    return w


MOMENTUM = [
    Strategy(
        id="gem", name="Global Equities Momentum (GEM)",
        assets=["SPY", "EFA", "AGG"], weights=gem(), lookback=12,
        family="Momentum", uses_cash=True,
        meta={"published": "2014-11", "author": "Gary Antonacci (2014)",
              "note": "Actions US ou internationales si elles battent les T-bills sur 12 mois, sinon obligations",
              "rules": ["Fin de mois : rendement total sur 12 mois de SPY, EFA et des T-bills (BIL).",
                        "Si SPY bat les T-bills : investir 100 % dans le meilleur de SPY et EFA.",
                        "Sinon : 100 % AGG (obligations agrégées US)."],
              "variant_note": "Antonacci utilise l'indice MSCI ACWI ex-US ; EFA (2001) remplace ACWX (2008) pour inclure la crise de 2008."}),
    Strategy(
        id="adm", name="Accelerating Dual Momentum",
        assets=["SPY", "SCZ", "TLT"], weights=adm(), lookback=6,
        family="Momentum",
        meta={"published": "2018-05", "author": "EngineeredPortfolio (2018)",
              "note": "Momentum court (1-3-6 mois) entre actions US et petites capitalisations internationales",
              "rules": ["Fin de mois : score = moyenne des rendements sur 1, 3 et 6 mois de SPY et SCZ.",
                        "Investir 100 % dans l'actif au meilleur score si ce score est positif.",
                        "Sinon : 100 % TLT (obligations d'État longues)."]}),
    Strategy(
        id="adm_tip", name="Accelerating Dual Momentum (variante TLT/TIP)",
        assets=["SPY", "SCZ", "TLT", "TIP"], weights=adm_tip(), lookback=6,
        family="Momentum",
        meta={"published": "2018-05", "author": "EngineeredPortfolio (2018), variante Allocate Smartly",
              "note": "Comme ADM, mais la poche défensive choisit entre TLT et TIP",
              "rules": ["Mêmes règles qu'[ADM](strategie:adm) pour la partie actions.",
                        "En défensif : TLT ou TIP, celui qui a le meilleur rendement sur 1 mois."],
              "variant_note": "Règle ajoutée après la publication originale : elle améliore nettement 2022, "
                              "ce qui illustre le risque de sur-optimisation a posteriori."}),
    Strategy(
        id="adm_cash", name="Accelerating Dual Momentum (variante cash)",
        assets=["SPY", "SCZ"], weights=adm(bonds=CASH), lookback=6,
        family="Momentum", uses_cash=True,
        meta={"published": "2026-09", "author": "Variante testée par Labo ETF (2026)",
              "note": "Comme ADM, mais la poche défensive est du cash plutôt que des obligations",
              "rules": ["Mêmes règles qu'[ADM](strategie:adm) pour la partie actions.",
                        "En défensif : 100 % en cash (T-bills en dollars ; compte épargne au taux de dépôt de la BCE dans la vue en euros)."],
              "variant_note": "Variante testée par ce site, pas par l'auteur d'ADM, pour un investisseur qui préfère éviter "
                              "les fonds obligataires. Tout son historique est antérieur à sa création."}),
    Strategy(
        id="gtaa5", name="GTAA 5 / Ivy Portfolio avec timing",
        assets=["SPY", "EFA", "IEF", "VNQ", "GSG"],
        weights=sma_timing(["SPY", "EFA", "IEF", "VNQ", "GSG"]), lookback=10,
        family="Tendance", uses_cash=True,
        meta={"published": "2007-01", "author": "Mebane Faber (2007), Faber & Richardson (2009)",
              "note": "5 classes à 20 % ; chacune passe en cash sous sa moyenne mobile 10 mois",
              "rules": ["Fin de mois : pour chaque actif, comparer la valeur à sa moyenne des 10 derniers mois.",
                        "Au-dessus : garder sa part de 20 %. En dessous : cette part va en cash (T-bills)."]}),
    Strategy(
        id="spy_sma10", name="S&P 500 avec timing (moyenne 10 mois)",
        assets=["SPY"], weights=sma_timing(["SPY"]), lookback=10,
        family="Tendance", uses_cash=True,
        meta={"published": "2007-01", "author": "Mebane Faber (2007)",
              "note": "Actions US au-dessus de la moyenne mobile 10 mois, cash en dessous",
              "rules": ["Fin de mois : si SPY dépasse sa moyenne des 10 derniers mois, 100 % SPY.",
                        "Sinon : 100 % cash (T-bills)."]}),
]
