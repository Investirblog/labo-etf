"""
strategies_static.py — portefeuilles à pondération fixe (« lazy portfolios »).

Rebalancement annuel (fin décembre) par défaut, comme la plupart des
références publiées. Chaque ETF est l'équivalent le plus ancien disponible
de la classe d'actifs décrite par l'auteur.
"""
from engine import Strategy


def fixed(id, name, alloc, rebalance="annual", family="Statique", **meta):
    alloc = {k: v / 100 for k, v in alloc.items()}
    assert abs(sum(alloc.values()) - 1) < 1e-9, id
    return Strategy(id=id, name=name, assets=[k for k in alloc if k != "CASH"],
                    weights=lambda hist, a=alloc: dict(a), rebalance=rebalance,
                    family=family, meta=meta)


STATIC = [
    fixed("acwi", "Actions mondiales (référence)", {"ACWI": 100}, rebalance="monthly", family="Référence",
          author="—", note="Référence principale : 100 % actions mondiales, pays développés et émergents"),
    fixed("spy", "S&P 500 (référence)", {"SPY": 100}, rebalance="monthly", family="Référence",
          author="—", note="Seconde référence : 100 % actions américaines"),
    fixed("6040", "60/40 classique", {"SPY": 60, "AGG": 40},
          author="—", note="Le portefeuille équilibré de référence"),
    fixed("permanent", "Permanent Portfolio", {"SPY": 25, "TLT": 25, "GLD": 25, "SHY": 25},
          published="1981-01", author="Harry Browne (1981)", note="4 quarts : croissance, déflation, inflation, récession"),
    fixed("golden_butterfly", "Golden Butterfly",
          {"SPY": 20, "IWN": 20, "TLT": 20, "SHY": 20, "GLD": 20},
          published="2016-01", author="Tyler (Portfolio Charts)", note="Permanent Portfolio + small caps value"),
    fixed("all_weather", "All Weather (version Robbins)",
          {"SPY": 30, "TLT": 40, "IEF": 15, "GLD": 7.5, "DBC": 7.5},
          published="2014-11", author="Ray Dalio / Tony Robbins (2014)", note="Parité de risque simplifiée"),
    fixed("three_fund", "Portefeuille 3 fonds (Bogleheads)", {"VTI": 42, "EFA": 18, "AGG": 40},
          published="2002-01", author="Taylor Larimore", note="Marché US total, international, obligations"),
    fixed("ivy", "Ivy Portfolio (buy & hold)",
          {"SPY": 20, "EFA": 20, "IEF": 20, "VNQ": 20, "GSG": 20},
          published="2009-01", author="Mebane Faber (2009)", note="5 classes équipondérées, version sans timing"),
    fixed("swensen", "Portefeuille Swensen (Yale)",
          {"VTI": 30, "EFA": 15, "EEM": 5, "VNQ": 20, "IEF": 15, "TIP": 15},
          published="2005-08", author="David Swensen (2005)", note="Version pour particuliers du modèle Yale"),
    fixed("coffeehouse", "Coffeehouse Portfolio",
          {"SPY": 10, "IVE": 10, "IWM": 10, "IWN": 10, "EFA": 10, "VNQ": 10, "IEF": 40},
          published="1998-01", author="Bill Schultheis (1998)",
          note="60 % d'actions réparties en six blocs égaux, 40 % d'obligations"),
    fixed("larry", "Larry Portfolio",
          {"IWN": 15, "SCZ": 7.5, "EEM": 7.5, "IEF": 70},
          published="2014-01", author="Larry Swedroe (2014)",
          note="30 % d'actions choisies pour leur rendement élevé, 70 % d'obligations d'État",
          variant_note="Swedroe vise des petites capitalisations « value » hors USA et des actions émergentes "
                       "« value » ; faute d'ETF américains assez anciens, on prend les petites capitalisations "
                       "internationales (SCZ) et les émergents (EEM)."),
]
