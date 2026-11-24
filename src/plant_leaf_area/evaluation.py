"""How well does the optical mass predict the measured leaf area? Leave-one-out test of

    leaf area = c x optical mass          (a line through zero: one number c, learned from the plants)

Every plant in turn is left out, c is learned from the other plants, and the left-out plant is predicted, so each
plant is predicted by a model that never saw it.

Scores:
    typical error   RMSE of the predictions as a % of the mean leaf area (the main score)
    R^2             share of the plant-to-plant variance in leaf area that the predictions explain
    mean |error|    mean absolute error, % of each plant's own leaf area
    worst           the largest absolute error, %
    within 5%       plants predicted within 5% of their measured leaf area
    shuffle test    how often c x optical mass predicts as well when the leaf areas are shuffled between the plants
"""
import csv
import json
from dataclasses import asdict, dataclass

import numpy as np

from .photos import plant_name


def read_column(path, column):
    """{plant: float} from a CSV with a 'plant' column."""
    with open(path, newline="") as fh:
        return {plant_name(row["plant"]): float(row[column]) for row in csv.DictReader(fh)}


def fit_c(x, y):
    """Least-squares c of y = c x (a line through zero)."""
    return float(x @ y / (x @ x))


def leave_one_out(x, y):
    """The prediction of every plant by c learned without it; and those c's."""
    n = len(x)
    c = np.array([fit_c(x[np.arange(n) != i], y[np.arange(n) != i]) for i in range(n)])
    return c * x, c


def typical_error(y, pred):
    """RMSE as a % of the mean leaf area."""
    return float(100 * np.sqrt(np.mean((pred - y) ** 2)) / y.mean())


def scores(y, pred):
    err = (pred - y) / y * 100
    return dict(typical_error=typical_error(y, pred),
                r2=float(1 - ((y - pred) ** 2).sum() / ((y - y.mean()) ** 2).sum()),
                mean_abs_error=float(np.mean(np.abs(err))),
                worst=float(np.max(np.abs(err))),
                within_5=int(np.sum(np.abs(err) <= 5)),
                plants=int(len(y)))


def shuffle_test(x, y, n=1000, seed=0):
    """The typical error with the leaf areas shuffled between the plants, n times. If the optical mass carries real
    information, shuffling makes it much worse. p: the share of shuffles at least as good as the real data."""
    rng = np.random.default_rng(seed)
    real = typical_error(y, leave_one_out(x, y)[0])
    shuffled = np.array([typical_error(ys, leave_one_out(x, ys)[0]) for ys in (rng.permutation(y) for _ in range(n))])
    summary = dict(shuffles=n, real=real, shuffled_median=float(np.median(shuffled)),
                   shuffled_best=float(shuffled.min()), p=float((np.sum(shuffled <= real) + 1) / (n + 1)))
    return summary, shuffled


@dataclass
class Result:
    plants: list            # the plants used
    x: np.ndarray           # their optical mass
    y: np.ndarray           # their measured leaf area, mm^2
    pred: np.ndarray        # their predicted leaf area (plant left out), mm^2
    c_loo: np.ndarray       # c learned without each plant
    c: float                # c learned on all plants: the model to use
    scores: dict
    shuffle: dict           # the shuffle test in numbers
    shuffled: np.ndarray    # ... and the typical error of every shuffle
    no_leaf_area: list      # plants with an optical mass but no measured leaf area
    no_optical_mass: list   # ... and the other way round

    @property
    def error_pct(self):
        return (self.pred - self.y) / self.y * 100


def evaluate(optical_mass, leaf_area):
    """optical_mass, leaf_area: {plant: value}. Only plants in both are used."""
    plants = [p for p in optical_mass if p in leaf_area]
    if len(plants) < 3:
        raise ValueError(f"need at least 3 plants with both an optical mass and a leaf area, got {len(plants)}")
    x = np.array([optical_mass[p] for p in plants])
    y = np.array([leaf_area[p] for p in plants])
    pred, c = leave_one_out(x, y)
    return Result(plants, x, y, pred, c, fit_c(x, y), scores(y, pred), *shuffle_test(x, y),
                  no_leaf_area=[p for p in optical_mass if p not in leaf_area],
                  no_optical_mass=[p for p in leaf_area if p not in optical_mass])


def save(r, out_dir, settings, labels_path):
    """evaluation.csv (per plant) and evaluation.json (scores, c, shuffle test, the run's settings)."""
    with open(out_dir / "evaluation.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plant", "optical_mass", "leaf_area_mm2", "predicted_mm2", "error_pct", "c_without_plant"])
        for p, x, y, pr, e, c in zip(r.plants, r.x, r.y, r.pred, r.error_pct, r.c_loo):
            w.writerow([p, round(x, 1), round(y, 1), round(pr, 1), round(e, 2), round(c, 6)])
    summary = dict(model="leaf area = c x optical mass", c=r.c, scores=r.scores, shuffle_test=r.shuffle,
                   c_leave_one_out=dict(min=float(r.c_loo.min()), max=float(r.c_loo.max())),
                   settings=asdict(settings), labels=str(labels_path),
                   no_leaf_area=r.no_leaf_area, no_optical_mass=r.no_optical_mass)
    (out_dir / "evaluation.json").write_text(json.dumps(summary, indent=2) + "\n")


def report(r):
    """The result as text for the terminal."""
    s, sh = r.scores, r.shuffle
    lines = [f"leaf area = c x optical mass, leave-one-out over {s['plants']} plants"]
    if r.no_leaf_area:
        lines.append(f"  not used (no measured leaf area): {', '.join(r.no_leaf_area)}")
    if r.no_optical_mass:
        lines.append(f"  not used (no optical mass): {', '.join(r.no_optical_mass)}")
    lines += ["", f"  {'plant':6s} {'measured':>10s} {'predicted':>10s} {'error':>7s}"]
    for p, y, pr, e in zip(r.plants, r.y, r.pred, r.error_pct):
        lines.append(f"  {p:6s} {y:10,.0f} {pr:10,.0f} {e:+6.1f}%{'  <- over 5%' if abs(e) > 5 else ''}")
    lines += [
        "",
        f"  typical error  {s['typical_error']:.2f}%   (RMSE as % of the mean leaf area)",
        f"  R^2            {s['r2']:.3f}",
        f"  mean |error|   {s['mean_abs_error']:.2f}%   worst {s['worst']:.1f}%",
        f"  within 5%      {s['within_5']} of {s['plants']} plants",
        f"  c              {r.c:.5f} mm^2 per unit of optical mass "
        f"(leave-one-out rounds: {r.c_loo.min():.5f} - {r.c_loo.max():.5f})",
        f"  shuffle test   shuffled leaf areas: median {sh['shuffled_median']:.1f}%, best {sh['shuffled_best']:.1f}% "
        f"of {sh['shuffles']}; p = {sh['p']:.4f}",
    ]
    return "\n".join(lines)
