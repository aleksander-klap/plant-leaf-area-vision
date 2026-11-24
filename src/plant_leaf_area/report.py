"""report.md: the result of a run on one page, with charts, in the style of the experiment reports."""
import datetime
import shutil

import numpy as np

from . import figures


def _pct(v):
    return f"{v:+.1f}%"


def write(path, settings, n_photos, per_plant, result, labels_path, seconds):
    """per_plant: {plant: [optical mass of every photo]}; result: evaluation.Result, or None if not evaluated.
    The charts go to report_files/ next to the report."""
    files = path.parent / "report_files"
    shutil.rmtree(files, ignore_errors=True)
    files.mkdir(parents=True)
    figures.style()
    res = "full" if settings.scale == 4 else "1/4"
    L = [
        "# Results",
        "",
        f"Run on {datetime.date.today().isoformat()} · **{n_photos} photos of {len(per_plant)} plants** · "
        f"kernel {settings.kernel} px, cap {settings.cap}, {res} resolution · {seconds:.0f} s",
        "",
    ]
    if result is not None:
        L += _toc() + _how_to_read() + _summary(result) + _method(settings, labels_path) + _fit(result, files)
        L += _plants(result, per_plant, files)
    L += _photos(per_plant, files)
    if result is not None:
        L += _c_rounds(result, files) + _shuffle(result, files)
    L += _files(result is not None)
    path.write_text("\n".join(L) + "\n", encoding="utf-8")


def _img(fig, files, name, alt):
    figures.save(fig, files / f"{name}.png")
    return f"![{alt}]({files.name}/{name}.png)"


def _toc():
    return [
        "**Contents**",
        "",
        "1. [Summary](#summary): the scores in short",
        "2. [The method](#the-method): the settings of this run",
        "3. [The fit and the predictions](#the-fit-and-the-predictions): the model, and every plant predicted "
        "without it",
        "4. [Per plant](#per-plant): how far off each plant is",
        "5. [Optical mass over the photos](#optical-mass-over-the-photos): how much one view of a plant differs "
        "from the next",
        "6. [c in every round](#c-in-every-round-does-one-plant-decide-the-model): whether one plant decides the "
        "model",
        "7. [Shuffle test](#shuffle-test-is-the-fit-real-or-luck): whether the fit is real or luck",
        "",
    ]


def _how_to_read():
    return [
        "<details><summary>How to read this page</summary>",
        "",
        "**The model.** `leaf area = c × optical mass`: a straight line through zero, with c the one number learned "
        "from the plants.",
        "",
        "**Leave-one-out.** Every plant in turn is left out, c is learned from the others, and the left-out plant is "
        "predicted. Each plant is predicted by a model that never saw it.",
        "",
        "**Typical error** = the RMSE of those predictions as a % of the mean leaf area. **Mean error** = the "
        "average of the absolute errors in %. **R²**: 1 is perfect, 0 is no better than guessing the average plant.",
        "",
        "**Noise.** With 13 plants, one plant more or less moves the typical error by about a point.",
        "",
        "**The settings were chosen on these plants** (kernel and cap, in experiment 05), so this score is somewhat "
        "optimistic: new plants are needed for an independent test.",
        "",
        "</details>",
        "",
    ]


def _summary(r):
    s = r.scores
    worst = r.plants[int(np.argmax(np.abs(r.error_pct)))]
    outside = ", ".join(f"{p} {_pct(e)}" for p, e in sorted(zip(r.plants, r.error_pct), key=lambda t: -abs(t[1]))
                        if abs(e) > 5)
    return [
        "## Summary",
        "",
        f"- **{s['typical_error']:.2f}%** typical error (RMSE as % of the mean leaf area)",
        f"- **{s['r2']:.3f}** R²",
        f"- **{s['mean_abs_error']:.2f}%** mean absolute error; worst plant {worst}, {s['worst']:.1f}% off",
        f"- **{s['within_5']} / {s['plants']}** plants within 5%" + (f" (outside: {outside})" if outside else ""),
        f"- **{r.c:.4f}** c, learned on all plants (mm² per unit of optical mass)",
        f"- shuffle test: **p = {r.shuffle['p']:.3f}**",
        "",
    ]


def _method(settings, labels_path):
    res = "full (6000 × 4000)" if settings.scale == 4 else "1/4 (1500 × 1000)"
    return [
        "## The method",
        "",
        "Every side photo: the plant mask (every plant pixel in front of the wall, leaves and twigs alike, the pot "
        "taken out), the leaf density in a window around every pixel, leaf layers by Beer-Lambert, summed: the "
        "optical mass. The mean over the plant's photos is its optical mass. The steps are described, with "
        "pictures, in the [main README](../README.md#the-method).",
        "",
        "| setting | value | what it does |",
        "|---|---|---|",
        f"| kernel | {settings.kernel} px | side of the window of the leaf density (px at 1/4 resolution) |",
        f"| cap | {settings.cap} | the density is capped at this before Beer-Lambert: at most "
        f"{-np.log1p(-settings.cap):.1f} layers |",
        f"| resolution | {res} | the resolution the photos are segmented at |",
        f"| leaf areas | `{labels_path}` | the measured leaf areas the model is learned from |",
        "",
    ]


def _fit(r, files):
    return [
        "## The fit and the predictions",
        "",
        "Left: every plant's optical mass against its measured leaf area, with the line "
        "`leaf area = c × optical mass` fitted on all plants. Right: each plant predicted by the model learned "
        "without it (leave-one-out), against its measured leaf area. On the black line the prediction is perfect; "
        "inside the green band it is within 5%.",
        "",
        _img(figures.fit(r.plants, r.x, r.y, r.c), files, "fit", "fit")
        + _img(figures.predicted(r.plants, r.y, r.pred), files, "predicted", "predicted vs measured"),
        "",
    ]


def _plants(r, per_plant, files):
    L = [
        "## Per plant",
        "",
        "The error of every plant when it is predicted by the model learned without it. Above 0: predicted too "
        "high; below: too low.",
        "",
        _img(figures.plant_errors(r.plants, r.error_pct), files, "plant_errors", "error per plant"),
        "",
        "| plant | photos | optical mass | measured leaf area, mm² | predicted, mm² | error | c without the plant |",
        "|---|---|---|---|---|---|---|",
    ]
    for p, x, y, pr, e, c in zip(r.plants, r.x, r.y, r.pred, r.error_pct, r.c_loo):
        err = f"**{_pct(e)}**" if abs(e) > 5 else _pct(e)
        L.append(f"| {p} | {len(per_plant[p])} | {x:,.0f} | {y:,.0f} | {pr:,.0f} | {err} | {c:.4f} |")
    L += ["", "Errors over 5% in bold."]
    if r.no_leaf_area:
        L += ["", "Not in the test (no measured leaf area): "
              + ", ".join(f"{p} (optical mass {np.mean(per_plant[p]):,.0f})" for p in r.no_leaf_area) + "."]
    return L + [""]


def _photos(per_plant, files):
    rows = []
    for p, v in per_plant.items():
        v = np.asarray(v, float)
        sd = 100 * v.std(ddof=1) / v.mean() if len(v) > 1 else 0.0
        rows.append(f"| {p} | {len(v)} | {v.mean():,.0f} | ±{sd:.1f}% | {100 * (v.min() / v.mean() - 1):+.0f}% "
                    f"… {100 * (v.max() / v.mean() - 1):+.0f}% |")
    return [
        "## Optical mass over the photos",
        "",
        "Every plant is photographed from 18 sides. Each dot is one photo's optical mass, as a % of the plant's mean: "
        "a plant seen from its wide or its narrow side gives a different number. The mean over all photos averages "
        "that out; it is the plant's optical mass.",
        "",
        _img(figures.photo_spread(per_plant), files, "photo_spread", "optical mass of every photo"),
        "",
        "| plant | photos | mean optical mass | standard deviation | lowest … highest photo |",
        "|---|---|---|---|---|",
        *rows,
        "",
    ]


def _c_rounds(r, files):
    spread = (r.c_loo.max() - r.c_loo.min()) / 2 / r.c * 100
    far = r.plants[int(np.argmax(np.abs(r.c_loo - r.c)))]
    return [
        "## c in every round: does one plant decide the model?",
        "",
        f"Leave-one-out fits c {len(r.plants)} times, each time without one plant. Each point is the c fitted "
        "**without** the plant on the x-axis; the dashed line is c fitted on all plants. A flat line means no single "
        "plant drives the model. A point far from the line means that plant on its own pulls c up or down, and it is "
        f"usually also predicted badly. Here c moves by ± {spread:.1f}%; the plant that moves it most is {far}.",
        "",
        _img(figures.c_rounds(r.plants, r.c_loo, r.c), files, "c_rounds", "c in every round"),
        "",
    ]


def _shuffle(r, files):
    sh = r.shuffle
    n_better = int(np.sum(r.shuffled <= sh["real"]))
    return [
        "## Shuffle test: is the fit real or luck?",
        "",
        f"The leaf areas are shuffled randomly between the plants {sh['shuffles']} times, so they no longer belong "
        "to their photos, and the same leave-one-out test is run each time. Grey: the errors of the shuffled data. "
        "Red: the error of the real data. If red lies left of nearly all of grey, the optical mass really carries "
        "the leaf area. p is the share of shuffles that did as well as the real data (p < 0.05: not luck). Here "
        f"{n_better} of {sh['shuffles']} shuffles did as well (median {sh['shuffled_median']:.1f}%, best "
        f"{sh['shuffled_best']:.1f}%), p = {sh['p']:.3f}.",
        "",
        _img(figures.shuffle(sh["real"], r.shuffled, sh["p"]), files, "shuffle", "shuffle test"),
        "",
    ]


def _files(evaluated):
    L = [
        "## Files",
        "",
        "| file | |",
        "|---|---|",
        "| `per_photo.csv` | optical mass, plant pixels and pot width of every photo |",
        "| `per_plant.csv` | mean optical mass per plant, and its spread over the photos |",
    ]
    if evaluated:
        L += ["| `evaluation.csv` | per plant: measured and predicted leaf area, error %, c learned without the plant |",
              "| `evaluation.json` | the scores, c, the shuffle test and the settings |"]
    return L + ["| `settings.json` | the settings of the run |", "| `report_files/` | the charts of this page |"]
