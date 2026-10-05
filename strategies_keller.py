"""
strategies_keller.py — la famille de Wouter Keller (et coauteurs).

Point commun : un momentum rapide (13612W) ou une moyenne mobile 12 mois,
et souvent un « univers canari » qui décide seul du passage en défensif.
Signal fin de mois t, détention pendant t+1, rebalancement mensuel.
"""
from __future__ import annotations

import pandas as pd

from functools import lru_cache
from pathlib import Path

from engine import CASH, Strategy
from strategies_momentum import tr_index, trailing

# ETF utilisés par Keller qui n'existaient pas encore, remplacés par l'équivalent le plus ancien :
#   PDBC -> DBC (même indice de matières premières)


# --------------------------------------------------------------------------
# Mesures de momentum
# --------------------------------------------------------------------------
def mom_13612w(hist: pd.DataFrame) -> pd.Series:
    """12×r1 + 4×r3 + 2×r6 + r12 : le dernier mois pèse 40 % du score."""
    return (12 * trailing(hist, 1) + 4 * trailing(hist, 3)
            + 2 * trailing(hist, 6) + trailing(hist, 12))


def mom_13612u(hist: pd.DataFrame) -> pd.Series:
    """Moyenne simple des rendements sur 1, 3, 6 et 12 mois."""
    return (trailing(hist, 1) + trailing(hist, 3) + trailing(hist, 6) + trailing(hist, 12)) / 4


def mom_sma12(hist: pd.DataFrame) -> pd.Series:
    """Valeur actuelle / moyenne des 13 dernières fins de mois − 1."""
    idx = tr_index(hist)
    return idx.iloc[-1] / idx.iloc[-13:].mean() - 1


def top(scores: pd.Series, n: int) -> list[str]:
    return list(scores.sort_values(ascending=False).index[:n])


def add(w: dict, k: str, v: float) -> None:
    if v > 0:
        w[k] = w.get(k, 0.0) + v


# --------------------------------------------------------------------------
# VAA-G4 — Vigilant Asset Allocation (Keller & Keuning, 2017)
# --------------------------------------------------------------------------
VAA_OFF, VAA_DEF = ["SPY", "EFA", "EEM", "AGG"], ["LQD", "IEF", "SHY"]


def vaa(hist):
    m = mom_13612w(hist)
    if (m[VAA_OFF] > 0).all():
        return {top(m[VAA_OFF], 1)[0]: 1.0}
    return {top(m[VAA_DEF], 1)[0]: 1.0}


# --------------------------------------------------------------------------
# DAA-G12 — Defensive Asset Allocation (Keller & Keuning, 2018)
# --------------------------------------------------------------------------
DAA_RISKY = ["SPY", "IWM", "QQQ", "VGK", "EWJ", "VWO", "VNQ", "GSG", "GLD", "TLT", "HYG", "LQD"]
DAA_CASH = ["SHY", "IEF", "LQD"]
DAA_CANARY = ["VWO", "BND"]


def daa(hist, T=6, B=2):
    m = mom_13612w(hist)
    bad = int((m[DAA_CANARY] <= 0).sum())
    cf = min(1.0, bad / B)                      # part défensive : 0, 50 % ou 100 %
    w: dict = {}
    for a in top(m[DAA_RISKY], T):
        add(w, a, (1 - cf) / T)
    add(w, top(m[DAA_CASH], 1)[0], cf)
    return w


# --------------------------------------------------------------------------
# PAA — Protective Asset Allocation (Keller & Keuning, 2016), version PAA2
# --------------------------------------------------------------------------
PAA_RISKY = ["SPY", "QQQ", "IWM", "VGK", "EWJ", "EEM", "VNQ", "DBC", "GLD", "HYG", "LQD", "TLT"]
PAA_SAFE = "IEF"


def paa(hist, a=2, T=6):
    m = mom_sma12(hist[PAA_RISKY])
    N = len(PAA_RISKY)
    n = int((m > 0).sum())
    n1 = a * N / 4                              # PAA2 : 6 actifs sur 12
    bf = min(1.0, (N - n) / (N - n1))           # part obligataire (« bond fraction »)
    w: dict = {}
    for x in top(m, T):
        add(w, x, (1 - bf) / T)
    add(w, PAA_SAFE, bf)
    return w


# --------------------------------------------------------------------------
# HAA — Hybrid Asset Allocation (Keller & Keizer, 2023)
# --------------------------------------------------------------------------
HAA_OFF = ["SPY", "IWM", "EFA", "EEM", "VNQ", "DBC", "IEF", "TLT"]
HAA_DEF = ["IEF", "BIL"]
HAA_CANARY = "TIP"


def haa(hist, T=4):
    m = mom_13612u(hist)
    safe = top(m[HAA_DEF], 1)[0]
    if m[HAA_CANARY] <= 0:
        return {safe: 1.0}
    w: dict = {}
    for a in top(m[HAA_OFF], T):
        add(w, a if m[a] > 0 else safe, 1 / T)  # momentum absolu actif par actif
    return w


# --------------------------------------------------------------------------
# BAA — Bold Asset Allocation (Keller, 2022), version équilibrée G12
# --------------------------------------------------------------------------
BAA_CANARY = ["SPY", "EFA", "EEM", "AGG"]
BAA_OFF = ["SPY", "QQQ", "IWM", "VGK", "EWJ", "EEM", "VNQ", "DBC", "GLD", "TLT", "HYG", "LQD"]
BAA_DEF = ["TIP", "DBC", "BIL", "IEF", "TLT", "LQD", "AGG"]


def baa(hist, T_off=6, T_def=3):
    if (mom_13612w(hist[BAA_CANARY]) > 0).all():
        rel = mom_sma12(hist[BAA_OFF])
        return {a: 1 / T_off for a in top(rel, T_off)}
    rel = mom_sma12(hist[BAA_DEF])
    w: dict = {}
    for a in top(rel, T_def):
        add(w, a if rel[a] >= rel["BIL"] else "BIL", 1 / T_def)
    return w


# --------------------------------------------------------------------------
# GPM — Generalized Protective Momentum (Keuning & Keller, 2016)
# --------------------------------------------------------------------------
GPM_RISKY = ["SPY", "QQQ", "IWM", "VGK", "EWJ", "EEM", "VNQ", "DBC", "GLD", "HYG", "LQD", "TLT"]
GPM_CP = ["IEF", "SHY"]


def gpm(hist):
    r = mom_13612u(hist)
    rets = hist[GPM_RISKY].iloc[-12:]
    ew = rets.mean(axis=1)                                   # indice équipondéré des 12 actifs
    corr = rets.apply(lambda c: c.corr(ew))
    z = r[GPM_RISKY] * (1 - corr)
    n = int((z > 0).sum())
    cp_asset = top(r[GPM_CP], 1)[0]
    cp = 1.0 if n <= 6 else (12 - n) / 6
    w: dict = {}
    add(w, cp_asset, cp)
    for a in top(z, 3):
        add(w, a, (1 - cp) / 3)
    return w


def uniq(*groups):
    out = []
    for g in groups:
        for a in ([g] if isinstance(g, str) else g):
            if a not in out:
                out.append(a)
    return out


# --------------------------------------------------------------------------
# RotationShield (Nathanaël Dumortier, 2026) : la logique de canari de DAA,
# avec le S&P 500 seul en offensive et du cash en défensive. https://rotationshield.be
# --------------------------------------------------------------------------
RS_CANARY = ["VWO", "TIP"]
DAILY = Path(__file__).resolve().parent / "data" / "daily"


@lru_cache(maxsize=1)
def rs_canary_table() -> dict:
    """Nombre de canaris négatifs à chaque fin de mois, comme sur rotationshield.be :
    score 13612W calculé chaque jour (1, 3, 6 et 12 mois = 21, 63, 126 et 252 séances),
    puis moyenné sur les 5 dernières séances du mois. Clé : le mois (Period) de la décision."""
    try:
        px = pd.concat({t: pd.read_csv(DAILY / f"{t}.csv", index_col=0, parse_dates=True).iloc[:, 0]
                        for t in RS_CANARY}, axis=1, sort=True).dropna()
    except FileNotFoundError:
        return {}
    score = sum(k * (px / px.shift(n) - 1) for k, n in ((12, 21), (4, 63), (2, 126), (1, 252)))
    score = score.dropna()
    months = score.index.to_period("M")
    out = {}
    for m, s in score.groupby(months):
        if len(s) >= 5:
            out[m] = int((s.iloc[-5:].mean() <= 0).sum())
    return out


def rotationshield(hist):
    t = hist.index[-1]
    bad = rs_canary_table().get(t)
    if bad is None:  # pas de cours quotidiens : même score sur les fins de mois
        bad = int((mom_13612w(hist[RS_CANARY]) <= 0).sum())
    spy = 1 - min(1.0, bad / 2)
    w: dict = {}
    add(w, "SPY", spy)
    add(w, CASH, 1 - spy)
    return w


KELLER = [
    Strategy(
        id="vaa", name="Vigilant Asset Allocation (VAA-G4)",
        assets=uniq(VAA_OFF, VAA_DEF), weights=vaa, lookback=12, family="Keller",
        meta={"published": "2017-07", "author": "Wouter Keller & Jan Willem Keuning (2017)",
              "note": "Tout en actions ou tout en défensif : il suffit qu'un seul des 4 actifs offensifs faiblisse",
              "rules": ["Fin de mois : momentum 13612W (12×r1 + 4×r3 + 2×r6 + r12) de chaque actif.",
                        "Si SPY, EFA, EEM et AGG ont tous un momentum positif : 100 % dans celui qui a le meilleur score.",
                        "Sinon : 100 % dans le meilleur de LQD, IEF et SHY."]}),
    Strategy(
        id="daa", name="Defensive Asset Allocation (DAA-G12)",
        assets=uniq(DAA_RISKY, DAA_CASH, DAA_CANARY), weights=daa, lookback=12, family="Keller",
        meta={"published": "2018-07", "author": "Wouter Keller & Jan Willem Keuning (2018)", "signal_only": ["BND"],
              "note": "Deux « canaris » (émergents et obligations) décident de la part défensive",
              "rules": ["Fin de mois : momentum 13612W de chaque actif.",
                        "Canaris : VWO et BND. Chaque canari négatif fait passer 50 % du portefeuille en défensif.",
                        "Partie offensive : les 6 meilleurs des 12 actifs risqués, à parts égales.",
                        "Partie défensive : le meilleur de SHY, IEF et LQD."],
              "variant_note": "[RotationShield](strategie:rotationshield) applique la même logique de canari au seul S&P 500, avec VWO et TIP."}),
    Strategy(
        id="rotationshield", name="RotationShield (DAA sur le S&P 500)",
        assets=["SPY"] + RS_CANARY, weights=rotationshield, lookback=12, family="Keller", uses_cash=True,
        meta={"published": "2026-09", "author": "Nathanaël Dumortier (2026), d'après Keller & Keuning", "signal_only": RS_CANARY,
              "note": "Les deux canaris de DAA pilotent un seul actif : le S&P 500, ou du cash",
              "rules": ["Chaque jour : score 13612W (12×r1 + 4×r3 + 2×r6 + r12) des canaris VWO (émergents) et TIP (obligations indexées sur l'inflation).",
                        "Fin de mois : moyenne du score sur les 5 dernières séances ; seul son signe compte.",
                        "0 canari négatif : 100 % S&P 500. 1 canari négatif : 50 % S&P 500, 50 % cash. 2 canaris négatifs : 100 % cash."],
              "variant_note": "Version testée ici avec les ETF américains (SPY, VWO, TIP) et les T-bills. Le site "
                              "[rotationshield.be](https://rotationshield.be) publie le signal du mois avec des équivalents "
                              "européens (SPYL pour le S&P 500, ETF UCITS pour les canaris) et un compte d'épargne en euros : "
                              "son signal peut ponctuellement différer de celui-ci."}),
    Strategy(
        id="paa", name="Protective Asset Allocation (PAA2)",
        assets=uniq(PAA_RISKY, PAA_SAFE), weights=paa, lookback=13, family="Keller",
        meta={"published": "2016-04", "author": "Wouter Keller & Jan Willem Keuning (2016)",
              "note": "La part obligataire grandit à mesure que les actifs risqués passent sous leur moyenne 12 mois",
              "rules": ["Fin de mois : momentum = valeur actuelle / moyenne des 13 dernières fins de mois − 1.",
                        "n = nombre d'actifs positifs parmi les 12. Part en IEF = (12 − n) / 6, plafonnée à 100 %.",
                        "Le reste va aux 6 meilleurs actifs, à parts égales.",
                        "Avec 6 actifs positifs ou moins, tout est en IEF."]}),
    Strategy(
        id="haa", name="Hybrid Asset Allocation (HAA)",
        assets=uniq(HAA_OFF, HAA_DEF, HAA_CANARY), weights=haa, lookback=12, family="Keller",
        meta={"published": "2023-02", "author": "Wouter Keller & JW Keizer (2023)", "signal_only": [HAA_CANARY],
              "note": "Un seul canari, les obligations indexées sur l'inflation (TIP)",
              "rules": ["Fin de mois : momentum = moyenne des rendements sur 1, 3, 6 et 12 mois.",
                        "Si TIP a un momentum négatif : 100 % dans le meilleur de IEF et BIL.",
                        "Sinon : les 4 meilleurs des 8 actifs offensifs à 25 % chacun ; un actif à momentum négatif est remplacé par le meilleur de IEF et BIL."],
              "variant_note": "Keller utilise VEA, VWO et PDBC ; on prend EFA, EEM et DBC (mêmes expositions, plus d'historique)."}),
    Strategy(
        id="baa", name="Bold Asset Allocation (BAA-G12)",
        assets=uniq(BAA_CANARY, BAA_OFF, BAA_DEF), weights=baa, lookback=13, family="Keller",
        meta={"published": "2022-10", "author": "Wouter Keller (2022)", "signal_only": ["EFA"],
              "note": "Offensif seulement si les 4 canaris sont au vert, ce qui arrive environ 40 % du temps",
              "rules": ["Fin de mois : momentum 13612W des canaris SPY, EFA, EEM et AGG.",
                        "Tous positifs : les 6 meilleurs des 12 actifs offensifs, classés sur valeur / moyenne 13 mois, à parts égales.",
                        "Sinon : les 3 meilleurs de TIP, DBC, BIL, IEF, TLT, LQD et AGG ; tout actif moins bon que BIL est remplacé par BIL."],
              "variant_note": "Allocate Smartly signale un risque de sur-optimisation élevé : beaucoup de paramètres pour un historique limité."}),
    Strategy(
        id="gpm", name="Generalized Protective Momentum (GPM)",
        assets=uniq(GPM_RISKY, GPM_CP), weights=gpm, lookback=12, family="Keller",
        meta={"published": "2016-07", "author": "Jan Willem Keuning & Wouter Keller (2016)",
              "note": "Le momentum de chaque actif est pénalisé quand il évolue comme tout le reste",
              "rules": ["Fin de mois : r = moyenne des rendements sur 1, 3, 6 et 12 mois de chacun des 12 actifs.",
                        "c = corrélation sur 12 mois avec l'indice équipondéré des 12 actifs ; score z = r × (1 − c).",
                        "n = nombre d'actifs avec z positif. Si n ≤ 6 : 100 % en protection ; sinon (12 − n) / 6 du portefeuille.",
                        "Protection : IEF ou SHY, celui dont r est le plus élevé. Le reste : les 3 meilleurs scores z, à parts égales."]}),
]
