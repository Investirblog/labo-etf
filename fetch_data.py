#!/usr/bin/env python3
"""
fetch_data.py — Labo ETF : pipeline de données.

Source principale : yfinance (cours ajustés des dividendes et splits = rendement
total). Contrôle : classeurs iShares téléchargés à la main (--audit).

Sorties (dossier data/) :
  monthly_returns.csv   une ligne par mois, une colonne par ETF (décimales)
  monthly_tr_index.csv  indice de rendement total (base 100 au départ de chaque ETF)
  daily/<TICKER>.csv    cours ajustés quotidiens (sert aussi de cache)
  meta.json             couverture de chaque ETF, fenêtre commune
  quality_report.md     contrôles : trous, rendements aberrants, retards,
                        révisions rétroactives de Yahoo, audit iShares

Usage :
  python fetch_data.py                   # tout l'univers (universe.json)
  python fetch_data.py --only SPY TLT    # sous-ensemble
  python fetch_data.py --offline         # reconstruit depuis data/daily/ sans réseau
  python fetch_data.py --audit manuel    # + compare avec les classeurs iShares du dossier

Code de sortie : 0 = OK, 2 = au moins une erreur (voir quality_report.md).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
import time
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parent
UNIVERSE = ROOT / "universe.json"
DATA = ROOT / "data"
DAILY = DATA / "daily"

# Seuils des contrôles qualité
MAX_ABS_MONTHLY = 0.25      # |rendement mensuel| au-delà → signalé
MAX_ABS_DAILY = 0.20        # |variation quotidienne| au-delà → donnée suspecte
MAX_DAILY_GAP_DAYS = 7      # trou entre deux cotations → signalé
REVISION_TOL = 0.0025       # écart avec la version précédente au-delà → révision signalée
AUDIT_MEAN_TOL = 0.003      # audit iShares : écart mensuel moyen toléré
AUDIT_CAGR_TOL = 0.002      # audit iShares : écart de CAGR toléré (par an)


# --------------------------------------------------------------------------
# 1. Source : yfinance
# --------------------------------------------------------------------------
def fetch_yf(ticker: str, retries: int = 3) -> pd.Series:
    """Cours de clôture ajusté quotidien (dividendes réinvestis, splits corrigés)."""
    import yfinance as yf
    last_err = None
    for attempt in range(1, retries + 1):
        try:
            # (un échec donne un tableau vide : intercepté juste en dessous)
            h = yf.Ticker(ticker).history(period="max", interval="1d", auto_adjust=True,
                                          actions=False)
            s = h["Close"].dropna()
            if len(s) < 30:
                raise ValueError(f"historique vide ou trop court ({len(s)} lignes)")
            idx = pd.DatetimeIndex(s.index)
            s.index = (idx.tz_localize(None) if idx.tz is not None else idx).normalize()
            s = s[~s.index.duplicated(keep="last")].sort_index()
            s.name = "adj_close"
            s.index.name = "date"
            return s
        except Exception as e:  # noqa: BLE001
            last_err = e
            time.sleep(5 * attempt)
    raise RuntimeError(f"yfinance : {last_err}")


FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=TB3MS"


def fred_frame(sid: str, timeout: int = 20) -> pd.DataFrame:
    """Colonnes « date » et sid. Avec une clé (variable FRED_API_KEY), passe par l'API officielle
    de FRED, qui répond aussi aux serveurs de GitHub ; sinon par l'export CSV du site."""
    import io
    import os
    import requests
    key = os.environ.get("FRED_API_KEY", "").strip()
    if key:
        r = requests.get("https://api.stlouisfed.org/fred/series/observations",
                         params={"series_id": sid, "api_key": key, "file_type": "json"}, timeout=timeout)
        r.raise_for_status()
        obs = r.json()["observations"]
        return pd.DataFrame({"date": [o["date"] for o in obs], sid: [o["value"] for o in obs]})
    r = requests.get(f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}", timeout=timeout,
                     headers={"User-Agent": "Mozilla/5.0 etf-lab"})
    r.raise_for_status()
    return pd.read_csv(io.StringIO(r.text))
TBILL_START = "1990-01"


def fetch_tbill(today: dt.date, retries: int = 2) -> pd.Series:
    """Rendement mensuel des T-bills à 3 mois (FRED, série TB3MS).

    Le taux annuel publié pour le mois m-1 est le rendement acquis pendant le
    mois m (on achète le T-bill au début du mois). Sert de cash avant BIL (2007).
    """
    import io
    import requests
    last = None
    for attempt in range(1, retries + 1):
        try:
            df = fred_frame("TB3MS")
            date_col = next(c for c in df.columns if "date" in c.lower())
            rate = pd.to_numeric(df["TB3MS"], errors="coerce")
            idx = pd.PeriodIndex(pd.to_datetime(df[date_col]), freq="M")
            s = pd.Series(rate.values, index=idx).dropna()
            if len(s) < 100:
                raise ValueError(f"série trop courte ({len(s)} mois)")
            s = s.reindex(pd.period_range(s.index.min(), s.index.max(), freq="M")).ffill()
            ret = (s / 100 / 12).shift(1)                     # taux du mois précédent
            ret = ret[(ret.index >= pd.Period(TBILL_START, "M")) & (ret.index < pd.Period(today, "M"))]
            # le taux du dernier mois publié finance le mois suivant, s'il est clos
            nxt = s.index.max() + 1
            if nxt < pd.Period(today, "M"):
                ret.loc[nxt] = s.iloc[-1] / 100 / 12
            return ret.sort_index().rename("TBILL")
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * attempt)
    raise RuntimeError(f"FRED : {last}")


# Séries FRED complémentaires (colonne -> série, type, description)
#   rate : taux annuel en % publié chaque mois -> rendement du mois suivant (comme TB3MS)
#   fx   : cours quotidien -> variation de fin de mois à fin de mois
FRED_EXTRA = {
    "EURUSD": ("DEXUSEU", "fx", "Euro en dollars (FRED DEXUSEU) : variation mensuelle de l'euro face au dollar"),
    "ECBDEP": ("ECBDFR", "rate_daily", "Taux de dépôt de la BCE (FRED ECBDFR), plancher 0 % : compte épargne en euros"),
}
FRED_ONLY = {"TBILL", "EUR3M", *FRED_EXTRA}   # EUR3M : ancienne série, plus téléchargée


def fetch_fred(col: str, today: dt.date, retries: int = 2) -> pd.Series:
    """Série FRED de FRED_EXTRA convertie en rendements mensuels (index : mois)."""
    import io
    import requests
    sid, kind, _ = FRED_EXTRA[col]
    last = None
    for attempt in range(1, retries + 1):
        try:
            df = fred_frame(sid)
            date_col = next(c for c in df.columns if "date" in c.lower())
            val = pd.to_numeric(df[sid], errors="coerce")
            dates = pd.to_datetime(df[date_col])
            if kind == "fx":
                # historique FRED (depuis 1999) ; les mois récents viennent de Yahoo (EURUSD=X),
                # publié sans le décalage d'une semaine de FRED
                s = pd.Series(val.values, index=dates).dropna()
                m = s.groupby(s.index.to_period("M")).last()
                ret = m[m.index < pd.Period(today, "M")].pct_change().dropna()
                try:
                    yx = fetch_yf("EURUSD=X")
                    ym = yx.groupby(yx.index.to_period("M")).last()
                    yret = ym[ym.index < pd.Period(today, "M")].pct_change().dropna()
                    ret = yret.combine_first(ret)
                except Exception:  # noqa: BLE001 — FRED seul
                    pass
            elif kind == "rate_daily":
                # taux quotidien : moyenne du mois, plancher à 0 (un compte épargne ne rémunère pas en négatif)
                s = pd.Series(val.values, index=dates).dropna()
                m = s.groupby(s.index.to_period("M")).mean().clip(lower=0)
                ret = (m / 100 / 12)[m.index < pd.Period(today, "M")]
            else:
                # publié avec plusieurs mois de retard : le dernier taux connu est prolongé
                s = pd.Series(val.values, index=pd.PeriodIndex(dates, freq="M")).dropna()
                last_closed = pd.Period(today, "M") - 1
                s = s.reindex(pd.period_range(s.index.min(), max(s.index.max(), last_closed), freq="M")).ffill()
                ret = (s / 100 / 12).shift(1).dropna()
                ret = ret[ret.index <= last_closed]
            if len(ret) < 100:
                raise ValueError(f"série trop courte ({len(ret)} mois)")
            return ret.sort_index().rename(col)
        except Exception as e:  # noqa: BLE001
            last = e
            time.sleep(3 * attempt)
    raise RuntimeError(f"FRED {sid} : {last}")


# --------------------------------------------------------------------------
# Sources de secours quand FRED ne répond pas (fréquent depuis les serveurs de GitHub)
# --------------------------------------------------------------------------
ECB_KEYS = {"EURUSD": "EXR/D.USD.EUR.SP00.A",          # cours de référence BCE : dollars pour 1 euro
            "ECBDEP": "FM/D.U2.EUR.4F.KR.DFR.LEV"}     # taux de la facilité de dépôt, en %


def fetch_ecb_daily(col: str) -> pd.Series:
    """Série quotidienne du portail de données de la BCE (index : dates)."""
    import io
    import requests
    url = f"https://data-api.ecb.europa.eu/service/data/{ECB_KEYS[col]}?format=csvdata"
    r = requests.get(url, timeout=30, headers={"User-Agent": "Mozilla/5.0 etf-lab"})
    r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    s = pd.Series(pd.to_numeric(df["OBS_VALUE"], errors="coerce").values,
                  index=pd.to_datetime(df["TIME_PERIOD"])).dropna().sort_index()
    if len(s) < 100:
        raise ValueError(f"série BCE trop courte ({len(s)} jours)")
    return s


def monthly_from_daily(col: str, s: pd.Series, today: dt.date) -> pd.Series:
    """Même conversion que fetch_fred, à partir d'une série quotidienne."""
    cur = pd.Period(today, "M")
    if FRED_EXTRA[col][1] == "fx":
        m = s.groupby(s.index.to_period("M")).last()
        return m[m.index < cur].pct_change().dropna().rename(col)
    m = s.groupby(s.index.to_period("M")).mean().clip(lower=0)
    return (m / 100 / 12)[m.index < cur].rename(col)


def fetch_backup(col: str, today: dt.date) -> pd.Series:
    """TBILL : taux des T-bills 13 semaines (Yahoo ^IRX) ; EURUSD, ECBDEP : BCE."""
    if col == "TBILL":
        px = fetch_yf("^IRX")                      # taux annualisé en %, moyenne du mois comme TB3MS
        m = px.groupby(px.index.to_period("M")).mean()
        m = m[m.index < pd.Period(today, "M")]
        ret = (m / 100 / 12).shift(1).dropna()
        return ret.rename("TBILL")
    return monthly_from_daily(col, fetch_ecb_daily(col), today)


def with_backup(col: str, cache: Path, today: dt.date, err: Exception):
    """FRED a échoué : historique du cache + mois récents de la source de secours."""
    old = None
    if cache.exists():
        old = pd.read_csv(cache, index_col=0)[col]
        old.index = pd.PeriodIndex(old.index, freq="M")
    try:
        new = fetch_backup(col, today)
    except Exception as e2:  # noqa: BLE001
        if old is None:
            raise RuntimeError(f"{err} ; secours : {e2}")
        print(f"[{col}] ⚠️ FRED et secours indisponibles ({e2}) → cache utilisé", file=sys.stderr)
        return old, "cache data/daily (non rafraîchi)", True
    s = new if old is None else old.combine_first(new)   # historique du cache, mois manquants du secours
    return s.sort_index().rename(col), "secours (FRED indisponible)", False


# --------------------------------------------------------------------------
# 2. Quotidien → mensuel
# --------------------------------------------------------------------------
def monthly_from_prices(px: pd.Series, today: dt.date) -> pd.Series:
    """Rendements mensuels de fin de mois ; le mois en cours (incomplet) est exclu."""
    m = px.groupby(px.index.to_period("M")).last()
    m = m[m.index < pd.Period(today, "M")]
    return m.pct_change()  # 1er mois (partiel, lancement) → NaN


# --------------------------------------------------------------------------
# 3. Contrôles qualité
# --------------------------------------------------------------------------
def quality_checks(px: pd.Series, monthly: pd.Series, today: dt.date,
                   checked_until: pd.Period | None = None) -> list[str]:
    """checked_until : dernier mois déjà publié (et donc déjà vérifié) ; les alertes
    de rendements extrêmes ne portent que sur les mois postérieurs."""
    issues = []
    m = monthly.dropna()
    if m.empty:
        return ["aucun rendement mensuel calculable"]
    full = pd.period_range(m.index.min(), m.index.max(), freq="M")
    missing = full.difference(m.index)
    if len(missing):
        issues.append(f"{len(missing)} mois manquant(s) : "
                      + ", ".join(str(p) for p in missing[:6]) + ("…" if len(missing) > 6 else ""))
    new_m = m[m.index > checked_until] if checked_until is not None else m
    for p, v in new_m[new_m.abs() > MAX_ABS_MONTHLY].items():
        issues.append(f"rendement mensuel aberrant {p} : {v:+.1%}")
    d = px.pct_change().dropna()
    if checked_until is not None:
        d = d[d.index.to_period("M") > checked_until]
    for day, v in d[d.abs() > MAX_ABS_DAILY].items():
        issues.append(f"variation quotidienne suspecte le {day:%Y-%m-%d} : {v:+.1%}")
    gaps = pd.Series(px.index).diff().dt.days
    n_gaps = int((gaps > MAX_DAILY_GAP_DAYS).sum())
    if n_gaps:
        end = px.index[int(gaps.idxmax())]
        issues.append(f"{n_gaps} trou(s) de plus de {MAX_DAILY_GAP_DAYS} jours dans les cours "
                      f"(le plus long se termine le {end:%Y-%m-%d})")
    expected = pd.Period(today, "M") - 1
    if m.index.max() < expected:
        issues.append(f"données en retard : dernier mois {m.index.max()}, attendu {expected}")
    else:
        last_in_month = px[px.index.to_period("M") == expected].index.max()
        if pd.notna(last_in_month) and (expected.to_timestamp(how="end") - last_in_month).days > 5:
            issues.append(f"mois {expected} possiblement incomplet "
                          f"(dernier cours du mois : {last_in_month:%Y-%m-%d})")
    return issues


def revisions(ticker: str, monthly: pd.Series, previous: pd.DataFrame | None) -> list[str]:
    """Yahoo révise parfois l'historique (dividende corrigé…) : on compare à la version précédente."""
    if previous is None or ticker not in previous:
        return []
    old = previous[ticker].dropna()
    old.index = pd.PeriodIndex(old.index, freq="M")
    both = pd.concat([old, monthly], axis=1, join="inner").dropna()
    diff = (both.iloc[:, 1] - both.iloc[:, 0]).abs()
    changed = diff[diff > REVISION_TOL]
    if changed.empty:
        return []
    ex = ", ".join(f"{p} ({both.iloc[:, 0][p]:+.2%} → {both.iloc[:, 1][p]:+.2%})"
                   for p in changed.index[:4])
    return [f"{len(changed)} mois révisé(s) par rapport à la version précédente : {ex}"
            + ("…" if len(changed) > 4 else "")]


# --------------------------------------------------------------------------
# 4. Audit iShares
# --------------------------------------------------------------------------
def identify_ticker(path: Path, universe: dict) -> str | None:
    import ishares_reader as ir
    m = re.match(r"([A-Za-z]{2,5})(?=[_\-. ])", path.stem)
    if m and m.group(1).upper() in universe:
        return m.group(1).upper()
    stem = ir._norm(re.sub(r"_fund$", "", path.stem, flags=re.I))
    for tk, cfg in universe.items():
        if cfg.get("ishares") and ir._norm(cfg["ishares"]) == stem:
            return tk
    return m.group(1).upper() if m else None


def audit(folder: Path, universe: dict, monthly_by_ticker: dict, today: dt.date,
          offline: bool) -> list[str]:
    import ishares_reader as ir
    lines = ["## Audit : yfinance vs classeurs iShares (NAV officielle)", ""]
    files = sorted(p for p in folder.iterdir() if p.suffix.lower() in (".xls", ".xlsx", ".xml"))
    if not files:
        return lines + [f"- aucun classeur dans {folder}", ""]
    for f in files:
        tk = identify_ticker(f, universe)
        if tk is None:
            lines.append(f"- ❔ {f.name} : ETF non reconnu (renomme-le en TICKER_fund.xls)")
            continue
        try:
            hist = ir.extract_history(ir.read_workbook(f))
            r, _ = ir.daily_total_returns(hist)
            tri = (1 + r.fillna(0)).cumprod()
            nav_m = monthly_from_prices(tri, today)
            yf_m = monthly_by_ticker.get(tk)
            if yf_m is None:
                if offline:
                    raise RuntimeError("pas de données yfinance (mode hors-ligne)")
                yf_m = monthly_from_prices(fetch_yf(tk), today)
            both = pd.concat([nav_m, yf_m], axis=1, join="inner").dropna()
            if len(both) < 12:
                raise RuntimeError(f"seulement {len(both)} mois en commun")
            diff = (both.iloc[:, 0] - both.iloc[:, 1]).abs()
            years = len(both) / 12
            c_nav = (1 + both.iloc[:, 0]).prod() ** (1 / years) - 1
            c_yf = (1 + both.iloc[:, 1]).prod() ** (1 / years) - 1
            ok = diff.mean() <= AUDIT_MEAN_TOL and abs(c_nav - c_yf) <= AUDIT_CAGR_TOL
            lines.append(f"- {'✅' if ok else '⚠️'} **{tk}** ({f.name}) : {len(both)} mois "
                         f"({both.index.min()} → {both.index.max()}), écart moyen {diff.mean():.2%}, "
                         f"max {diff.max():.2%} ({diff.idxmax()}), CAGR iShares {c_nav:.2%} "
                         f"vs yfinance {c_yf:.2%}")
        except Exception as e:  # noqa: BLE001
            lines.append(f"- ❌ **{tk}** ({f.name}) : {e}")
    return lines + [""]


# --------------------------------------------------------------------------
# 5. Orchestration
# --------------------------------------------------------------------------
def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--only", nargs="+", metavar="TICKER")
    ap.add_argument("--offline", action="store_true", help="n'utilise que data/daily/")
    ap.add_argument("--audit", type=Path, metavar="DOSSIER",
                    help="compare avec les classeurs iShares de ce dossier")
    ap.add_argument("--today", help=argparse.SUPPRESS)  # pour les tests
    a = ap.parse_args(argv)

    today = dt.date.fromisoformat(a.today) if a.today else dt.date.today()
    universe = {k: v for k, v in json.loads(UNIVERSE.read_text(encoding="utf-8")).items()
                if not k.startswith("_")}
    tickers = [t.upper() for t in a.only] if a.only else list(universe)
    DAILY.mkdir(parents=True, exist_ok=True)
    prev_path = DATA / "monthly_returns.csv"
    previous = pd.read_csv(prev_path, index_col=0) if prev_path.exists() else None

    series, meta, report, errors = {}, {}, [], 0
    for tk in [t for t in tickers if t not in FRED_ONLY]:   # séries FRED : pas de yfinance
        cfg = universe.get(tk, {})
        cache = DAILY / f"{tk}.csv"
        notes = []
        try:
            if a.offline:
                raise RuntimeError("mode hors-ligne")
            px = fetch_yf(tk)
            px.to_frame().to_csv(cache, date_format="%Y-%m-%d", float_format="%.6f")
            source = "yfinance"
        except Exception as e:  # noqa: BLE001
            if cache.exists():
                px = pd.read_csv(cache, index_col=0, parse_dates=True)["adj_close"]
                source = "cache data/daily (non rafraîchi)"
                if not a.offline:
                    errors += 1
                    notes.append(f"⚠️ {e} → cache utilisé")
                    print(f"[{tk}] ⚠️ {e} → cache utilisé", file=sys.stderr)
            else:
                errors += 1
                report.append(f"### {tk} — {cfg.get('name', '')}\n- ❌ {e}\n")
                print(f"[{tk}] ❌ {e}", file=sys.stderr)
                continue
        if not a.offline:
            time.sleep(1)  # ménage Yahoo

        monthly = monthly_from_prices(px, today)
        checked_until = None
        if previous is not None and tk in previous and previous[tk].notna().any():
            checked_until = pd.Period(previous[tk].dropna().index.max(), "M")
        issues = (quality_checks(px, monthly, today, checked_until)
                  + revisions(tk, monthly, previous))
        series[tk] = monthly
        m = monthly.dropna()
        meta[tk] = {"name": cfg.get("name", ""), "class": cfg.get("class", ""),
                    "first_month": str(m.index.min()) if len(m) else None,
                    "last_month": str(m.index.max()) if len(m) else None,
                    "months": int(len(m)), "last_price_date": f"{px.index[-1]:%Y-%m-%d}",
                    "source": source}
        lines = [f"### {tk} — {cfg.get('name', '')}",
                 f"- Source : {source} · couverture {meta[tk]['first_month']} → "
                 f"{meta[tk]['last_month']} ({meta[tk]['months']} mois)"]
        lines += [f"- {tk} : {n}" for n in notes]
        lines += [f"- ⚠️ {tk} : {i}" for i in issues] or ["- ✅ aucun problème détecté"]
        report.append("\n".join(lines) + "\n")
        print(f"[{tk}] {meta[tk]['first_month']} → {meta[tk]['last_month']}"
              + (f"  ({len(issues)} alerte(s))" if issues else ""))

    # T-bills FRED : cash avant 2007 (pas un ETF, donc hors de l'univers yfinance)
    if not a.only or "TBILL" in tickers:
        cache = DAILY / "TBILL.csv"
        try:
            if a.offline:
                raise RuntimeError("mode hors-ligne")
            tb = fetch_tbill(today)
            tb.to_frame().to_csv(cache)
            src = "FRED TB3MS"
        except Exception as e:  # noqa: BLE001
            tb = None
            if a.offline and cache.exists():
                tb = pd.read_csv(cache, index_col=0)["TBILL"]
                tb.index = pd.PeriodIndex(tb.index, freq="M")
                src = "cache data/daily"
            elif not a.offline:
                try:
                    tb, src, stale = with_backup("TBILL", cache, today, e)
                    tb.to_frame().to_csv(cache)
                    errors += stale
                    print(f"[TBILL] FRED indisponible → {src}", file=sys.stderr)
                except Exception as e2:  # noqa: BLE001
                    errors += 1
                    report.append(f"### TBILL — T-bills 3 mois (FRED)\n- ❌ {e2}\n")
                    print(f"[TBILL] ❌ {e2}", file=sys.stderr)
        if tb is not None:
            series["TBILL"] = tb
            meta["TBILL"] = {"name": "T-bills 3 mois (FRED TB3MS)", "class": "Cash",
                             "first_month": str(tb.index.min()), "last_month": str(tb.index.max()),
                             "months": int(len(tb)), "source": src}
            report.append(f"### TBILL — T-bills 3 mois (FRED)\n- Source : {src} · couverture "
                          f"{tb.index.min()} → {tb.index.max()} ({len(tb)} mois)\n")
            print(f"[TBILL] {tb.index.min()} → {tb.index.max()}")

    # Euro : change EUR/USD et taux court en euros (vue d'un investisseur européen)
    for col, (sid, _, label) in FRED_EXTRA.items():
        if a.only and col not in tickers:
            continue
        cache = DAILY / f"{col}.csv"
        try:
            if a.offline:
                raise RuntimeError("mode hors-ligne")
            try:   # portail de la BCE d'abord : fiable depuis GitHub
                fx = monthly_from_daily(col, fetch_ecb_daily(col), today)
                src = "BCE (data-api.ecb.europa.eu)"
            except Exception:  # noqa: BLE001
                fx = fetch_fred(col, today)
                src = f"FRED {sid}"
            fx.to_frame().to_csv(cache)
        except Exception as e:  # noqa: BLE001
            if cache.exists():
                fx = pd.read_csv(cache, index_col=0)[col]
                fx.index = pd.PeriodIndex(fx.index, freq="M")
                src = "cache data/daily (non rafraîchi)"
                if not a.offline:
                    errors += 1
                    print(f"[{col}] ⚠️ {e} → cache utilisé", file=sys.stderr)
            else:
                fx = None
                errors += 1
                report.append(f"### {col} — {label}\n- ❌ {e}\n")
                print(f"[{col}] ❌ {e}", file=sys.stderr)
        if fx is not None:
            series[col] = fx
            meta[col] = {"name": label, "class": "Euro", "first_month": str(fx.index.min()),
                         "last_month": str(fx.index.max()), "months": int(len(fx)), "source": src}
            report.append(f"### {col} — {label}\n- Source : {src} · couverture "
                          f"{fx.index.min()} → {fx.index.max()} ({len(fx)} mois)\n")
            print(f"[{col}] {fx.index.min()} → {fx.index.max()}")

    audit_lines = audit(a.audit, universe, series, today, a.offline) if a.audit else []

    common_start = "—"
    if series:
        table = pd.DataFrame(series).sort_index()
        table.index = table.index.astype(str)
        table.index.name = "month"
        if previous is not None and a.only:  # --only : on garde les autres colonnes existantes
            keep = previous.drop(columns=[c for c in table.columns if c in previous.columns])
            table = keep.join(table, how="outer").sort_index()
            table.index.name = "month"
        table.round(6).to_csv(prev_path)
        tri = (1 + table.fillna(0)).cumprod() * 100
        tri = tri.where(table.notna().cumsum() > 0)
        tri.round(4).to_csv(DATA / "monthly_tr_index.csv")
        common = table.drop(columns=list(FRED_ONLY), errors="ignore").dropna()
        common_start = common.index.min() if len(common) else "—"

    (DATA / "meta.json").write_text(json.dumps({
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "source": "yfinance, cours ajustés (dividendes réinvestis, splits corrigés)",
        "common_window_start": common_start,
        "etfs": meta,
    }, indent=2, ensure_ascii=False), encoding="utf-8")

    n_alerts = sum(r.count("⚠️") for r in report)
    head = [f"# Rapport qualité — {today:%Y-%m-%d}", "",
            f"- ETF traités : {len(series)}/{len(tickers)} · erreurs : {errors} · "
            f"alertes : {n_alerts}",
            f"- Fenêtre commune (tous les ETF traités disponibles) : à partir de {common_start}",
            ""]
    (DATA / "quality_report.md").write_text(
        "\n".join(head + audit_lines + ["## Détail par ETF", ""] + report), encoding="utf-8")
    if audit_lines:
        print("\n" + "\n".join(audit_lines).strip())
    print(f"\nTerminé : {len(series)}/{len(tickers)} ETF, {errors} erreur(s), "
          f"{n_alerts} alerte(s). Fenêtre commune depuis {common_start}. "
          f"Voir data/quality_report.md")
    return 2 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
