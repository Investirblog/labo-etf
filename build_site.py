#!/usr/bin/env python3
"""
build_site.py — génère les vraies pages HTML du site (une par adresse).

À partir de templates/app.html (le site interactif) et des données
(site/strategies.json, fiches.json, ucits.json, content/methode.html), écrit :

  site/index.html                     accueil (tableau comparatif)
  site/strategies/<id>/index.html     une page par stratégie
  site/equivalents-ucits/index.html   table des équivalents UCITS
  site/methode/index.html             méthode et limites
  site/mentions-legales/index.html   éditeur, hébergeur, données personnelles
  site/og/<id>.png                    images d'aperçu (og_images.py)
  site/404.html, site/sitemap.xml, site/robots.txt

Chaque page contient son contenu en HTML (lisible par les moteurs de recherche
et les aperçus de liens), son titre, sa description et ses balises Open Graph.
Le JavaScript prend ensuite le relais pour les graphiques interactifs.

Appelé automatiquement à la fin de run_backtests.py. Seul : python3 build_site.py
"""
from __future__ import annotations

import datetime as dt
import html
import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent
SITE = ROOT / "site"
TEMPLATE = ROOT / "templates" / "app.html"
CONFIG = ROOT / "site_config.json"

MOIS = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
MOIS_LONG = ["janvier", "février", "mars", "avril", "mai", "juin", "juillet", "août", "septembre",
             "octobre", "novembre", "décembre"]
NBSP = " "
REF_NAMES = {"acwi": "Actions mondiales", "spy": "S&P 500"}
MATCH = {"meme": "même indice", "proche": "proche", "aucun": "aucun"}
FAMILLES: dict = {}          # slug -> textes (site/content/familles.json)
FAM_SLUG: dict = {}          # famille -> slug
COMPARAISONS: list = []      # pages « X ou Y ? » (site/content/comparaisons.json)


# --------------------------------------------------------------------------
# Mise en forme (identique au site)
# --------------------------------------------------------------------------
def e(x) -> str:
    return html.escape(str(x), quote=True)


LINK = re.compile(r"\[([^\]]+)\]\((?:strategie:([a-z0-9_]+)|(https?://[^)\s]+))\)")
KNOWN_IDS: set[str] = set()


def rich(x) -> str:
    """Texte échappé, avec [texte](strategie:adm) et [texte](https://…) convertis en liens."""
    def sub(m):
        txt, sid, url = m.groups()
        if sid:
            return f'<a href="/strategies/{sid}/">{txt}</a>' if sid in KNOWN_IDS else txt
        return f'<a href="{url}" target="_blank" rel="noopener">{txt}</a>'
    return LINK.sub(sub, e(x))


def plain(x: str) -> str:
    """Même texte sans la syntaxe de lien (descriptions, images)."""
    return LINK.sub(lambda m: m.group(1), x)


def m_label(p: str | None) -> str:
    if not p:
        return "—"
    y, m = p.split("-")[:2]
    return f"{MOIS[int(m) - 1]} {y}"


def m_long(p: str) -> str:
    y, m = p.split("-")[:2]
    return f"{MOIS_LONG[int(m) - 1]} {y}"


def de(mot: str) -> str:
    """« de octobre » -> « d'octobre »."""
    return ("d'" if mot[:1].lower() in "aeiouyéèêâàîôûh" else "de ") + mot


def next_month(p: str) -> str:
    y, m = map(int, p.split("-")[:2])
    return f"{y + (m == 12)}-{(m % 12) + 1:02d}"


def num(v, d=1) -> str:
    return f"{v:,.{d}f}".replace(",", " ").replace(".", ",").replace(" ", NBSP)


def pct(v, d=1, sign=False) -> str:
    if v is None:
        return "—"
    x = v * 100
    if abs(x) < 0.5 * 10 ** -d:   # évite « -0,0 % »
        x = 0.0
    s = num(x, d)
    return ("+" if sign and x > 0 else "") + s + NBSP + "%"


def dec(v, d=2) -> str:
    return "—" if v is None else num(v, d)


def uw(st) -> str:
    n = st.get("underwater_months")
    return "—" if n is None else f"{n}{'+' if st.get('underwater_ongoing') else ''}{NBSP}mois"


def weight_text(w: float) -> str:
    return num(w * 100, 0 if abs(w * 100 - round(w * 100)) < 1e-9 else 1) + NBSP + "%"


# --------------------------------------------------------------------------
# Gabarit
# --------------------------------------------------------------------------
def split_template(tpl: str) -> tuple[str, str]:
    """Retire les balises d'en-tête du prototype et sépare <head> / <body>."""
    for pat in (r'<meta charset="utf-8">\s*', r'<meta name="viewport"[^>]*>\s*',
                r"<title>.*?</title>\s*", r'<meta name="description"[^>]*>\s*'):
        tpl = re.sub(pat, "", tpl, count=1, flags=re.S)
    i = tpl.index('<div class="wrap">')
    return tpl[:i], tpl[i:]


def page(head_tpl: str, body_tpl: str, *, cfg: dict, path: str, title: str, desc: str,
         content: str, nav: str, stamp: str, og_type="website", noindex=False, jsonld=None,
         image="home", static=False) -> str:
    base = cfg["site_url"].rstrip("/")
    url = base + "/" + path
    meta = [
        '<meta charset="utf-8">',
        '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
        f"<title>{e(title)}</title>",
        f'<meta name="description" content="{e(desc)}">',
        f'<link rel="canonical" href="{e(url)}">',
        '<meta property="og:site_name" content="Labo ETF">',
        '<meta property="og:locale" content="fr_FR">',
        f'<meta property="og:type" content="{og_type}">',
        f'<meta property="og:title" content="{e(title)}">',
        f'<meta property="og:description" content="{e(desc)}">',
        f'<meta property="og:url" content="{e(url)}">',
        f'<meta property="og:image" content="{base}/og/{image}.png">',
        '<meta property="og:image:width" content="1200">',
        '<meta property="og:image:height" content="630">',
        f'<meta property="og:image:alt" content="{e(title)}">',
        '<meta name="twitter:card" content="summary_large_image">',
        '<link rel="preload" href="/fonts/ibm-plex-sans-latin-400-normal.woff2" as="font" type="font/woff2" crossorigin>',
    ]
    if cfg.get("goatcounter"):  # mesure d'audience sans cookie
        meta.append(f'<script data-goatcounter="{e(cfg["goatcounter"])}" async src="https://gc.zgo.at/count.js"></script>')
    if noindex:
        meta.append('<meta name="robots" content="noindex">')
    if jsonld:
        meta.append('<script type="application/ld+json">'
                    + json.dumps(jsonld, ensure_ascii=False).replace("</", "<\\/") + "</script>")
    head_tpl = (head_tpl.replace('url("fonts/', 'url("/fonts/').replace('href="favicon', 'href="/favicon')
                .replace('href="apple-touch-icon', 'href="/apple-touch-icon'))
    body = body_tpl
    body = body.replace('href="https://laboetf.eu/', 'href="/').replace('href="https://laboetf.netlify.app/', 'href="/')  # liens du gabarit vers le site publié
    body = body.replace('href="#signaux"', 'href="/signaux/"').replace('href="#comparer"', 'href="/comparer/"')
    # liens de navigation réels
    body = body.replace('class="brand" href="#"', 'class="brand" href="/"')
    body = body.replace('<a href="#" data-nav="">', '<a href="/" data-nav="">')
    body = body.replace('href="#ucits"', 'href="/equivalents-ucits/"').replace('href="#methode"', 'href="/methode/"')
    body = body.replace(f'data-nav="{nav}">', f'data-nav="{nav}" aria-current="page">', 1)
    body = body.replace('<span class="stamp" id="stamp">Chargement…</span>',
                        f'<span class="stamp" id="stamp">{e(stamp)}</span>')
    body = body.replace('<main id="app" aria-live="polite"></main>',
                        f'<main id="app" aria-live="polite">{content}</main>')
    flags = 'window.ESL_BASE = "/";' + (" window.ESL_STATIC = true;" if static else "")
    body = body.replace("<script>", f"<script>{flags}</script>\n<script>", 1)
    out = ("<!doctype html>\n<html lang=\"fr\">\n<head>\n" + "\n".join(meta) + "\n"
           + head_tpl.strip() + "\n</head>\n<body>\n" + body.strip() + "\n</body>\n</html>\n")
    name = cfg.get("site_name") or "Labo ETF"
    return out if name == "Labo ETF" else out.replace("Labo ETF", e(name))


# --------------------------------------------------------------------------
# Contenus
# --------------------------------------------------------------------------
def intro_sentence(data, ref) -> str:
    rs = ref["stats_common"]
    strats = [s for s in data["strategies"] if s["id"] not in REF_NAMES]
    n = len(strats)
    better = sum(s["stats_common"]["cagr"] > rs["cagr"] for s in strats)
    sharper = sum((s["stats_common"]["sharpe"] or -9) > rs["sharpe"] for s in strats)
    shallower = sum(s["stats_common"]["max_dd"] > rs["max_dd"] for s in strats)
    name = "les actions mondiales" if ref["id"] == "acwi" else "le S&amp;P 500"
    poss = "leurs" if ref["id"] == "acwi" else "ses"
    verb = lambda k: "ont" if k > 1 else "a"
    sh = f"toutes les {n}" if shallower == n else str(shallower)
    sp = "toutes" if sharper == n else str(sharper)
    return (f"Depuis {m_label(data['common_window'][0])}, <b>{better} stratégie{'s' if better > 1 else ''} sur {n}</b> "
            f"{verb(better)} rapporté plus que {name} ({pct(rs['cagr'])} par an). Mais <b>{sh}</b> {verb(shallower)} "
            f"subi une pire baisse moins profonde que {poss} {pct(rs['max_dd'], 0)}, et <b>{sp}</b> {verb(sharper)} "
            f"mieux rémunéré chaque unité de risque. La vraie question n'est pas seulement combien une stratégie "
            f"rapporte, mais ce qu'elle fait traverser pour y arriver.")


def hero_stats(data) -> str:
    strats = [s for s in data["strategies"] if s["id"] not in REF_NAMES]
    changed = 0
    for s in strats:
        h = s.get("signal_history") or {}
        ms = sorted(h)
        if s["family"] != "Statique" and len(ms) >= 2 and not same_weights(h[ms[-2]], s["next_signal"]["weights"]):
            changed += 1
    nm = data["strategies"][0]["next_signal"]["for_month"]
    c0, c1 = data["common_window"]
    years = (int(c1[:4]) * 12 + int(c1[5:7]) - int(c0[:4]) * 12 - int(c0[5:7]) + 1) // 12
    return (f'<div class="hero-stats"><div><b>{len(strats)}</b><span>stratégies testées sur les mêmes données</span></div>'
            f'<a href="/signaux/"><b>{changed}</b><span>changent d\'allocation en {MOIS_LONG[int(nm[5:7]) - 1]} →</span></a>'
            f'<div><b>{years}{NBSP}ans</b><span>de backtest, sur la même période pour toutes (depuis {m_label(c0)})</span></div></div>')


def board_html(data, ref) -> str:
    c0, c1 = data["common_window"]
    rows = sorted(data["strategies"], key=lambda s: -(s["stats_common"]["sharpe"] or -9))
    trs = []
    for s in rows:
        st = s["stats_common"]
        trs.append(
            f'<tr class="{"is-bench" if s["id"] in REF_NAMES else ""}"><td><div class="s-name">'
            f'<a class="s-link" href="/strategies/{s["id"]}/">{e(s["name"])}</a></div>'
            f'<div class="s-meta"><span class="fam">{e(s["family"])}</span></div></td>'
            f'<td class="num">{pct(st["cagr"])}</td><td class="num">{dec(st["sharpe"])}</td>'
            f'<td class="num neg">{pct(st["max_dd"])}</td><td class="num">{uw(st)}</td>'
            f'<td class="num">{pct(st["worst_year"], 1, True)}</td></tr>')
    return f"""
      <section class="intro">
        <h1>Les stratégies ETF connues, testées sur les mêmes données et avec les mêmes règles</h1>
        {hero_stats(data)}
        <p class="key">{intro_sentence(data, ref)}</p>
        <p>Portefeuilles permanents, momentum, suivi de tendance : chaque stratégie est recalculée chaque mois à partir des rendements réels des ETF, frais compris, puis comparée sur la même période. Cliquez sur une stratégie pour ouvrir sa fiche.</p>
        <ul class="method">
          <li>Période commune <b>{m_label(c0)} → {m_label(c1)}</b></li>
          <li>Frais <b>{num(data['cost_per_trade'] * 100, 2)}{NBSP}%</b> par transaction</li>
          <li>Signaux <b>fin de mois</b> (portefeuilles fixes : rééquilibrage annuel)</li>
          <li>Devise <b>USD</b></li>
        </ul>
        {fam_links()}
      </section>
      <div class="table-scroll"><table class="board">
        <thead><tr><th scope="col">Stratégie</th><th scope="col">CAGR</th><th scope="col">Sharpe</th>
          <th scope="col">Max DD</th><th scope="col">Récup.</th><th scope="col">Pire année</th></tr></thead>
        <tbody>{''.join(trs)}</tbody></table></div>
      <p class="note-under">Période commune de {m_label(c0)} à {m_label(c1)}, frais inclus. CAGR : rendement annualisé. Sharpe : rendement au-delà des T-bills, divisé par la volatilité. Max DD : pire baisse depuis un sommet. Récup. : plus longue période passée sous un sommet précédent. Pire année : pire année civile complète ({int(c0[:4]) + (c0[5:7] != "01")}-{int(c1[:4]) - (c1[5:7] != "12")}), sans le début de {c0[:4]} ni l'année en cours.</p>"""


def rules_for(s) -> list[str]:
    if s.get("rules"):
        return s["rules"]
    w = sorted(s["next_signal"]["weights"].items(), key=lambda kv: -kv[1])
    rb = ("Rééquilibrage une fois par an, fin décembre, pour revenir aux poids cibles."
          if s["rebalance"] == "annual" else "Rééquilibrage chaque fin de mois.")
    return ["Allocation fixe : " + ", ".join(f"{weight_text(v)} {k}" for k, v in w) + ".", rb]


def ucits_item(t, uc) -> str:
    m = uc["map"].get(t)
    if not m:
        return ""
    funds = [uc["_funds"][k] for k in m["funds"]]
    lines = "".join(f'<div class="fmeta">{e(f["name"])} · <span class="isin">{f["isin"]}</span> · '
                    f'frais {num(f["ter"], 2)}{NBSP}%</div>' for f in funds)
    main = " + ".join(f'<b>{e(f["tickers"].split(" (")[0])}</b>' for f in funds) or "<span>—</span>"
    note = f'<div class="unote">{e(m["note"])}</div>' if m.get("note") else ""
    return (f'<div class="ucits-item"><div class="top"><span class="us num">{"Cash" if t == "CASH" else e(t)}</span>'
            f'<span aria-hidden="true">→</span>{main}<span class="match {m["match"]}">{MATCH[m["match"]]}</span></div>'
            f'{lines}{note}</div>')


def sheet_html(s, data, fiches, uc, ref) -> str:
    st, sf = s["stats_common"], s["stats_full"]
    rst = ref["stats_common"]
    rname = REF_NAMES[ref["id"]]
    f = fiches.get(s["id"])
    cmp = lambda v: "" if s["id"] == ref["id"] else f'<span class="cmp">{e(rname)} : <span class="num">{v}</span></span>'
    ess = ""
    if f:
        ess = (f'<section class="panel" style="--o:1"><h2>L\'essentiel</h2><div class="essentials"><p>{rich(f["idee"])}</p>'
               f'<h3>Points forts</h3><ul>{"".join(f"<li>{rich(x)}</li>" for x in f["forces"])}</ul>'
               f'<h3>Points faibles</h3><ul>{"".join(f"<li>{rich(x)}</li>" for x in f["faiblesses"])}</ul>'
               + (f'<h3>À savoir</h3><p>{rich(f["a_savoir"])}</p>' if f.get("a_savoir") else "") + "</div></section>")
    nm = s["next_signal"]["for_month"]
    sig = "".join(
        f'<div class="alloc-row"><span class="tk">{"Cash" if k == "CASH" else e(k)}</span>'
        f'<span class="bar"><i style="width:{v * 100:.1f}%"></i></span><span class="pc num">{weight_text(v)}</span>'
        f'<span class="nm">{"T-bills (BIL)" if k == "CASH" else e(data["etf_names"].get(k, ""))}</span></div>'
        for k, v in sorted(s["next_signal"]["weights"].items(), key=lambda kv: -kv[1]))
    extra = ""
    if s.get("variant_note"):
        extra += f'<div class="callout">{rich(s["variant_note"])}</div>'
    if s.get("published"):
        extra += f'<div class="callout"><b>Publiée en {m_long(s["published"])}.</b></div>'
    assets = list(dict.fromkeys(s["assets"] + (["CASH"] if s.get("uses_cash") or "CASH" in s["next_signal"]["weights"] else [])))
    ucits = "".join(ucits_item(a, uc) for a in assets) if uc else ""
    metrics = [
        ("Début", lambda x: m_label(x["start"])), ("CAGR", lambda x: pct(x["cagr"])),
        ("Volatilité", lambda x: pct(x["vol"])), ("Sharpe", lambda x: dec(x["sharpe"])),
        ("Max drawdown", lambda x: pct(x["max_dd"])), ("Plus longue période sous l'eau", uw),
        ("Meilleure année civile complète", lambda x: pct(x["best_year"], 1, True)), ("Pire année civile complète", lambda x: pct(x["worst_year"], 1, True)),
        ("Pire 5 ans (annualisé)", lambda x: pct(x["roll5_min"], 1, True)),
        ("Pire 10 ans (annualisé)", lambda x: pct(x["roll10_min"], 1, True)),
    ]
    same = st["start"] == sf["start"]
    mt = "".join(f'<tr><td>{l}</td><td class="num">{fn(st)}</td>' + ("" if same else f'<td class="num">{fn(sf)}</td>') + "</tr>"
                 for l, fn in metrics if l != "Début")
    mhead = (f'<th scope="col">Depuis {m_label(st["start"])}</th>' if same else
             f'<th scope="col">Période commune<span class="th-sub">depuis {m_label(st["start"])}</span></th>'
             f'<th scope="col">Historique complet<span class="th-sub">depuis {m_label(sf["start"])}</span></th>')
    return f"""
      {crumbs_html(sheet_crumbs(s))}
      <section class="sheet-head">
        <div class="byline">{fam_chip(s['family'])}<span>{e(s.get('author', ''))}</span></div>
        <h1>{e(s['name'])}</h1>
        <p class="lede">{e(s.get('note', ''))}</p>
        <p class="cmp-cta"><a href="/comparer/?s={s['id']},{compare_default(s, data)}">Comparer avec une autre stratégie →</a></p>
      </section>
      <div class="tiles">
        <div class="tile"><span class="k">CAGR</span><span class="v">{pct(st['cagr'])}</span>{cmp(pct(rst['cagr']))}</div>
        <div class="tile"><span class="k">Temps de récupération</span><span class="v">{uw(st)}</span>{cmp(uw(rst))}</div>
        <div class="tile"><span class="k">Max drawdown</span><span class="v neg">{pct(st['max_dd'])}</span>{cmp(pct(rst['max_dd']))}</div>
        <div class="tile"><span class="k">Pire année</span><span class="v">{pct(st['worst_year'], 1, True)}</span>{cmp(pct(rst['worst_year'], 1, True))}</div>
      </div>
      <div class="grid-2 sheet-grid"><div class="stack">
        {ess}
        <section class="panel" style="--o:5"><h2>Règles</h2><ol class="rules">{''.join(f'<li>{rich(r)}</li>' for r in rules_for(s))}</ol>{extra}</section>
      </div><div class="stack">
        <section class="panel" style="--o:2"><h2>Signal pour {m_long(nm)}</h2><p class="sub">Calculé sur la clôture de fin {m_long(data['data_end'])}.</p><div class="alloc">{sig}</div></section>
        {history_html(s)}
        {f'<section class="panel" style="--o:9"><h2>Avec des ETF européens</h2><div class="ucits-list">{ucits}</div></section>' if ucits else ''}
        <section class="panel" style="--o:10"><h2>Toutes les mesures</h2><table class="metrics"><thead><tr><th scope="col"></th>{mhead}</tr></thead><tbody>{mt}</tbody></table></section>
        {same_family_html(s, data)}
      </div></div>"""


def fam_chip(family: str) -> str:
    slug = FAM_SLUG.get(family)
    return (f'<a class="fam" href="/{slug}/">{e(family)}</a>' if slug
            else f'<span class="fam">{e(family)}</span>')


def fam_links() -> str:
    if not FAMILLES:
        return ""
    return ('<p class="fam-links"><span>Par famille :</span> '
            + " · ".join(f'<a href="/{slug}/">{e(f["titre"])}</a>' for slug, f in FAMILLES.items()) + "</p>")


def same_family_html(s, data) -> str:
    others = [x for x in data["strategies"] if x["family"] == s["family"] and x["id"] != s["id"]]
    if not others:
        return ""
    slug = FAM_SLUG.get(s["family"])
    rows = "".join(
        f'<li><a href="/strategies/{x["id"]}/">{e(x["name"])}</a><span class="num">{pct(x["stats_common"]["cagr"])} /an · '
        f'{pct(x["stats_common"]["max_dd"])}</span></li>' for x in others)
    more = f'<a href="/{slug}/">Toute la famille « {e(FAMILLES[slug]["titre"])} »</a>' if slug else ""
    return (f'<section class="panel" style="--o:11"><h2>Même famille</h2><p class="sub">Rendement annuel et pire baisse sur la période commune.</p>'
            f'<ul class="kin">{rows}</ul>{more}</section>')


def alloc_text(w: dict) -> str:
    """{'SPY': .6, 'AGG': .4} -> « 60 % SPY · 40 % AGG » ; poids égaux regroupés."""
    groups: dict = {}
    for k, v in w.items():
        groups.setdefault(round(v, 3), []).append("Cash" if k == "CASH" else k)
    parts = []
    for v, ks in sorted(groups.items(), key=lambda kv: -kv[0]):
        ks = sorted(ks, key=lambda k: (k == "Cash", k))
        parts.append(f"{weight_text(v)} {ks[0]}" if len(ks) == 1 else f"{weight_text(v)} chacun : {', '.join(ks)}")
    return " · ".join(parts)


def same_weights(a: dict, b: dict) -> bool:
    return all(abs(a.get(k, 0) - b.get(k, 0)) < 0.005 for k in set(a) | set(b))


def signal_since(s) -> str | None:
    """Premier mois de la série ininterrompue du signal actuel ("long" : toute la fenêtre de 13 mois)."""
    h = s.get("signal_history") or {}
    months = sorted(h)
    if not months:
        return None
    cur, since = s["next_signal"]["weights"], None
    for m in reversed(months):
        if not same_weights(h[m], cur):
            break
        since = m
    return "long" if since == months[0] else since


def signals_html(data) -> str:
    nm = data["strategies"][0]["next_signal"]["for_month"]
    tactical = [s for s in data["strategies"] if s["family"] not in ("Statique", "Référence")]
    fixed = [s for s in data["strategies"] if s["family"] == "Statique"]
    changed, same = [], []
    for s in tactical:
        h = s.get("signal_history") or {}
        months = sorted(h)
        prev = h[months[-2]] if len(months) >= 2 else None
        (changed if prev is not None and not same_weights(prev, s["next_signal"]["weights"]) else same).append((s, prev))
    order = lambda lst: sorted(lst, key=lambda x: (x[0]["family"], x[0]["name"]))

    def card(s, prev):
        return (f'<li class="sig-card"><div class="sig-head"><a href="/strategies/{s["id"]}/">{e(s["name"])}</a>{fam_chip(s["family"])}</div>'
                f'<div class="sig-row now"><span class="lab">Nouveau</span>'
                f'<span class="alloc-txt">{e(alloc_text(s["next_signal"]["weights"]))}</span></div>'
                f'<div class="sig-row before"><span class="lab">Avant</span><span class="alloc-txt">{e(alloc_text(prev))}</span></div></li>')

    def row(s):
        since = signal_since(s)
        stxt = "depuis plus d'un an" if since == "long" else f"depuis {m_label(since)}" if since else ""
        return (f'<tr><td><a href="/strategies/{s["id"]}/">{e(s["name"])}</a><div class="s-meta">{fam_chip(s["family"])}</div></td>'
                f'<td class="alloc-txt">{e(alloc_text(s["next_signal"]["weights"]))}</td><td class="since">{stxt}</td></tr>')

    n_ch, n_t = len(changed), len(tactical)
    lead = (f"<b>{n_ch} stratégie{'s' if n_ch > 1 else ''} sur {n_t}</b> change{'nt' if n_ch > 1 else ''} d'allocation pour {m_long(nm)}."
            if n_ch else f"Aucune des {n_t} stratégies actives ne change d'allocation pour {m_long(nm)}.")
    ch_html = (f'<section class="sig-sec"><h2>Ce qui change</h2><ul class="sig-cards">'
               f'{"".join(card(s, p) for s, p in order(changed))}</ul></section>' if changed else "")
    rebal = ("<b>C'est le mois du rééquilibrage annuel</b> : on revient aux poids cibles." if nm.endswith("-01")
             else "Rééquilibrage une fois par an, fin décembre.")
    fixed_li = "".join(f'<li><a href="/strategies/{s["id"]}/">{e(s["name"])}</a>'
                       f'<span class="alloc-txt">{e(alloc_text(s["next_signal"]["weights"]))}</span></li>'
                       for s in sorted(fixed, key=lambda s: s["name"]))
    return f"""
      <section class="doc">
        <h1>Signaux des stratégies ETF pour {m_long(nm)}</h1>
        <p class="lede">{lead} Signaux calculés sur les cours de clôture de fin {m_long(data['data_end'])}, à appliquer au début du mois.</p>
      </section>
      {ch_html}
      <section class="sig-sec"><h2>{"Sans changement" if changed else "Allocations du mois"}</h2>
        <div class="table-scroll"><table class="sig-table"><thead><tr><th scope="col">Stratégie</th><th scope="col">Allocation</th><th scope="col">Inchangée</th></tr></thead>
        <tbody>{"".join(row(s) for s, _ in order(same))}</tbody></table></div></section>
      <section class="sig-sec"><h2>Portefeuilles fixes</h2>
        <p class="sub">Pas de signal : l'allocation ne change jamais. {rebal}</p>
        <ul class="fixed-list">{fixed_li}</ul>
      </section>
      <p class="note-under">Les signaux sont calculés avec les ETF américains ; les <a href="/equivalents-ucits/">équivalents UCITS</a> permettent de les appliquer depuis l'Europe. Ils découlent de règles publiques appliquées mécaniquement : ce ne sont pas des conseils en investissement.</p>"""


def family_html(slug, fam, data, ref) -> str:
    members = sorted([s for s in data["strategies"] if s["family"] == fam["famille"]],
                     key=lambda s: -(s["stats_common"]["sharpe"] or -9))
    rs = ref["stats_common"]
    nm = data["strategies"][0]["next_signal"]["for_month"]
    fixed = fam["famille"] == "Statique"

    def tr(s, is_ref=False):
        st = s["stats_common"]
        sig = "" if is_ref else ("Allocation fixe" if fixed else alloc_text(s["next_signal"]["weights"]))
        return (f'<tr class="{"is-bench" if is_ref else ""}"><td><a class="s-link" href="/strategies/{s["id"]}/">{e(s["name"])}</a></td>'
                f'<td class="num">{pct(st["cagr"])}</td><td class="num neg">{pct(st["max_dd"])}</td><td class="num">{uw(st)}</td>'
                f'<td class="num">{dec(st["sharpe"])}</td><td class="alloc-txt">{e(sig)}</td></tr>')

    c0, c1 = data["common_window"]
    others = " · ".join(f'<a href="/{k}/">{e(f["titre"])}</a>' for k, f in FAMILLES.items() if k != slug)
    return f"""
      {crumbs_html([("/", "Stratégies"), (None, fam["titre"])])}
      <section class="doc">
        <h1>{e(fam["h1"])}</h1>
        {"".join(f"<p>{rich(x)}</p>" for x in fam["intro"])}
      </section>
      <div class="table-scroll" style="margin-top:22px"><table class="fam-table">
        <thead><tr><th scope="col">Stratégie</th><th scope="col">CAGR</th><th scope="col">Max DD</th><th scope="col">Récup.</th><th scope="col">Sharpe</th><th scope="col">Signal {e(m_label(nm))}</th></tr></thead>
        <tbody>{"".join(tr(s) for s in members)}{tr(ref, True)}</tbody></table></div>
      <p class="note-under">Période commune de {m_label(c0)} à {m_label(c1)}, frais inclus, du meilleur au moins bon Sharpe. Dernière ligne, pour comparaison : {"les actions mondiales" if ref["id"] == "acwi" else "le S&amp;P 500"} ({pct(rs["cagr"])} par an, pire baisse {pct(rs["max_dd"])}).</p>
      <section class="doc">
        <h2>Ce qu'il faut savoir</h2>
        <ul>{"".join(f"<li>{rich(x)}</li>" for x in fam["a_savoir"])}</ul>
        <h2>Les autres familles</h2>
        <p>{others}</p>
      </section>"""


def compare_default(s, data) -> str:
    kin = [x for x in data["strategies"] if x["family"] == s["family"] and x["id"] != s["id"]]
    if kin:
        return kin[0]["id"]
    return "acwi" if s["id"] != "acwi" and any(x["id"] == "acwi" for x in data["strategies"]) else "spy" if s["id"] != "spy" else "6040"


def crumbs_html(items) -> str:
    """items : [(url ou None, texte)] ; le dernier est la page courante."""
    parts = [f'<a href="{u}">{e(t)}</a>' if u else f'<span aria-current="page">{e(t)}</span>' for u, t in items]
    return ('<nav class="crumbs" aria-label="Fil d\'Ariane">'
            + '<span class="sep" aria-hidden="true">›</span>'.join(parts) + "</nav>")


def crumbs_ld(items, base_url) -> dict:
    return {"@context": "https://schema.org", "@type": "BreadcrumbList", "itemListElement": [
        {"@type": "ListItem", "position": k + 1, "name": t, **({"item": base_url + u} if u else {})}
        for k, (u, t) in enumerate(items)]}


def sheet_crumbs(s) -> list:
    slug = FAM_SLUG.get(s["family"])
    return [("/", "Stratégies")] + ([(f"/{slug}/", FAMILLES[slug]["titre"])] if slug else []) + [(None, s["name"])]


def history_html(s) -> str:
    if s["family"] in ("Statique", "Référence"):
        return ""
    h = s.get("signal_history") or {}
    ms = sorted(h, reverse=True)
    if len(ms) < 2:
        return ""
    rows, n = [], 0
    for k, m in enumerate(ms):
        prev = h[ms[k + 1]] if k + 1 < len(ms) else None
        ch = prev is not None and not same_weights(h[m], prev)
        n += ch
        rows.append(f'<tr class="{"chg" if ch else ""}"><td>{m_label(m)}</td><td class="alloc-txt">{e(alloc_text(h[m]))}</td></tr>')
    lead = f"{n} changement{'s' if n > 1 else ''}" if n else "Aucun changement"
    return (f'<section class="panel" style="--o:4"><h2>Historique des signaux</h2><p class="sub">{lead} sur les {len(ms) - 1} derniers mois. '
            f"En gras : le mois où l'allocation a changé.</p><table class=\"hist\"><thead><tr><th scope=\"col\">Mois</th>"
            f'<th scope="col">Allocation</th></tr></thead><tbody>{"".join(rows)}</tbody></table></section>')


# --------------------------------------------------------------------------
# Comparaisons
# --------------------------------------------------------------------------
CMP_COLORS = ["var(--accent)", "var(--pub)", "var(--pos)"]


def pair_slug(c) -> str:
    return c.get("slug") or f'{c["a"]}-ou-{c["b"]}'.replace("_", "-")


def aligned(ss, start):
    """Séries d'équité des stratégies ss, base 1 juste avant le premier mois où toutes existent."""
    keys = sorted(set.intersection(*[set(s["equity"]) for s in ss]))
    keys = [k for k in keys if k >= start]
    out = []
    for s in ss:
        base = s["equity"].get(prev_month(keys[0]), 1.0)   # absent : premier mois de la stratégie
        out.append([(k, s["equity"][k] / base) for k in keys])
    return keys, out


def prev_month(p: str) -> str:
    y, m = map(int, p.split("-"))
    return f"{y - (m == 1)}-{12 if m == 1 else m - 1:02d}"


def svg_equity(series, names, width=760, height=280) -> str:
    """Graphique statique (échelle log) : croissance de 1 $ pour chaque série."""
    import math
    m = {"t": 12, "r": 14, "b": 26, "l": 48}
    allv = [v for s in series for _, v in s] + [1.0]
    lo, hi = math.log(min(allv)), math.log(max(allv))
    pad = (hi - lo) * 0.06 or 0.1
    lo, hi = lo - pad, hi + pad
    months = [k for k, _ in series[0]]
    n = len(months)
    X = lambda i: m["l"] + i / max(n - 1, 1) * (width - m["l"] - m["r"])
    Y = lambda v: m["t"] + (1 - (math.log(v) - lo) / (hi - lo)) * (height - m["t"] - m["b"])
    out = [f'<svg viewBox="0 0 {width} {height}" role="img" aria-label="Croissance de 1 $ : {e(" / ".join(names))}">']
    for v in [0.5, 0.75, 1, 1.5, 2, 3, 4, 5, 6, 8, 10, 15, 20]:
        if lo <= math.log(v) <= hi:
            y = Y(v)
            out.append(f'<line x1="{m["l"]}" x2="{width - m["r"]}" y1="{y:.1f}" y2="{y:.1f}" stroke="var(--rule{"" if v == 1 else "-soft"})"/>'
                       f'<text x="{m["l"] - 8}" y="{y + 3.5:.1f}" text-anchor="end" class="ax">{num(v, 2 if v < 1 else 1 if v % 1 else 0)} $</text>')
    years = sorted({k[:4] for k in months})
    step = 5 if len(years) > 24 else 2 if len(years) > 12 else 1
    for i, k in enumerate(months):
        if k.endswith("-01") and int(k[:4]) % step == 0 and 10 < X(i) < width - 10:
            out.append(f'<text x="{X(i):.1f}" y="{height - 8}" text-anchor="middle" class="ax">{k[:4]}</text>')
    for s, color in reversed(list(zip(series, CMP_COLORS))):
        d = "".join(f'{"L" if i else "M"}{X(i):.1f},{Y(v):.1f}' for i, (_, v) in enumerate(s))
        out.append(f'<path d="{d}" fill="none" stroke="{color}" stroke-width="2" stroke-linejoin="round" vector-effect="non-scaling-stroke"/>')
    out.append("</svg>")
    return "".join(out)


def mini(series):
    """Statistiques d'une série (mois, valeur base 1) : CAGR, volatilité, pire baisse, pire année."""
    import statistics
    vals = [v for _, v in series]
    rets = [vals[0] - 1] + [vals[i] / vals[i - 1] - 1 for i in range(1, len(vals))]
    n = len(rets)
    cagr = vals[-1] ** (12 / n) - 1
    vol = statistics.stdev(rets) * 12 ** 0.5 if n > 2 else None
    peak, mdd, run, best, ongoing = 1.0, 0.0, 0, 0, False
    for v in vals:
        if v >= peak - 1e-12:
            best, peak, run = max(best, run), v, 0
        else:
            run += 1
        mdd = min(mdd, v / peak - 1)
    if run > best:
        best, ongoing = run, True
    years: dict = {}
    for (k, _), r in zip(series, rets):
        g = years.setdefault(k[:4], [1.0, 0])
        g[0] *= 1 + r
        g[1] += 1
    full = {y: g[0] - 1 for y, g in years.items() if g[1] == 12}
    return {"cagr": cagr, "vol": vol, "max_dd": mdd, "uw": best, "uw_ongoing": ongoing, "worst_year": min(full.values()) if full else None,
            "years": {y: (g[0] - 1, g[1] == 12) for y, g in years.items()}}


def pair_html(c, data, by_id) -> str:
    ss = [by_id[c["a"]], by_id[c["b"]]]
    c0 = data["common_window"][0]
    months, series = aligned(ss, c0)
    st = [mini(s) for s in series]
    nm = data["strategies"][0]["next_signal"]["for_month"]
    head = "".join(f'<th scope="col"><i class="sw" style="background:{CMP_COLORS[k]}"></i>'
                   f'<a href="/strategies/{s["id"]}/">{e(s["name"])}</a></th>' for k, s in enumerate(ss))

    def row(label, f):
        return f'<tr><th scope="row">{label}</th>{"".join(f"<td class=num>{f(x, s)}</td>" for x, s in zip(st, ss))}</tr>'

    sig = lambda x, s: (f'<span class="alloc-txt">{e("Allocation fixe" if s["family"] == "Statique" else alloc_text(s["next_signal"]["weights"]))}</span>')
    rows = (row("Rendement annuel", lambda x, s: pct(x["cagr"]))
            + row("Volatilité", lambda x, s: pct(x["vol"]))
            + row("Pire baisse", lambda x, s: f'<span class="neg">{pct(x["max_dd"])}</span>')
            + row("Plus longue période sous l'eau", lambda x, s: f'{x["uw"]}{"+" if x["uw_ongoing"] else ""}{NBSP}mois')
            + row("Pire année", lambda x, s: pct(x["worst_year"], 1, True))
            + row(f"Signal {m_label(nm)}", sig))
    yrs = sorted(st[0]["years"], reverse=True)
    yrows = "".join(
        f'<tr><td>{y}{"*" if not all(x["years"][y][1] for x in st) else ""}</td>'
        + "".join(f'<td class="num{" neg" if x["years"][y][0] < 0 else ""}">{pct(x["years"][y][0], 1, True)}</td>' for x in st)
        + "</tr>" for y in yrs)
    others = [x for x in COMPARAISONS if x is not c][:4]
    return f"""
      {crumbs_html([("/", "Stratégies"), ("/comparer/", "Comparer"), (None, c["titre"])])}
      <section class="doc">
        <h1>{e(c["titre"])}</h1>
        {"".join(f"<p>{rich(x)}</p>" for x in c["intro"])}
      </section>
      <p class="sub cmp-period" style="margin-top:18px">De {m_label(months[0])} à {m_label(months[-1])}, frais inclus, en dollars.</p>
      <div class="table-scroll"><table class="cmp-table"><thead><tr><th scope="col"></th>{head}</tr></thead><tbody>{rows}</tbody></table></div>
      <div class="grid-2 cmp-grid"><div class="stack">
        <section class="panel"><h2>Croissance de 1 $</h2>
          <div class="legend">{"".join(f'<span><i style="background:{CMP_COLORS[k]}"></i>{e(s["name"])}</span>' for k, s in enumerate(ss))}</div>
          <div class="chart static-chart">{svg_equity(series, [s["name"] for s in ss])}</div></section>
        <section class="panel"><h2>Ce qui les distingue</h2><ul class="doc-list">{"".join(f"<li>{rich(x)}</li>" for x in c["points"])}</ul>
          <p style="margin:0"><a href="/comparer/?s={c["a"]},{c["b"]}">Ouvrir dans le comparateur</a> (en euros, sur d'autres périodes ou avec une troisième stratégie)</p></section>
      </div><div class="stack">
        <section class="panel"><h2>Rendement par année</h2>
          <table class="metrics cmp-years"><thead><tr><th scope="col"></th>{"".join(f'<th scope="col"><i class="sw" style="background:{CMP_COLORS[k]}"></i></th>' for k in range(2))}</tr></thead><tbody>{yrows}</tbody></table>
          <p class="sub" style="margin:0">* année incomplète, non retenue pour la « pire année ».</p></section>
      </div></div>
      <section class="doc"><h2>Autres comparaisons</h2><p>{" · ".join(f'<a href="/comparer/{pair_slug(x)}/">{e(x["titre"])}</a>' for x in others)}</p></section>
      <p class="note-under">Backtests sur des ETF américains, dividendes réinvestis, avant impôts. Les performances passées ne préjugent pas des performances futures.</p>"""


def compare_index_html(data) -> str:
    items = "".join(f'<li><a href="/comparer/{pair_slug(c)}/">{e(c["titre"])}</a></li>' for c in COMPARAISONS)
    return f"""
      {crumbs_html([("/", "Stratégies"), (None, "Comparer")])}
      <section class="doc">
        <h1>Comparer des stratégies</h1>
        <p class="lede">Choisissez deux ou trois stratégies : courbes, pires baisses et années côte à côte, sur la période où toutes sont disponibles.</p>
      </section>
      <div id="cmp-tool"><noscript><p>Le comparateur a besoin de JavaScript. Les comparaisons ci-dessous restent lisibles sans.</p></noscript></div>
      <section class="sig-sec"><h2>Comparaisons détaillées</h2><ul class="cmp-list">{items}</ul></section>"""


def strip_tags(h: str) -> str:
    return re.sub(r"<[^>]+>", "", h)


def ucits_html(data, uc) -> str:
    order = [t for t in ["ACWI", "SPY", "IVV", "IVE", "VTI", "QQQ", "IWM", "IWN", "EFA", "VEA", "ACWX", "VGK", "EWJ", "SCZ",
                         "EEM", "VWO", "VNQ", "RWX", "REM", "GLD", "DBC", "GSG", "TLT", "IEF", "SHY", "SHV", "BIL",
                         "TIP", "AGG", "BND", "LQD", "HYG", "BWX", "XLB", "XLE", "XLF", "XLI", "XLK", "XLP", "XLU",
                         "XLV", "XLY"] if t in uc["map"]]
    rows = []
    for t in order:
        m = uc["map"][t]
        funds = "".join(
            f'<div class="fund"><div class="fname">{e(f["name"])}</div><div class="fmeta">'
            f'<span class="part"><span class="lab">ISIN</span><span class="isin">{f["isin"]}</span></span><span class="sep"> · </span>'
            f'<span class="part"><span class="lab">Cotations</span>{e(f["tickers"])}</span><span class="sep"> · </span>'
            f'<span class="part"><span class="lab">Frais</span><span class="num">{num(f["ter"], 2)}{NBSP}%</span> par an</span></div></div>'
            for f in (uc["_funds"][k] for k in m["funds"])) or "—"
        note = f'<div class="unote">{e(m["note"])}</div>' if m.get("note") else ""
        rows.append(f'<tr><td><span class="us">{t}</span><div class="fmeta">{e(data["etf_names"].get(t, ""))}</div></td>'
                    f'<td><span class="match {m["match"]}">{MATCH[m["match"]]}</span></td><td>{funds}{note}</td></tr>')
    return f"""
      <section class="doc">
        <h1>Équivalents UCITS des ETF américains</h1>
        <p class="lede">Depuis 2018, la réglementation européenne (PRIIPs) empêche les particuliers d'acheter la plupart des ETF américains. Les stratégies de ce site restent applicables avec des ETF domiciliés en Europe, dits UCITS. Cette table donne, pour chaque ETF utilisé, l'équivalent le plus proche.</p>
        <p><span class="match meme">même indice</span> même indice ou quasi identique · <span class="match proche">proche</span> même classe d'actifs, indice différent · <span class="match aucun">aucun</span> pas d'équivalent satisfaisant</p>
      </section>
      <div class="table-scroll" style="margin-top:18px"><table class="ucits">
        <thead><tr><th scope="col">ETF US</th><th scope="col">Correspondance</th><th scope="col">Équivalent UCITS</th></tr></thead>
        <tbody>{''.join(rows)}</tbody></table></div>
      <p class="note-under">ISIN, tickers et frais vérifiés sur justETF. Plusieurs cotations existent pour chaque fonds (devise, bourse) : vérifiez celle proposée par votre courtier. Cette table n'est pas une recommandation d'achat.</p>"""


def method_html(data) -> str:
    frag = (SITE / "content" / "methode.html").read_text(encoding="utf-8")
    c0, c1 = data["common_window"]
    return (frag.replace("{{C0}}", m_label(c0)).replace("{{C1}}", m_label(c1))
            .replace("{{COST}}", num(data["cost_per_trade"] * 100, 2)))


def legal_html(cfg) -> str:
    ed = cfg.get("editeur", {})
    nom = e(ed.get("nom", ""))
    if nom and ed.get("lien"):
        nom = f'<a href="{e(ed["lien"])}" rel="noopener">{nom}</a>'
    lines = [f"<b>{nom}</b>" if nom else ""]
    if ed.get("adresse"):
        lines.append(e(ed["adresse"]))
    if ed.get("contact"):
        c = ed["contact"]
        lines.append(f'Contact : <a href="mailto:{e(c)}">{e(c)}</a>' if "@" in c and not c.startswith("http")
                     else f'Contact : <a href="{e(c)}">{e(c)}</a>')
    editeur = "<br>".join(x for x in lines if x)
    return f"""
      <section class="doc">
        <h1>Mentions légales</h1>
        <h2>Éditeur</h2>
        <p>{editeur}<br>Site personnel, gratuit, sans publicité ni produit à vendre.</p>
        <h2>Hébergement</h2>
        <p>Netlify, Inc., 101 2nd Street, San Francisco, CA 94105, États-Unis (<a href="https://www.netlify.com">netlify.com</a>).</p>
        <h2>Données personnelles et cookies</h2>
        <p>Ce site ne dépose aucun cookie et ne demande aucune donnée personnelle. La fréquentation est mesurée avec <a href="https://www.goatcounter.com">GoatCounter</a>, un outil de statistiques sans cookie qui ne conserve ni adresse IP ni identifiant : il compte les pages vues, les sites d'origine, la taille d'écran et le pays. Les polices de caractères sont hébergées sur le site lui-même. Comme tout hébergeur, Netlify peut conserver des journaux techniques (dont l'adresse IP) pour assurer la sécurité du service.</p>
        <p>Une préférence d'affichage (la référence choisie, actions mondiales ou S&amp;P 500) est enregistrée dans votre navigateur. Elle ne quitte pas votre appareil.</p>
        <h2>Avertissement</h2>
        <p>Les informations de ce site sont fournies à titre éducatif et général. Elles ne constituent ni un conseil en investissement, ni une recommandation personnalisée, ni une offre d'achat ou de vente d'un instrument financier. Les résultats sont des simulations (backtests) calculées sur des données passées, avant impôts : les performances passées ne préjugent pas des performances futures. Vérifiez toute information auprès de sources officielles avant de prendre une décision.</p>
        <h2>Sources et crédits</h2>
        <p>Cours ajustés via yfinance (Yahoo Finance), contrôlés contre les valeurs liquidatives publiées par iShares ; taux des T-bills : Réserve fédérale (FRED). Les stratégies présentées ont été publiées par leurs auteurs respectifs, cités sur chaque fiche. Polices IBM Plex, sous licence SIL Open Font License.</p>
      </section>"""


def clip(t: str, n=160) -> str:
    return t if len(t) <= n else t[: n - 1].rsplit(" ", 1)[0].rstrip(" .,;:") + "…"


# --------------------------------------------------------------------------
# Construction
# --------------------------------------------------------------------------
def build(root: Path = ROOT) -> list[str]:
    cfg = json.loads(CONFIG.read_text(encoding="utf-8")) if CONFIG.exists() else {
        "site_url": "https://laboetf.eu"}
    data = json.loads((SITE / "strategies.json").read_text(encoding="utf-8"))
    fiches = json.loads((SITE / "fiches.json").read_text(encoding="utf-8")) if (SITE / "fiches.json").exists() else {}
    uc = json.loads((SITE / "ucits.json").read_text(encoding="utf-8")) if (SITE / "ucits.json").exists() else None
    head_tpl, body_tpl = split_template(TEMPLATE.read_text(encoding="utf-8"))
    fam_file = SITE / "content" / "familles.json"
    FAMILLES.clear()
    FAM_SLUG.clear()
    if fam_file.exists():
        present = {s["family"] for s in data["strategies"]}
        for slug, f in json.loads(fam_file.read_text(encoding="utf-8")).items():
            if not slug.startswith("_") and f["famille"] in present:
                FAMILLES[slug] = f
                FAM_SLUG[f["famille"]] = slug
    cmp_file = SITE / "content" / "comparaisons.json"
    COMPARAISONS.clear()
    if cmp_file.exists():
        ids = {s["id"] for s in data["strategies"]}
        COMPARAISONS.extend(c for c in json.loads(cmp_file.read_text(encoding="utf-8"))["comparaisons"]
                            if c["a"] in ids and c["b"] in ids)
    by_id = {s["id"]: s for s in data["strategies"]}
    KNOWN_IDS.clear()
    KNOWN_IDS.update(by_id)
    ref = by_id.get("acwi") or by_id["spy"]
    c0 = data["common_window"][0]
    stamp = f"Données à fin {m_long(data['data_end'])} · {sum(s['id'] not in REF_NAMES for s in data['strategies'])} stratégies"
    base_url = cfg["site_url"].rstrip("/")
    written = []

    def write(rel: str, text: str):
        out = SITE / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(text, encoding="utf-8")
        written.append(rel)

    common = dict(cfg=cfg, stamp=stamp)
    n = len([s for s in data["strategies"] if s["id"] not in REF_NAMES])
    write("index.html", page(head_tpl, body_tpl, path="", nav="", content=board_html(data, ref),
                             title="Labo ETF : les stratégies ETF backtestées et comparées",
                             desc=clip(f"{n} stratégies d'investissement en ETF (Permanent Portfolio, Dual Momentum, "
                                       f"stratégies de Keller…) testées depuis {m_label(c0)} avec les mêmes données : "
                                       "rendement, pire baisse, signal du mois."),
                             jsonld={"@context": "https://schema.org", "@type": "WebSite", "name": "Labo ETF",
                                     "url": base_url + "/", "inLanguage": "fr"}, **common))
    for s in data["strategies"]:
        st = s["stats_common"]
        month = m_long(s["next_signal"]["for_month"])
        desc = (f"{s.get('note', s['name'])}. Depuis {m_label(st['start'])} : {pct(st['cagr'])} par an, "
                f"pire baisse {pct(st['max_dd'])}.")
        tail = " Règles, signal du mois, équivalents UCITS."
        desc = clip(desc + tail if len(desc + tail) <= 160 else desc)
        write(f"strategies/{s['id']}/index.html",
              page(head_tpl, body_tpl, path=f"strategies/{s['id']}/", nav="", og_type="article",
                   content=sheet_html(s, data, fiches, uc, ref), image=s["id"],
                   title=f"{s['name']} : backtest, règles et signal du mois | Labo ETF", desc=desc,
                   jsonld=[{"@context": "https://schema.org", "@type": "WebPage", "name": s["name"],
                            "description": desc, "inLanguage": "fr",
                            "isPartOf": {"@type": "WebSite", "name": "Labo ETF", "url": base_url + "/"}},
                           crumbs_ld(sheet_crumbs(s), base_url)],
                   **common))
    if uc:
        write("equivalents-ucits/index.html",
              page(head_tpl, body_tpl, path="equivalents-ucits/", nav="ucits", content=ucits_html(data, uc),
                   title="Équivalents UCITS des ETF américains (ISIN, tickers, frais) | Labo ETF",
                   desc="Pour chaque ETF américain (SPY, TLT, GLD, QQQ…), l'équivalent UCITS accessible en Europe : "
                        "ISIN, cotations, frais et niveau de correspondance.", **common))
    nm = data["strategies"][0]["next_signal"]["for_month"]
    write("signaux/index.html",
          page(head_tpl, body_tpl, path="signaux/", nav="signaux", static=True, content=signals_html(data),
               title=f"Signaux des stratégies ETF pour {m_long(nm)} (GEM, DAA, VAA…) | Labo ETF",
               desc=clip(f"Les allocations {de(m_long(nm))} de toutes les stratégies ETF du site : ce qui change, ce qui "
                         "reste en place, calculé sur la dernière clôture mensuelle."), **common))
    for slug, fam in FAMILLES.items():
        write(f"{slug}/index.html",
              page(head_tpl, body_tpl, path=f"{slug}/", nav="none", static=True,
                   content=family_html(slug, fam, data, ref),
                   title=f"{fam['titre']} : stratégies backtestées et comparées | Labo ETF",
                   desc=clip(fam["description"]),
                   jsonld=crumbs_ld([("/", "Stratégies"), (None, fam["titre"])], base_url), **common))
    # comparateur et pages « X ou Y ? »
    write("comparer/index.html",
          page(head_tpl, body_tpl, path="comparer/", nav="comparer", content=compare_index_html(data),
               title="Comparer des stratégies ETF : courbes, baisses et années côte à côte | Labo ETF",
               desc="Comparez deux ou trois stratégies ETF (GEM, Permanent Portfolio, DAA…) : rendement, pire baisse, "
                    "années, en dollars ou en euros.",
               jsonld=crumbs_ld([("/", "Stratégies"), (None, "Comparer")], base_url), **common))
    for c in COMPARAISONS:
        slug = pair_slug(c)
        sa, sb = by_id[c["a"]], by_id[c["b"]]
        write(f"comparer/{slug}/index.html",
              page(head_tpl, body_tpl, path=f"comparer/{slug}/", nav="none", static=True,
                   content=pair_html(c, data, by_id),
                   title=f"{c['titre']} Backtest et comparaison | Labo ETF",
                   desc=clip(f"{sa['name']} ou {sb['name']} : rendement, pire baisse, années et règles comparés "
                             "sur les mêmes données."),
                   jsonld=crumbs_ld([("/", "Stratégies"), ("/comparer/", "Comparer"), (None, c["titre"])], base_url),
                   **common))
    if not (SITE / "content" / "methode.html").exists():
        print("⚠️  site/content/methode.html introuvable : page Méthode non générée.")
    else:
        write("methode/index.html",
              page(head_tpl, body_tpl, path="methode/", nav="methode", content=method_html(data),
                   title="Méthode et limites des backtests | Labo ETF",
                   desc="Données, conventions de calcul, période commune, mesures et limites des backtests "
                        "de Labo ETF.", **common))
    if not cfg.get("editeur", {}).get("contact"):
        print("⚠️  Mentions légales : ajoute un contact (e-mail ou lien) dans site_config.json, rubrique editeur.")
    write("mentions-legales/index.html",
          page(head_tpl, body_tpl, path="mentions-legales/", nav="none", static=True, content=legal_html(cfg),
               title="Mentions légales | Labo ETF",
               desc="Éditeur, hébergeur, données personnelles et avertissement de Labo ETF.", **common))
    write("404.html",
          page(head_tpl, body_tpl, path="404.html", nav="", noindex=True,
               content='<section class="doc"><h1>Page introuvable</h1><p class="lede">Cette adresse n\'existe pas '
                       '(ou plus). <a href="/">Voir toutes les stratégies</a>.</p></section>',
               title="Page introuvable | Labo ETF", desc="Page introuvable.", **common).replace(
                   '<script>window.ESL_BASE = "/";</script>', '<script>window.ESL_BASE = "/"; window.ESL_404 = true;</script>'))
    try:
        import og_images
        written += og_images.build(data, SITE, cfg.get("site_name") or "Labo ETF")
    except ImportError as err:  # matplotlib absent : pages sans image
        print(f"⚠️  Images d'aperçu non générées ({err})")
    today = dt.date.today().isoformat()
    urls = ["", "signaux/", "equivalents-ucits/", "methode/"] + [f"{k}/" for k in FAMILLES] + ["comparer/"] + [f"comparer/{pair_slug(c)}/" for c in COMPARAISONS] + [f"strategies/{s['id']}/" for s in data["strategies"]]
    write("sitemap.xml", '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
          + "".join(f"  <url><loc>{base_url}/{u}</loc><lastmod>{today}</lastmod></url>\n" for u in urls) + "</urlset>\n")
    write("robots.txt", f"User-agent: *\nAllow: /\n\nSitemap: {base_url}/sitemap.xml\n")
    return written


if __name__ == "__main__":
    files = build()
    print(f"{len(files)} fichiers générés dans site/ ({sum(f.endswith('index.html') for f in files)} pages)")
