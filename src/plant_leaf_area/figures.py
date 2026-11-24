"""The charts of report.md, in the style of the experiment reports (experiments/00_evaluation/evaluate.py)."""
import matplotlib

matplotlib.use("Agg")                     # no window: the charts are only saved
import matplotlib.pyplot as plt          # noqa: E402
import numpy as np                       # noqa: E402

BLUE, ORANGE, GREY, RED, GREEN = "#2563eb", "#ea580c", "#9ca3af", "#dc2626", "#16a34a"


def style():
    plt.rcParams.update({"figure.dpi": 110, "savefig.dpi": 140, "font.size": 10, "axes.spines.top": False,
                         "axes.spines.right": False, "axes.grid": True, "grid.alpha": 0.3,
                         "axes.titleweight": "bold", "axes.titlesize": 11})


def save(fig, path):
    fig.savefig(path, bbox_inches="tight")
    plt.close(fig)
    return path


def _thousands(ax, *axes):
    for a in axes:
        getattr(ax, f"{a}axis").set_major_formatter(lambda v, _: f"{v / 1000:.0f}k")


def _labels(ax, names, xs, ys):
    """Name every point, each label on the side of its point where it overlaps no other label or point."""
    fig = ax.figure
    fig.canvas.draw()
    r = fig.canvas.get_renderer()
    pts = ax.transData.transform(np.column_stack([xs, ys]))
    placed = []
    for name, x, y, (px, py) in zip(names, xs, ys, pts):
        for dx, dy, ha, va in ((5, 3, "left", "bottom"), (5, -3, "left", "top"), (-5, 3, "right", "bottom"),
                               (-5, -3, "right", "top"), (0, 7, "center", "bottom"), (0, -7, "center", "top")):
            t = ax.annotate(name, (x, y), textcoords="offset points", xytext=(dx, dy), ha=ha, va=va, fontsize=8)
            bb = t.get_window_extent(r).expanded(1.05, 1.1)
            hits_label = any(bb.overlaps(b) for b in placed)
            hits_point = any(bb.contains(qx, qy) for qx, qy in pts if (qx, qy) != (px, py))
            if not (hits_label or hits_point):
                break
            t.remove()
        else:                                   # nowhere free: keep the first place
            t = ax.annotate(name, (x, y), textcoords="offset points", xytext=(5, 3), fontsize=8)
            bb = t.get_window_extent(r)
        placed.append(bb)


def fit(plants, x, y, c):
    """Every plant's optical mass against its leaf area, with the line fitted on all plants."""
    f, ax = plt.subplots(figsize=(6.4, 4.8))
    xs = np.linspace(x.min() * 0.85, x.max() * 1.08, 50)
    ax.plot(xs, c * xs, color=BLUE, lw=2, label=f"leaf area = {c:.4f} × optical mass")
    ax.fill_between(xs, c * xs * 0.95, c * xs * 1.05, color=BLUE, alpha=0.08, label="± 5%")
    ax.scatter(x, y, s=40, color=BLUE, zorder=3)
    ax.set_xlabel("optical mass (mean over the photos)")
    ax.set_ylabel("measured leaf area (mm²)")
    _thousands(ax, "x", "y")
    ax.set_title("The model, fitted on all plants")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    _labels(ax, plants, x, y)
    return f


def predicted(plants, y, pred):
    """Each plant predicted by the model learned without it, against its measured leaf area."""
    f, ax = plt.subplots(figsize=(6, 4.8))
    lo, hi = min(y.min(), pred.min()) * 0.9, max(y.max(), pred.max()) * 1.05
    xs = np.array([lo, hi])
    ax.fill_between(xs, xs * 0.9, xs * 1.1, color=GREY, alpha=0.12, label="± 10%")
    ax.fill_between(xs, xs * 0.95, xs * 1.05, color=GREEN, alpha=0.15, label="± 5%")
    ax.plot(xs, xs, color="black", lw=1, label="perfect prediction")
    ax.scatter(y, pred, s=40, color=BLUE, zorder=3)
    ax.set_xlim(lo, hi)
    ax.set_ylim(lo, hi)
    ax.set_aspect("equal")
    ax.set_xlabel("measured leaf area (mm²)")
    ax.set_ylabel("predicted, plant left out (mm²)")
    _thousands(ax, "x", "y")
    ax.set_title("Leave-one-out: predicted vs measured")
    ax.legend(loc="upper left", fontsize=8, frameon=False)
    _labels(ax, plants, y, pred)
    return f


def plant_errors(plants, err):
    """The error of every plant, plant left out."""
    f, ax = plt.subplots(figsize=(10, 3.8))
    pos = np.arange(len(plants))
    ax.bar(pos, err, 0.6, color=[BLUE if abs(e) <= 5 else RED for e in err])
    for i, v in enumerate(err):
        ax.annotate(f"{v:+.1f}", (i, v), ha="center", va="bottom" if v >= 0 else "top", fontsize=8,
                    textcoords="offset points", xytext=(0, 2 if v >= 0 else -2))
    ax.axhline(0, color="black", lw=0.8)
    for v in (-5, 5):
        ax.axhline(v, color=GREEN, lw=0.8, ls="--")
    ax.set_xticks(pos, plants)
    ax.set_ylabel("error (%)  + = predicted too high")
    ax.set_title("Error per plant, plant left out (dashed: ± 5%; red: outside it)")
    ax.grid(axis="x", visible=False)
    return f


def c_rounds(plants, cs, c):
    """c fitted without each plant."""
    f, ax = plt.subplots(figsize=(7.5, 3.2))
    ax.plot(plants, cs, "o-", color=BLUE)
    ax.axhline(c, color="black", lw=0.8, ls="--", label=f"all plants: {c:.4f}")
    ax.set_ylabel("c")
    ax.set_xlabel("plant left out")
    ax.set_title(f"c in every round: {cs.min():.4f} … {cs.max():.4f} (± {(cs.max() - cs.min()) / 2 / c * 100:.1f}%)")
    ax.legend(fontsize=8, frameon=False)
    return f


def shuffle(real, shuffled, p):
    """The typical error of the shuffled leaf areas against the real one."""
    f, ax = plt.subplots(figsize=(6.5, 3.4))
    ax.hist(shuffled, bins=40, color=GREY)
    ax.axvline(real, color=RED, lw=2, label=f"real: {real:.2f}%")
    ax.set_xlabel("typical error, leave-one-out (%)")
    ax.set_ylabel("shuffles")
    ax.set_title(f"Leaf areas shuffled between the plants, {len(shuffled)} times: p = {p:.3f}")
    ax.legend(fontsize=8, frameon=False)
    return f


def photo_spread(per_plant):
    """The optical mass of every photo, as % of its plant's mean: how much one view differs from the average."""
    plants = list(per_plant)
    f, ax = plt.subplots(figsize=(10, 3.8))
    for i, p in enumerate(plants):
        v = np.asarray(per_plant[p], float)
        rel = (v / v.mean() - 1) * 100
        jitter = (np.arange(len(rel)) % 5 - 2) * 0.06
        ax.scatter(i + jitter, rel, s=14, color=BLUE, alpha=0.6, zorder=3)
        sd = rel.std(ddof=1) if len(rel) > 1 else 0.0
        ax.plot([i - 0.28, i + 0.28], [sd, sd], color=ORANGE, lw=1.5)
        ax.plot([i - 0.28, i + 0.28], [-sd, -sd], color=ORANGE, lw=1.5)
    ax.axhline(0, color="black", lw=0.8)
    ax.set_xticks(range(len(plants)), plants)
    ax.set_ylabel("photo vs plant mean (%)")
    ax.set_title("Optical mass of every photo, relative to its plant's mean (orange: ± 1 standard deviation)")
    ax.grid(axis="x", visible=False)
    return f
