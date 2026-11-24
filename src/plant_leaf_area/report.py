"""report.md: the result of a run on one page, readable on GitHub."""
import datetime

import numpy as np


def _pct(v):
    return f"{v:+.1f}%"


def write(path, settings, n_photos, per_plant, result, labels_path, seconds):
    """per_plant: {plant: [optical mass of every photo]}; result: evaluation.Result, or None if not evaluated."""
    res = "full" if settings.scale == 4 else "1/4"
    lines = [
        "# Results",
        "",
        f"Run on {datetime.date.today().isoformat()}: **{n_photos} photos of {len(per_plant)} plants**, "
        f"kernel {settings.kernel} px, cap {settings.cap}, {res} resolution ({seconds:.0f} s).",
        "",
    ]
    if result is not None:
        s, sh = result.scores, result.shuffle
        worst = result.plants[int(np.argmax(np.abs(result.error_pct)))]
        lines += [
            "## How well the leaf area is predicted",
            "",
            f"`leaf area = c × optical mass`, tested with leave-one-out on the {s['plants']} plants with a measured "
            f"leaf area (`{labels_path}`): every plant is predicted by c learned from the other {s['plants'] - 1}.",
            "",
            "| | |",
            "|---|---|",
            f"| **typical error** (RMSE as % of the mean leaf area) | **{s['typical_error']:.2f}%** |",
            f"| R² | {s['r2']:.3f} |",
            f"| mean absolute error | {s['mean_abs_error']:.2f}% |",
            f"| worst plant | {worst}, {s['worst']:.1f}% off |",
            f"| plants within 5% | {s['within_5']} of {s['plants']} |",
            f"| c, learned on all plants | {result.c:.5f} mm² per unit of optical mass |",
            f"| c in the leave-one-out rounds | {result.c_loo.min():.5f} – {result.c_loo.max():.5f} |",
            f"| shuffle test: typical error with the leaf areas shuffled between the plants | median "
            f"{sh['shuffled_median']:.1f}%, best {sh['shuffled_best']:.1f}% of {sh['shuffles']} (p = {sh['p']:.4f}) |",
            "",
        ]
    lines += [
        "## Per plant",
        "",
        "Optical mass: the mean over the plant's photos, and how much single photos differ from it (standard "
        "deviation). Predicted: by the model learned without the plant.",
        "",
        "| plant | photos | optical mass | spread over the photos | measured leaf area, mm² | predicted, mm² | error |",
        "|---|---|---|---|---|---|---|",
    ]
    pred = {}
    if result is not None:
        pred = {p: (y, pr, e) for p, y, pr, e in zip(result.plants, result.y, result.pred, result.error_pct)}
    for plant, v in per_plant.items():
        m, sd = float(np.mean(v)), float(np.std(v, ddof=1)) if len(v) > 1 else 0.0
        row = f"| {plant} | {len(v)} | {m:,.0f} | ±{100 * sd / m:.1f}% |"
        if plant in pred:
            y, pr, e = pred[plant]
            err = f"**{_pct(e)}**" if abs(e) > 5 else _pct(e)
            row += f" {y:,.0f} | {pr:,.0f} | {err} |"
        else:
            row += " — | — | no measured leaf area |" if result is not None else " | | |"
        lines.append(row)
    if result is not None:
        lines += ["", "Errors over 5% in bold. + = predicted too high."]
    lines += [
        "",
        "## Files",
        "",
        "| file | |",
        "|---|---|",
        "| `per_photo.csv` | optical mass, plant pixels and pot width of every photo |",
        "| `per_plant.csv` | mean optical mass per plant, and its spread over the photos |",
    ]
    if result is not None:
        lines += [
            "| `evaluation.csv` | per plant: measured and predicted leaf area, error %, c learned without the plant |",
            "| `evaluation.json` | the scores, c, the shuffle test and the settings |",
        ]
    lines.append("| `settings.json` | the settings of the run |")
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")
