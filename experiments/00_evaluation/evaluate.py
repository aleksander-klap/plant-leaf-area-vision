"""Test the runs of an experiment with the regression model and write a report.

    python 00_evaluation/evaluate.py EXPERIMENT/results/runs.csv [--out DIR] [--detail RUN ...] [--perm 1000]

Input: runs.csv as written by common.data.write_runs, one row per run and plant (run, <settings...>, plant,
optical_mass), with one run named "baseline": the current method, T_64_0.9. The real leaf areas come from
common/real_leaf_area_mm2.csv.

Every run is tested with leaf area = c x optical mass, leave-one-out (common/regression.py). With more than one run
besides the baseline, the honest score of "choose the best run, then predict" is computed too (nested): with many
runs and 14 plants, the best run is partly lucky.

Output (default: the folder of runs.csv):
    report.md      everything on one page (pictures in report_files/)
    summary.csv    every run with its scores, best first
    *.png          the charts of the page
"""
import argparse
import base64
import csv
import html
import io
import sys
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from common import regression as rg  # noqa: E402
from common import html_to_md  # noqa: E402
from common.data import BASELINE, labels, plant_sort_key  # noqa: E402

BLUE, ORANGE, GREY, RED, GREEN = "#2563eb", "#ea580c", "#9ca3af", "#dc2626", "#16a34a"
NOISE = 1.0      # points of typical error: with 14 plants, smaller differences between runs are noise


# ----------------------------------------------------------------------------------------------
# data
# ----------------------------------------------------------------------------------------------

def number(v):
    try:
        return float(v)
    except ValueError:
        return v


def load(path):
    """Runs of runs.csv on the plants that have a real leaf area.
    Returns (run names, {run: settings}, setting keys, plants, X: runs x plants, y: leaf areas)."""
    rows = list(csv.DictReader(open(path, newline="")))
    if not rows:
        raise SystemExit(f"{path} is empty")
    keys = [k for k in rows[0] if k not in ("run", "plant", "optical_mass")]
    real = labels()
    names, settings, values = [], {}, {}
    for r in rows:
        n = r["run"]
        if n not in values:
            names.append(n)
            settings[n] = {k: number(r[k]) for k in keys if r[k] != ""}
            values[n] = {}
        values[n][r["plant"]] = float(r["optical_mass"])
    plants = sorted(set.intersection(*(set(v) for v in values.values())) & set(real), key=plant_sort_key)
    if len(plants) < 4:
        raise SystemExit(f"only {len(plants)} plants with a real leaf area in every run, need at least 4")
    if BASELINE not in values:
        raise SystemExit(f"no run named '{BASELINE}' (the current method) in {path}")
    X = np.array([[values[n][p] for p in plants] for n in names])
    return names, settings, keys, plants, X, np.array([real[p] for p in plants])


# ----------------------------------------------------------------------------------------------
# charts
# ----------------------------------------------------------------------------------------------

def style():
    plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 140, "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.3,
                         "axes.titleweight": "bold", "axes.titlesize": 11})


def thousands(ax, *axes):
    for a in axes:
        getattr(ax, f"{a}axis").set_major_formatter(lambda v, _: f"{v / 1000:.0f}k")


def fig_fit(plants, x, y, c):
    f, ax = plt.subplots(figsize=(6.4, 4.8))
    xs = np.linspace(x.min() * 0.85, x.max() * 1.08, 50)
    ax.plot(xs, c * xs, color=BLUE, lw=2, label=f"leaf area = {c:.4f} × optical mass")
    ax.fill_between(xs, c * xs * 0.95, c * xs * 1.05, color=BLUE, alpha=0.08, label="± 5%")
    ax.scatter(x, y, s=40, color=BLUE, zorder=3)
    for p, xi, yi in zip(plants, x, y):
        ax.annotate(p, (xi, yi), textcoords="offset points", xytext=(5, 3), fontsize=8)
    ax.set_xlabel("optical mass (mean over the photos)")
    ax.set_ylabel("real leaf area (mm²)")
    thousands(ax, "x", "y")
    ax.set_title("The model, fitted on all plants")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    return f


def fig_pred(plants, y, p):
    f, ax = plt.subplots(figsize=(6, 4.8))
    lo, hi = min(y.min(), p.min()) * 0.9, max(y.max(), p.max()) * 1.05
    xs = np.array([lo, hi])
    ax.fill_between(xs, xs * 0.9, xs * 1.1, color=GREY, alpha=0.12, label="± 10%")
    ax.fill_between(xs, xs * 0.95, xs * 1.05, color=GREEN, alpha=0.15, label="± 5%")
    ax.plot(xs, xs, color="black", lw=1, label="perfect prediction")
    ax.scatter(y, p, s=40, color=BLUE, zorder=3)
    for name, yi, pi in zip(plants, y, p):
        ax.annotate(name, (yi, pi), textcoords="offset points", xytext=(5, 3), fontsize=8)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.set_xlabel("real leaf area (mm²)")
    ax.set_ylabel("predicted, plant left out (mm²)")
    thousands(ax, "x", "y")
    ax.set_title("Leave-one-out: predicted vs real")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    return f


def fig_plant_errors(plants, y, rows):
    """rows: [(label, predictions, colour)] -> bars of the error per plant, side by side."""
    f, ax = plt.subplots(figsize=(10, 3.8))
    w = 0.8 / len(rows)
    pos = np.arange(len(plants))
    for k, (lab, p, col) in enumerate(rows):
        e = (p - y) / y * 100
        ax.bar(pos + (k - (len(rows) - 1) / 2) * w, e, w, color=col, label=lab)
        if len(rows) == 1:
            for i, v in enumerate(e):
                ax.annotate(f"{v:+.1f}", (i, v), ha="center", va="bottom" if v >= 0 else "top", fontsize=8,
                            textcoords="offset points", xytext=(0, 2 if v >= 0 else -2))
    ax.axhline(0, color="black", lw=0.8)
    for v in (-5, 5):
        ax.axhline(v, color=GREEN, lw=0.8, ls="--")
    ax.set_xticks(pos, plants)
    ax.set_ylabel("error (%)  + = predicted too high")
    ax.set_title("Error per plant, plant left out (dashed: ± 5%)")
    ax.legend(fontsize=8, frameon=False, ncol=min(len(rows), 4))
    ax.grid(axis="x", visible=False)
    return f


def fig_c(plants, cs, c):
    f, ax = plt.subplots(figsize=(7.5, 3.2))
    ax.plot(plants, cs, "o-", color=BLUE)
    ax.axhline(c, color="black", lw=0.8, ls="--", label=f"all plants: {c:.4f}")
    ax.set_ylabel("c")
    ax.set_xlabel("plant left out")
    ax.set_title(f"c in every round: {cs.min():.4f} … {cs.max():.4f} (± {(cs.max() - cs.min()) / 2 / c * 100:.1f}%)")
    ax.legend(fontsize=8, frameon=False)
    return f


def fig_perm(real, perm, p):
    f, ax = plt.subplots(figsize=(6.5, 3.4))
    ax.hist(perm / 1000, bins=40, color=GREY)
    ax.axvline(real / 1000, color=RED, lw=2, label=f"real: {real / 1000:.1f}k")
    ax.set_xlabel("leave-one-out RMSE (thousand mm²)")
    ax.set_ylabel("shuffled runs")
    ax.set_title(f"Leaf areas shuffled between the plants, {len(perm)} times: p = {p:.3f}")
    ax.legend(fontsize=8, frameon=False)
    return f


def fig_hist(err, base):
    f, ax = plt.subplots(figsize=(7.5, 3.6))
    ax.hist(err, bins=min(50, max(10, len(err) // 4)), color=GREY)
    ax.axvline(base, color=ORANGE, lw=2, ls="--", label=f"baseline: {base:.2f}%")
    ax.axvline(err.min(), color=GREEN, lw=2, label=f"best run: {err.min():.2f}%")
    ax.set_xlabel("typical error, plant left out (%)")
    ax.set_ylabel("runs")
    ax.set_title(f"All {len(err)} runs")
    ax.legend(fontsize=8, frameon=False)
    return f


def fig_grid(sets, err, base, a, b):
    """Two settings, every combination one run: the typical error of each run in its cell."""
    va, vb = values_of(sets, a), values_of(sets, b)
    M = np.full((len(vb), len(va)), np.nan)
    for e_, s_ in zip(err, sets):
        M[vb.index(s_[b]), va.index(s_[a])] = e_
    f, ax = plt.subplots(figsize=(min(12, 1.2 + 0.62 * len(va)), 1.4 + 0.42 * len(vb)))
    lim = max(np.nanmax(np.abs(M - base)), 0.01)
    im = ax.imshow(M - base, cmap="RdBu_r", vmin=-lim, vmax=lim, aspect="auto")
    best = np.unravel_index(np.nanargmin(M), M.shape)
    for i in range(len(vb)):
        for j in range(len(va)):
            if not np.isnan(M[i, j]):
                ax.text(j, i, f"{M[i, j]:.2f}", ha="center", va="center", fontsize=7,
                        fontweight="bold" if (i, j) == best else "normal",
                        color="white" if abs(M[i, j] - base) > 0.6 * lim else "black")
    ax.set_xticks(range(len(va)), [f"{x:g}" for x in va])
    ax.set_yticks(range(len(vb)), [f"{x:g}" for x in vb])
    ax.set_xlabel(a)
    ax.set_ylabel(b)
    ax.grid(False)
    ax.set_title(f"Typical error (%) of every run; blue = better than the baseline ({base:.2f}%), red = worse")
    f.colorbar(im, ax=ax, shrink=0.8, label="points vs the baseline")
    return f


def values_of(sets, k):
    vals = {s[k] for s in sets if k in s}
    return sorted(vals) if all(isinstance(v, float) for v in vals) else sorted(vals, key=str)


def fig_effects(sets, err, base, vary):
    """For every setting that varies: the error per value (median and best over the other settings)."""
    f, axs = plt.subplots(1, len(vary), figsize=(11 if len(vary) == 1 else 2.8 * len(vary) + 0.5, 3.8),
                          sharey=True, squeeze=False)
    for ax, k in zip(axs[0], vary):
        vals = values_of(sets, k)
        v = [s.get(k) for s in sets]
        best = np.array([min(e for e, x in zip(err, v) if x == val) for val in vals])
        med = np.array([np.median([e for e, x in zip(err, v) if x == val]) for val in vals])
        numeric = all(isinstance(x, float) for x in vals) and len(vals) > 8
        pos = np.array(vals) if numeric else np.arange(len(vals))
        if np.any(np.abs(best - med) > 1e-9):
            ax.plot(pos, med, "o-", color=BLUE, ms=4, label="median of the runs")
            ax.plot(pos, best, "o-", color=GREEN, ms=4, label="best run")
        else:
            ax.plot(pos, best, "o-", color=BLUE, ms=4, label="typical error")
            i = int(np.argmin(best))
            ax.plot([pos[i]], [best[i]], "o", color=GREEN, ms=8)
            ax.annotate(f"best: {vals[i]:g} ({best[i]:.2f}%)" if numeric else f"best ({best[i]:.2f}%)",
                        (pos[i], best[i]), textcoords="offset points", xytext=(0, -16), ha="center", fontsize=8,
                        color=GREEN)
        ax.axhline(base, color=ORANGE, ls="--", lw=1, label="baseline")
        if numeric:
            ax.set_xticks(vals[::max(1, len(vals) // 12)])
        else:
            ax.set_xticks(pos, [f"{x:g}" if isinstance(x, float) else str(x) for x in vals])
        ax.set_xlabel(k)
    axs[0][0].set_ylabel("typical error (%)")
    axs[0][0].legend(fontsize=8, frameon=False)
    f.suptitle("What each setting does" + ("" if len(vary) == 1 else " (the other settings vary)"),
               fontweight="bold", fontsize=11)
    f.tight_layout()
    return f


# ----------------------------------------------------------------------------------------------
# the page
# ----------------------------------------------------------------------------------------------

CSS = """
:root { --bg:#ffffff; --fg:#1f2937; --muted:#6b7280; --card:#f9fafb; --line:#e5e7eb; --good:#16a34a; --bad:#dc2626; }
@media (prefers-color-scheme: dark) { :root { --bg:#111827; --fg:#e5e7eb; --muted:#9ca3af; --card:#1f2937;
  --line:#374151; --good:#4ade80; --bad:#f87171; } img.chart { background:#fff; } }
body { background:var(--bg); color:var(--fg); font:15px/1.55 system-ui, sans-serif; margin:0 auto; max-width:1000px;
       padding:24px 16px 60px; }
h1 { font-size:26px; margin:0 0 4px; } h2 { font-size:20px; margin:36px 0 8px; border-bottom:1px solid var(--line);
     padding-bottom:4px; } h3 { font-size:16px; margin:22px 0 6px; }
.muted { color:var(--muted); } .small { font-size:13px; }
.cards { display:grid; grid-template-columns:repeat(auto-fit, minmax(170px, 1fr)); gap:12px; margin:16px 0; }
.card { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:12px 14px; }
.card .v { font-size:26px; font-weight:700; } .card .l { font-size:13px; color:var(--muted); }
.scroll { overflow-x:auto; }
table { border-collapse:collapse; margin:8px 0 12px; font-size:14px; width:100%; }
th, td { border-bottom:1px solid var(--line); padding:5px 8px; text-align:right; white-space:nowrap; }
th:first-child, td:first-child { text-align:left; } th { color:var(--muted); font-weight:600; }
tr.hi td { font-weight:700; }
.good { color:var(--good); } .bad { color:var(--bad); }
img.chart { max-width:100%; height:auto; border-radius:8px; border:1px solid var(--line); margin:6px 0; }
.grid2 { display:grid; grid-template-columns:repeat(auto-fit, minmax(min(420px, 100%), 1fr)); gap:12px; }
details { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin:12px 0; }
summary { cursor:pointer; font-weight:600; }
code { background:var(--card); padding:1px 4px; border-radius:4px; }
figure { margin:12px 0 20px; } figcaption { color:var(--muted); margin-top:2px; }
nav.toc { background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 14px; margin:14px 0; }
nav.toc ol { margin:6px 0 0; padding-left:22px; } nav.toc li { margin:2px 0; } nav.toc a { color:inherit; }
html { scroll-behavior:smooth; } h2[id] { scroll-margin-top:12px; }
"""

EXPLAIN = """
<details><summary>How to read this page</summary>
<p><b>The model.</b> <code>leaf area = c × optical mass</code>: a straight line through zero, with c the one number
learned from the plants. It is the model of the regression (<code>Regression/docs/single_feature_model.md</code>).</p>
<p><b>Leave-one-out.</b> Every plant in turn is left out, c is learned from the others, and the left-out plant is
predicted. Each plant is predicted by a model that never saw it.</p>
<p><b>Typical error</b> = the RMSE of those predictions as a % of the average leaf area, the number the regression
reports. <b>Mean error</b> = the average of the absolute errors in %. <b>R²</b>: 1 is perfect, 0 is no better than
guessing the average plant.</p>
<p><b>Baseline</b> = the current method, <code>T_64_0.9</code>: 64 px window, cap 0.9, leaf mask M1, mean over all
side photos. Every experiment is compared with it on the same plants and leaf areas.</p>
<p><b>Nested (honest) score.</b> With many runs, the best one is partly lucky: its settings happen to suit these
plants. The nested score repeats the whole search once per plant: the best run is chosen on the other plants only,
then predicts the left-out plant. Compare <b>that</b> number with the baseline.</p>
<p><b>Noise.</b> With 14 plants, one plant can move the typical error by about a point. Differences below about
1 point are not a result.</p>
</details>
"""


def png(fig, path):
    buf = io.BytesIO()
    fig.savefig(buf, format="png", bbox_inches="tight")
    plt.close(fig)
    path.write_bytes(buf.getvalue())
    return f'<img class="chart" src="data:image/png;base64,{base64.b64encode(buf.getvalue()).decode()}" alt="{path.stem}">'


def e(s):
    return html.escape(str(s))


def fmt(v):
    return f"{v:g}" if isinstance(v, float) else str(v)


def settings_text(s):
    return " · ".join(f"{e(k)} <b>{e(fmt(v))}</b>" for k, v in s.items()) or "<span class='muted'>—</span>"


def pct(v):
    return f"<span class='{'good' if abs(v) <= 5 else 'bad'}'>{v:+.1f}%</span>"


def detail(name, sets, plants, x, y, out, n_perm, base_pred=None, anchor="best"):
    """One run in detail: fit, predictions, per-plant numbers, c per round, shuffle test."""
    tag = "".join(ch if ch.isalnum() else "_" for ch in name)
    c = rg.fit("origin", x, y)[0]
    pred, prms = rg.loo("origin", x, y)
    s = rg.scores(y, pred)
    cs = np.array([q[0] for q in prms])
    real, perm, p = rg.permutation(x, y, n_perm)
    figs = [png(fig_fit(plants, x, y, c), out / f"{tag}_fit.png"),
            png(fig_pred(plants, y, pred), out / f"{tag}_predicted.png")]
    c_fig = png(fig_c(plants, cs, c), out / f"{tag}_c_rounds.png")
    perm_fig = png(fig_perm(real, perm, p), out / f"{tag}_permutation.png")

    rows = []
    for i, pl in enumerate(plants):
        er = (pred[i] - y[i]) / y[i] * 100
        extra = "" if base_pred is None else f"<td>{pct((base_pred[i] - y[i]) / y[i] * 100)}</td>"
        rows.append(f"<tr><td>{e(pl)}</td><td>{x[i]:,.0f}</td><td>{y[i]:,.0f}</td><td>{pred[i]:,.0f}</td>"
                    f"<td>{pct(er)}</td>{extra}</tr>")
    plant_table = ("<div class='scroll'><table><tr><th>plant</th><th>optical mass</th><th>real mm²</th>"
                   "<th>predicted mm²</th><th>error</th>" + ("" if base_pred is None else "<th>baseline error</th>")
                   + "</tr>" + "".join(rows) + "</table></div>")
    spread = (cs.max() - cs.min()) / 2 / c * 100
    far = plants[int(np.argmax(np.abs(cs - c)))]
    n_better = int(np.sum(perm <= real))
    return f"""
<h2 id="{anchor}">Run in detail: {e(name)}</h2>
<p class="small muted">settings: {settings_text(sets)}</p>
<div class="cards">
  <div class="card"><div class="v">{s['typical']:.1f}%</div><div class="l">typical error</div></div>
  <div class="card"><div class="v">{s['r2']:.2f}</div><div class="l">R²</div></div>
  <div class="card"><div class="v">{s['within5']} / {len(plants)}</div><div class="l">plants within 5%</div></div>
  <div class="card"><div class="v">{c:.4f}</div><div class="l">c, fitted on all plants</div></div>
</div>
<h3>The fit and the predictions</h3>
<p class="small">Left: every plant's optical mass against its real leaf area, with the line
<code>leaf area = c × optical mass</code> fitted on all plants. Right: each plant predicted by the model learned
without it (leave-one-out), against its real leaf area. On the black line the prediction is perfect; inside the
green band it is within 5%.</p>
<div class="grid2">{''.join(figs)}</div>
<h3>Per plant</h3>
{plant_table}
<h3>c in every round: does one plant decide the model?</h3>
<p class="small">Leave-one-out fits c {len(plants)} times, each time without one plant. Each point is the c fitted
<b>without</b> the plant on the x-axis; the dashed line is c fitted on all plants. A flat line means no single plant
drives the model. A point far from the line means that plant on its own pulls c up or down, and it is usually also
predicted badly. Here c moves by ± {spread:.1f}%; the plant that moves it most is {e(far)}.</p>
{c_fig}
<h3>Shuffle test: is the fit real or luck?</h3>
<p class="small">The leaf areas are shuffled randomly between the plants {len(perm)} times, so they no longer belong
to their photos, and the same leave-one-out test is run each time. Grey: the errors of the shuffled data. Red: the
error of the real data. If red lies left of nearly all of grey, the optical mass really carries the leaf area.
p is the share of shuffles that did as well as the real data (p &lt; 0.05: not luck). It says the run is not
noise, not that it beats the baseline.
Here {n_better} of {len(perm)} shuffles did as well (p = {p:.3f}{', so it is not luck' if p < 0.05 else
', so it could be luck'}).</p>
{perm_fig}
"""


def method_section(folder, sets, vary, n_runs):
    """The method of the experiment: optional method.html next to runs.csv (an HTML fragment written by the
    experiment), the settings (settings.csv) and how many runs the sweep makes."""
    parts = []
    if (folder / "method.html").exists():
        parts.append((folder / "method.html").read_text(encoding="utf-8"))
    parts.append(settings_section(folder / "settings.csv"))
    counts = [len(values_of(sets, k)) for k in vary]
    if len(vary) == 1 and counts[0] == n_runs:
        parts.append(f"<p><b>Runs:</b> one run per {e(vary[0])} value, <b>{n_runs} runs</b>, plus the baseline.</p>")
    elif vary and int(np.prod(counts)) == n_runs:
        grid = " × ".join(f"{n} {e(k)}" for n, k in zip(counts, vary))
        parts.append(f"<p><b>Runs:</b> every combination of the settings, {grid} = <b>{n_runs} runs</b>, plus the "
                     "baseline.</p>")
    else:
        parts.append(f"<p><b>Runs:</b> {n_runs} run{'s' if n_runs > 1 else ''}, plus the baseline.</p>")
    return "<h2 id='method'>The method</h2>" + "".join(parts)


def settings_section(path):
    """What each setting of the experiment means, from an optional settings.csv next to runs.csv
    (setting, meaning[, values]). Without it the report only shows the setting names."""
    if not path.exists():
        return ""
    rows = list(csv.DictReader(open(path, newline="")))
    has_values = any(r.get("values") for r in rows)
    head = ("<th>setting</th><th style='text-align:left'>what it does</th>"
            + ("<th>values tried</th>" if has_values else ""))
    body = "".join(f"<tr><td><b>{e(r['setting'])}</b></td><td style='text-align:left'>{e(r['meaning'])}</td>"
                   + (f"<td>{e(r.get('values') or '')}</td>" if has_values else "") + "</tr>" for r in rows)
    return ("<h3>The settings</h3><p class='small muted'>What the settings in the run names and tables mean.</p>"
            "<div class='scroll'><table><tr>" + head + "</tr>" + body + "</table></div>")


def pictures_section(folder):
    """The pictures an experiment left in results/pictures/, embedded so the page stays one file.
    Optional pictures/captions.csv (file, caption[, section]) sets the order and the captions; pictures with a
    section are grouped in a collapsed block of that name."""
    if not folder.is_dir():
        return ""
    cap_file = folder / "captions.csv"
    if cap_file.exists():
        items = [(folder / r["file"], r["caption"], r.get("section") or "")
                 for r in csv.DictReader(open(cap_file, newline=""))]
    else:
        items = [(p, p.stem, "") for p in sorted(folder.iterdir()) if p.suffix.lower() in (".jpg", ".jpeg", ".png")]
    shown, folded = [], {}
    for path, caption, section in items:
        if not path.exists():
            continue
        mime = "png" if path.suffix.lower() == ".png" else "jpeg"
        data = base64.b64encode(path.read_bytes()).decode()
        fig = (f"<figure><img class='chart' loading='lazy' src='data:image/{mime};base64,{data}' "
               f"alt='{e(path.stem)}'><figcaption class='small'>{e(caption)}</figcaption></figure>")
        (folded.setdefault(section, []) if section else shown).append(fig)
    if not shown and not folded:
        return ""
    blocks = "".join(f"<details><summary>{e(sec)} ({len(figs)})</summary>{''.join(figs)}</details>"
                     for sec, figs in folded.items())
    return "<h2 id='pictures'>What the method looks like</h2>" + "".join(shown) + blocks


def best_share_table(all_sets, top_sets, vary, cutoff, out):
    """Where the best 10% of the runs lie: for every setting, how often each value appears among them.
    With no preference, every value would get its share of the grid (100% / number of values). Also written to
    best_10pct.csv."""
    rows, csv_rows = [], []
    for k in vary:
        vals = values_of(all_sets, k)
        cells = []
        for v in vals:
            n_top = sum(s.get(k) == v for s in top_sets)
            share = n_top / len(top_sets) * 100
            even = sum(s.get(k) == v for s in all_sets) / len(all_sets) * 100
            cls = "good" if share >= 1.5 * even else "muted" if share <= 0.5 * even else ""
            cells.append(f"<span class='{cls}'>{e(fmt(v))}: {share:.0f}%</span>")
            csv_rows.append([k, fmt(v), n_top, round(share, 1), round(even, 1)])
        used = [v for v in vals if any(s.get(k) == v for s in top_sets)]
        rng = f"{fmt(used[0])} – {fmt(used[-1])}" if len(used) > 1 else fmt(used[0])
        rows.append(f"<tr><td>{e(k)}</td><td>{e(rng)}</td><td style='text-align:left'>{' · '.join(cells)}</td>"
                    f"<td>{100 / len(vals):.0f}%</td></tr>")
    with open(out / "best_10pct.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "value", "runs_in_best_10pct", "share_of_best_10pct", "share_of_all_runs"])
        w.writerows(csv_rows)
    return (f"<h3 id='best10'>Where the best 10% of the runs lie ({len(top_sets)} runs, typical error ≤ {cutoff:.2f}%)</h3>"
            "<div class='scroll'><table><tr><th>setting</th><th>range in the best 10%</th>"
            "<th style='text-align:left'>share of the best 10% per value</th><th>if it didn't matter</th></tr>"
            + "".join(rows) + "</table></div><p class='small muted'>Green: the value is at least 1.5× as common "
            "among the best runs as in the grid; grey: at most half as common. A setting whose values all sit near "
            "the \"didn't matter\" share has no effect.</p>")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("runs", type=Path, help="runs.csv of an experiment")
    ap.add_argument("--out", type=Path, default=None, help="output folder (default: the folder of runs.csv)")
    ap.add_argument("--detail", nargs="*", default=[], help="runs to show in full (always: baseline and best run)")
    ap.add_argument("--perm", type=int, default=1000, help="shuffles in the shuffle test")
    ap.add_argument("--title", default=None)
    a = ap.parse_args()
    style()
    names, settings, keys, plants, X, y = load(a.runs)
    out = a.out or a.runs.parent
    out.mkdir(parents=True, exist_ok=True)
    sets = [settings[n] for n in names]

    P = rg.loo_origin(X, y)
    err = rg.typical(y, P)
    mape = np.mean(np.abs((P - y) / y), axis=1) * 100
    r2 = 1 - ((P - y) ** 2).sum(1) / ((y - y.mean()) ** 2).sum()
    within5 = (np.abs((P - y) / y) <= 0.05).sum(1)
    cs = X @ y / (X * X).sum(1)
    bi = names.index(BASELINE)
    cand = [i for i in range(len(names)) if i != bi]
    if not cand:
        raise SystemExit("runs.csv holds only the baseline")
    order = sorted(cand, key=lambda i: err[i])
    best = order[0]

    with open(out / "summary.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["rank", "run", *keys, "c", "typical_error_pct", "mean_error_pct", "r2", "within_5pct",
                    "vs_baseline_points"])
        for rank, i in enumerate([bi] + order):
            w.writerow([rank if i != bi else "baseline", names[i], *[fmt(sets[i].get(k, "")) for k in keys],
                        round(cs[i], 5), round(err[i], 3), round(mape[i], 3), round(r2[i], 4), within5[i],
                        round(err[i] - err[bi], 3)])

    # cards and verdict
    cards = [(f"{err[bi]:.2f}%", "baseline T_64_0.9"), (f"{err[best]:.2f}%", f"best run: {names[best]}")]
    nested_html, verdict_err, verdict_what = "", err[best], "the best run"
    if len(cand) > 1:
        npred, chosen = rg.nested_runs(X[cand], y)
        n_err = float(rg.typical(y, npred))
        cards[1] = (cards[1][0], cards[1][1] + " (optimistic)")
        cards.append((f"{n_err:.2f}%", "honest: run chosen without the plant (nested)"))
        cards.append((f"{int((err[cand] < err[bi]).sum())} / {len(cand)}", "runs better than the baseline"))
        picked = {}
        for j in chosen:
            picked[names[cand[j]]] = picked.get(names[cand[j]], 0) + 1
        nested_html = ("<p class='small muted'>Runs the nested search chose: "
                       + ", ".join(f"{e(k)} ({v}×)" for k, v in sorted(picked.items(), key=lambda t: -t[1]))
                       + "</p>")
        verdict_err, verdict_what = n_err, "choosing the run on the other plants (nested)"
    diff = verdict_err - err[bi]
    verdict = (f"<p><b>Verdict:</b> {verdict_what} gives <b>{verdict_err:.2f}%</b>, against <b>{err[bi]:.2f}%</b> "
               f"for the baseline ({diff:+.2f} points). "
               + ("That is a <b>gain</b> beyond the ~1 point of noise." if diff < -NOISE else
                  "That is <b>worse</b> by more than the ~1 point of noise." if diff > NOISE else
                  "That is within the ~1 point of noise: <b>no clear difference</b>.") + "</p>")

    # all runs
    toc = [("summary", "Summary", "the baseline, the best run and the honest score, and the verdict")]
    sections = []
    vary = [k for k in keys if len({str(sets[i].get(k)) for i in cand}) > 1]
    method_html = method_section(a.runs.parent, [sets[i] for i in cand], vary, len(cand))
    toc.append(("method", "The method", "what the experiment changes, its settings and how many runs it makes"))
    pictures_html = pictures_section(a.runs.parent / "pictures")
    if pictures_html:
        toc.append(("pictures", "What the method looks like", "the method drawn on example photos"))
    toc.append(("runs", "All runs", "how the runs are spread, what each setting does, the best runs"))
    if len(cand) > 10:
        sections.append("<p class='small'>The typical error of every run. Runs left of the orange line beat the "
                        "baseline; the green line is the best run (before the honest correction).</p>"
                        + png(fig_hist(err[cand], err[bi]), out / "all_runs.png"))
    if vary and len(cand) > 2:
        sections.append("<h3>What each setting does</h3><p class='small'>One panel per setting. For each value of "
                        "the setting, the runs with that value are taken together, whatever the other settings: "
                        "blue is their median typical error, green the best of them. The orange line is the "
                        "baseline. A flat line means the setting doesn't matter; a slope shows which values "
                        "are better.</p>"
                        + png(fig_effects([sets[i] for i in cand], err[cand], err[bi], vary), out / "settings.png"))
    if len(vary) == 2 and len(cand) == np.prod([len(values_of([sets[i] for i in cand], k)) for k in vary]):
        sections.append(f"<h3>Every run: {e(vary[0])} × {e(vary[1])}</h3><p class='small'>With two settings, every "
                        "combination is one run, so this grid shows every run's own typical error, nothing "
                        "averaged. Blue cells beat the baseline, red ones are worse; the best run is in bold. A "
                        "real effect shows as a smooth region; a lone good cell among worse ones is likely "
                        "luck.</p>"
                        + png(fig_grid([sets[i] for i in cand], err[cand], err[bi], vary[0], vary[1]),
                              out / "grid.png"))
    if vary and len(cand) >= 20:
        sections.append(best_share_table([sets[i] for i in cand], [sets[i] for i in order[:len(cand) // 10]],
                                         vary, err[order[len(cand) // 10 - 1]], out))
    shown = [bi] + order[:25]
    trows = []
    for i in shown:
        cls = " class='hi'" if i in (bi, best) else ""
        trows.append(f"<tr{cls}><td>{e(names[i])}</td>" + "".join(f"<td>{e(fmt(sets[i].get(k, '')))}</td>"
                                                                   for k in keys)
                     + f"<td>{cs[i]:.4f}</td><td>{err[i]:.2f}%</td><td>{mape[i]:.2f}%</td><td>{r2[i]:.3f}</td>"
                     f"<td>{within5[i]}/{len(y)}</td><td>{err[i] - err[bi]:+.2f}</td></tr>")
    table = ("<h3>The best runs</h3><div class='scroll'><table><tr><th>run</th>"
             + "".join(f"<th>{e(k)}</th>" for k in keys)
             + "<th>c</th><th>typical error</th><th>mean error</th><th>R²</th><th>within 5%</th>"
             "<th>vs baseline</th></tr>" + "".join(trows) + "</table></div>"
             + (f"<p class='small muted'>Best 25 of {len(cand)} runs. All runs: summary.csv.</p>"
                if len(cand) > 25 else ""))
    bars = [(BASELINE, P[bi], ORANGE)]
    others = order if len(cand) <= 5 else [best]
    palette = [BLUE, GREEN, "#7c3aed", "#0891b2", "#be185d"]
    bars += [(names[i], P[i], palette[k % len(palette)]) for k, i in enumerate(others)]
    plants_fig = png(fig_plant_errors(plants, y, bars), out / "plants.png")
    compared = "the best run, " + names[best] if len(others) == 1 else "every run"
    plants_title = "Per plant: baseline vs " + ("best run" if len(others) == 1 else "every run")
    toc.append(("plants", plants_title, "how far off each plant is, the baseline next to " + compared))
    plants_html = (f"<h2 id='plants'>{e(plants_title)}</h2><p class='small'>The error of every plant when it is "
                   f"predicted by the model learned without it, for the baseline (orange) and {e(compared)}. "
                   "Above 0: predicted too high; below: too low. Between the green dashed lines the plant is "
                   "within 5%. A plant that is off the same way for both is missed by the optical mass itself, "
                   "not by the setting.</p>" + plants_fig)

    details = [names[best]] + [n for n in a.detail if n in names and n not in (BASELINE, names[best])]
    toc.append(("best", "Best run in detail",
                "its fit, every plant's prediction, whether one plant decides the model, and the shuffle test"))
    detail_html = "".join(detail(n, settings[n], plants, X[names.index(n)], y, out, a.perm, P[bi],
                                 "best" if k == 0 else f"detail{k}") for k, n in enumerate(details))
    detail_html = detail_html.replace("<h2 id=\"best\">Run in detail:", "<h2 id=\"best\">Best run in detail:", 1)
    title = a.title or f"Experiment {a.runs.resolve().parents[1].name}"
    card_html = "".join(f"<div class='card'><div class='v'>{v}</div><div class='l'>{e(lab)}</div></div>"
                        for v, lab in cards)
    toc_html = ("<nav class='toc'><b>Contents</b><ol>" + "".join(
        f"<li><a href='#{k}'>{e(t)}</a> <span class='muted'>— {e(d)}</span></li>" for k, t, d in toc)
        + "</ol></nav>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>{e(title)}</title><style>{CSS}</style>
</head><body><h1>{e(title)}</h1>
<p class="muted">{len(cand)} run{'s' if len(cand) > 1 else ''} + baseline · {len(y)} plants ({e(', '.join(plants))})
· leaf area = c × optical mass, leave-one-out</p>
{toc_html}
{EXPLAIN}
<h2 id="summary">Summary</h2>
<div class="cards">{card_html}</div>
{verdict}{nested_html}
{method_html}
{pictures_html}
<h2 id="runs">All runs</h2>
{''.join(sections)}
{table}
{plants_html}
{detail_html}
</body></html>"""
    html_to_md.save(page, out / "report.md")
    print(f"baseline {err[bi]:.2f}%   best {names[best]} {err[best]:.2f}%"
          + (f"   nested {verdict_err:.2f}%" if len(cand) > 1 else ""))
    print(out / "report.md")


if __name__ == "__main__":
    main()
