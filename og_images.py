"""
og_images.py — images d'aperçu (1200 × 630) pour les réseaux sociaux.

  site/og/home.png        accueil, UCITS, méthode : nuage rendement / pire baisse
  site/og/<id>.png        une par stratégie : nom, chiffres clés, courbe face aux actions mondiales
  site/og/cmp-<slug>.png  une par comparaison « X ou Y ? » : les deux courbes et leurs chiffres clés

Appelé par build_site.py. Polices : assets/og-fonts (IBM Plex, licence OFL).
"""
from __future__ import annotations

import io
import textwrap
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
from matplotlib.font_manager import FontProperties  # noqa: E402
from PIL import Image  # noqa: E402

ROOT = Path(__file__).resolve().parent
FONTS = ROOT / "assets" / "og-fonts"
W, H, DPI = 1200, 630, 100
BRAND = "Labo ETF"

BG, INK, INK2, INK3, RULE = "#f3f5f1", "#17201b", "#4f5a54", "#7a847e", "#d8ddd5"
ACCENT, BENCH, NEG, PUB = "#2a78d6", "#8e9791", "#b6402e", "#9a6b00"


def _font(name, size):
    f = FONTS / f"{name}.ttf"
    return FontProperties(fname=str(f), size=size) if f.exists() else FontProperties(size=size)


def _canvas():
    fig = plt.figure(figsize=(W / DPI, H / DPI), dpi=DPI, facecolor=BG)
    # marque
    ax = fig.add_axes([60 / W, 1 - 92 / H, 34 / W, 34 / H])
    ax.set_xlim(0, 20); ax.set_ylim(0, 20); ax.axis("off")
    ax.add_patch(matplotlib.patches.FancyBboxPatch((1.2, 1.2), 17.6, 17.6, boxstyle="round,pad=0,rounding_size=3",
                                                   fill=False, ec=INK, lw=2.2))
    ax.plot([4, 8, 11, 16], [6, 10, 8, 15], color=ACCENT, lw=3, solid_capstyle="round", solid_joinstyle="round")
    fig.text(106 / W, 1 - 75 / H, BRAND, fontproperties=_font("ibm-plex-sans-600", 20), color=INK, va="center")
    return fig


def _save(fig, out: Path):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", dpi=DPI, facecolor=BG)
    plt.close(fig)
    buf.seek(0)
    img = Image.open(buf).convert("RGB").quantize(colors=96, method=Image.Quantize.MEDIANCUT)
    out.parent.mkdir(parents=True, exist_ok=True)
    img.save(out, optimize=True)


def _pct(v, sign=False):
    if v is None:
        return "—"
    s = f"{v * 100:.1f}".replace(".", ",")
    return ("+" if sign and v > 0 else "") + s + " %"


def _mlabel(p):
    mois = ["janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc."]
    y, m = p.split("-")[:2]
    return f"{mois[int(m) - 1]} {y}"


def strategy_image(s: dict, ref: dict, out: Path):
    fig = _canvas()
    st = s["stats_common"]
    fig.text(60 / W, 1 - 140 / H, s["family"].upper(), fontproperties=_font("ibm-plex-mono-500", 15), color=INK3)
    name = textwrap.fill(_nbsp(s["name"]), 34)
    lines = name.count("\n") + 1
    size = 50 if lines == 1 else 42
    fig.text(60 / W, 1 - 160 / H, name, fontproperties=_font("ibm-plex-sans-condensed-700", size), color=INK,
             va="top", linespacing=1.05)
    # chiffres clés
    y = 1 - (280 if lines == 1 else 330) / H
    for i, (k, v, c) in enumerate([("Rendement annuel", _pct(st["cagr"]), INK),
                                   ("Pire baisse", _pct(st["max_dd"]), NEG),
                                   ("Sous l'eau (max)", f"{st['underwater_months']} mois"
                                    if st.get("underwater_months") is not None else "—", INK)]):
        x = (60 + i * 250) / W
        fig.text(x, y, k, fontproperties=_font("ibm-plex-sans-400", 17), color=INK2)
        fig.text(x, y - 52 / H, v, fontproperties=_font("ibm-plex-mono-500", 34), color=c)
    legend = ("" if s["id"] == ref["id"] else " · courbe bleue : la stratégie, grise : "
              + ("actions mondiales" if ref["id"] == "acwi" else "S&P 500"))
    fig.text(60 / W, 36 / H, f"Backtest depuis {_mlabel(st['start'])}, frais inclus{legend}",
             fontproperties=_font("ibm-plex-sans-400", 15), color=INK3)
    # courbe (fenêtre commune, base 100, échelle log)
    start = st["start"]
    ax = fig.add_axes([840 / W, 80 / H, 320 / W, 380 / H] if lines > 1 else [800 / W, 80 / H, 360 / W, 400 / H])
    def series(x):
        keys = [k for k in x["equity"] if k >= start]
        v0 = x["equity"][keys[0]]
        return [x["equity"][k] / v0 * 100 for k in keys]
    a = series(s)
    if s["id"] != ref["id"]:
        b = series(ref)
        ax.plot(range(len(b)), b, color=BENCH, lw=2.2)
    ax.plot(range(len(a)), a, color=ACCENT, lw=3)
    ax.set_yscale("log")
    ax.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([]); ax.minorticks_off()
    ax.axhline(100, color=RULE, lw=1.2, zorder=0)
    _save(fig, out)


def home_image(data: dict, out: Path):
    fig = _canvas()
    strats = data["strategies"]
    n = len([s for s in strats if s["id"] not in ("acwi", "spy")])
    fig.text(60 / W, 1 - 128 / H, textwrap.fill("Les stratégies ETF connues, backtestées et comparées", 20),
             fontproperties=_font("ibm-plex-sans-condensed-700", 48), color=INK, va="top", linespacing=1.05)
    fig.text(60 / W, 1 - 375 / H, f"{n} stratégies, mêmes données, mêmes règles\ntestées depuis {_mlabel(data['common_window'][0])}",
        fontproperties=_font("ibm-plex-sans-400", 22), color=INK2, va="top", linespacing=1.3)
    fig.text(60 / W, 60 / H, "Rendement, pire baisse, temps de récupération et signal du mois",
             fontproperties=_font("ibm-plex-sans-400", 17), color=INK3)
    ax = fig.add_axes([790 / W, 110 / H, 360 / W, 400 / H])
    for s in strats:
        st = s["stats_common"]
        ref = s["id"] in ("acwi", "spy")
        ax.scatter(st["max_dd"] * 100, st["cagr"] * 100, s=130 if ref else 90,
                   color=BENCH if ref else ACCENT, alpha=1 if ref else .8, edgecolors="white", linewidths=1.2)
    ax.set_facecolor(BG)
    for k in ("top", "right"):
        ax.spines[k].set_visible(False)
    for k in ("left", "bottom"):
        ax.spines[k].set_color(RULE)
    ax.tick_params(colors=INK3, labelsize=12)
    for lab in ax.get_xticklabels() + ax.get_yticklabels():
        lab.set_fontproperties(_font("ibm-plex-mono-500", 12))
    ax.set_xlabel("Pire baisse (%)", fontproperties=_font("ibm-plex-sans-400", 14), color=INK2)
    ax.set_ylabel("Rendement annuel (%)", fontproperties=_font("ibm-plex-sans-400", 14), color=INK2)
    _save(fig, out)


def _nbsp(x: str) -> str:
    """Espaces insécables devant : ? ! (pas de ponctuation rejetée en début de ligne)."""
    return x.replace(" :", "\u00a0:").replace(" ?", "\u00a0?").replace(" !", "\u00a0!")


def pair_image(c: dict, slug: str, by_id: dict, start: str, out: Path, short: dict | None = None):
    """Comparaison « X ou Y ? » : titre, deux courbes (base 100, échelle log) et chiffres clés."""
    fig = _canvas()
    a, b = by_id[c["a"]], by_id[c["b"]]
    short = short or {}
    title = textwrap.fill(_nbsp(c["titre"]), 26)
    lines = title.count("\n") + 1
    fig.text(60 / W, 1 - 128 / H, title, fontproperties=_font("ibm-plex-sans-condensed-700", 46 if lines < 3 else 40),
             color=INK, va="top", linespacing=1.05)
    keys = sorted(set(a["equity"]) & set(b["equity"]))
    keys = [k for k in keys if k >= start]          # mois détenus, base juste avant le premier

    def curve(s):
        eq = s["equity"]
        base = eq.get(prev_month(keys[0]), 1.0)     # absent : premier mois de la stratégie
        return [1.0] + [eq[k] / base for k in keys]

    y = 1 - (330 if lines < 3 else 380) / H
    for i, (s, col) in enumerate([(a, ACCENT), (b, PUB)]):
        v = curve(s)
        cagr = v[-1] ** (12 / len(keys)) - 1
        dd, peak = 0.0, 1.0
        for x in v:
            peak = max(peak, x); dd = min(dd, x / peak - 1)
        yy = y - i * 105 / H
        fig.text(60 / W, yy, textwrap.shorten(short.get(s["id"], s["name"]), 40, placeholder="…"),
                 fontproperties=_font("ibm-plex-sans-600", 19), color=col)
        fig.text(60 / W, yy - 44 / H, f"{_pct(cagr)} par an   pire baisse {_pct(dd)}",
                 fontproperties=_font("ibm-plex-mono-500", 21), color=INK2)
    fig.text(60 / W, 36 / H, f"Backtest depuis {_mlabel(keys[0])}, frais inclus, mêmes données",
             fontproperties=_font("ibm-plex-sans-400", 15), color=INK3)
    ax = fig.add_axes([740 / W, 90 / H, 420 / W, 420 / H])
    for s, col, lw in [(b, PUB, 2.6), (a, ACCENT, 3)]:
        v = curve(s)
        ax.plot(range(len(v)), [x * 100 for x in v], color=col, lw=lw)
    ax.set_yscale("log")
    ax.set_facecolor(BG)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xticks([]); ax.set_yticks([]); ax.minorticks_off()
    ax.axhline(100, color=RULE, lw=1.2, zorder=0)
    _save(fig, out)


def build(data: dict, site: Path, brand: str = "Labo ETF", comparisons: list | None = None,
          short: dict | None = None) -> list[str]:
    global BRAND
    BRAND = brand
    by_id = {s["id"]: s for s in data["strategies"]}
    ref = by_id.get("acwi") or by_id["spy"]
    home_image(data, site / "og" / "home.png")
    written = ["og/home.png"]
    for s in data["strategies"]:
        strategy_image(s, ref, site / "og" / f"{s['id']}.png")
        written.append(f"og/{s['id']}.png")
    start = data["common_window"][0]
    for slug, c in (comparisons or []):
        pair_image(c, slug, by_id, start, site / "og" / f"cmp-{slug}.png", short)
        written.append(f"og/cmp-{slug}.png")
    return written


def prev_month(p: str) -> str:
    y, m = map(int, p.split("-")[:2])
    return f"{y - (m == 1)}-{12 if m == 1 else m - 1:02d}"
