"""
strategies_other.py — stratégies isolées : rotation sectorielle, Composite
Dual Momentum, Paired Switching et le 90/10 de Warren Buffett.
"""
from __future__ import annotations

from engine import CASH, Strategy
from strategies_momentum import above_sma, trailing
from strategies_static import fixed

SECTORS = ["XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU", "XLV", "XLY"]


# --------------------------------------------------------------------------
# Rotation sectorielle (Faber, « Relative Strength Strategies for Investing », 2010)
# --------------------------------------------------------------------------
def sector_rotation(n=3, lookback=3, trend_filter=False):
    def w(hist):
        if trend_filter and not above_sma(hist[["SPY"]], 10)["SPY"]:
            return {CASH: 1.0}
        r = trailing(hist[SECTORS], lookback)
        return {s: 1 / n for s in r.sort_values(ascending=False).index[:n]}
    return w


# --------------------------------------------------------------------------
# Composite Dual Momentum (Antonacci, « Risk Premia Harvesting Through Dual Momentum », 2012)
# --------------------------------------------------------------------------
CDM_MODULES = [("SPY", "EFA"), ("LQD", "HYG"), ("VNQ", "REM"), ("GLD", "TLT")]


def cdm(hist):
    r = trailing(hist, 12)
    w: dict = {}
    for a, b in CDM_MODULES:
        best = a if r[a] >= r[b] else b
        k = best if r[best] > r["BIL"] else CASH
        w[k] = w.get(k, 0.0) + 0.25
    return w


# --------------------------------------------------------------------------
# Paired Switching (Maewal & Bock, 2011)
# --------------------------------------------------------------------------
def paired_switching(hist):
    r = trailing(hist[["SPY", "TLT"]], 3)
    return {"SPY" if r["SPY"] >= r["TLT"] else "TLT": 1.0}


OTHER = [
    fixed("buffett", "90/10 de Warren Buffett", {"SPY": 90, "SHY": 10},
          published="2014-03", author="Warren Buffett, lettre aux actionnaires (2013)",
          note="Le conseil de Buffett pour l'héritage de son épouse : 90 % S&P 500, 10 % obligations d'État courtes"),
    Strategy(
        id="sector_rot", name="Rotation sectorielle (Faber)",
        assets=SECTORS, weights=sector_rotation(), lookback=3, family="Secteurs",
        meta={"published": "2010-01", "author": "Mebane Faber (2010)",
              "note": "Chaque mois, les 3 secteurs américains les plus forts sur 3 mois",
              "rules": ["Fin de mois : rendement sur 3 mois des 9 secteurs SPDR (XLB à XLY).",
                        "Investir un tiers dans chacun des 3 meilleurs."],
              "variant_note": "Faber teste plusieurs durées (1 à 12 mois) ; on retient les 3 mois de la version décrite par StockCharts."}),
    Strategy(
        id="sector_rot_trend", name="Rotation sectorielle avec filtre de tendance",
        assets=SECTORS + ["SPY"], weights=sector_rotation(trend_filter=True), lookback=3,
        asset_lookback={"SPY": 10}, family="Secteurs", uses_cash=True,
        meta={"published": "2010-01", "author": "Mebane Faber (2010)",
              "note": "La même rotation, mise en cash quand le S&P 500 passe sous sa moyenne 10 mois",
              "rules": ["Si SPY est sous sa moyenne des 10 derniers mois : 100 % cash.",
                        "Sinon : un tiers dans chacun des 3 meilleurs secteurs sur 3 mois."]}),
    Strategy(
        id="cdm", name="Composite Dual Momentum",
        assets=["SPY", "EFA", "LQD", "HYG", "VNQ", "REM", "GLD", "TLT", "BIL"],
        weights=cdm, lookback=12, family="Momentum", uses_cash=True,
        meta={"published": "2012-04", "author": "Gary Antonacci (2012)",
              "note": "Quatre modules à 25 %, chacun avec son propre double momentum",
              "rules": ["Quatre modules de 25 % : actions (SPY/EFA), crédit (LQD/HYG), immobilier (VNQ/REM), stress économique (GLD/TLT).",
                        "Dans chaque module : l'actif au meilleur rendement sur 12 mois.",
                        "S'il fait moins bien que les T-bills sur 12 mois, la part du module va en cash."]}),
    Strategy(
        id="paired_switching", name="Paired Switching",
        assets=["SPY", "TLT"], weights=paired_switching, lookback=3, rebalance="quarterly",
        family="Momentum",
        meta={"published": "2011-01", "author": "Ashok Maewal & Joel Bock (2011)",
              "note": "Actions ou obligations longues, selon le meilleur des deux sur le trimestre écoulé",
              "rules": ["Fin de trimestre : rendement sur 3 mois de SPY et TLT.",
                        "Investir 100 % dans le meilleur des deux pour le trimestre suivant."]}),
]
