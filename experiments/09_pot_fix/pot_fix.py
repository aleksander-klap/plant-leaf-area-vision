"""Experiment 09: the pot fix in the segmentation, and scaling every plant by its pot.

    python 09_pot_fix/pot_fix.py PHOTO_SET [--plants P2 P12] [--jobs 16]
    python 00_evaluation/evaluate.py 09_pot_fix/results/runs.csv

Two changes, tested on the baseline and on the best run of experiment 04:

1. Pot fix (common/masks.py): the rim line is measured from the pot's bottom (bottom - 0.945 x width), nothing above
   it counts as pot, and the trunk zone just above the rim is gone. Before, dark shaded leaves right above the pot
   merged with it and were counted as neither leaf nor stem (P12's dense core).
2. Pot scaling (common/data.py, pot_scale): every plant's optical mass is multiplied by (199 / its median pot width)^2,
   so all plants are on the same scale even if the camera distance differed a little.

The old masks can't be made any more (common/masks.py has changed), so their optical masses are taken from experiment
04's runs.csv, which was made with them: the baseline and k144_cap_0.995.

Output (results/):
    runs.csv        the 5 runs and the baseline, for 00_evaluation
    pot_scale.csv   per plant: the median pot width and the scale factor
    settings.csv    what the settings mean, shown in the report
    method.html     the method in a few lines, shown in the report
    pictures/       old and new masks around the pot (made once, with the original segmentation, when the fix was made)
"""
import argparse
import csv
import sys
from pathlib import Path

import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data  # noqa: E402

OLD_RUNS = HERE.parent / "04_kernel_cap" / "results" / "runs.csv"     # made with the masks before the fix
MODELS = {"baseline": dict(stems=False, kernel=64, cap=0.90, old_run="baseline"),
          "04 best": dict(stems=True, kernel=144, cap=0.995, old_run="k144_cap_0.995")}

METHOD_HTML = """
<p><b>Question:</b> do the baseline and the best run of experiment 04 get better when the segmentation stops
cutting leaves away at the pot, and when every plant is brought to the same scale by its pot?</p>
<p><b>1. Pot fix</b> (in the segmentation, <code>common/masks.py</code>). Before, dark, shaded leaves right above
the pot merged with the dark pot into one "background object", where neither leaf nor stem was looked for; P12 lost a
dense, fully covered triangle of leaves this way. Now:</p>
<ul>
<li>the rim line is measured from the pot's bottom, which leaves never hide: bottom − 0.945 × the pot width (all pots
are the same model);</li>
<li>nothing above the rim line counts as pot: the part of a dark object above it is freed;</li>
<li>the "trunk zone" just above the rim, where non-green pixels never counted as leaf, is gone.</li>
</ul>
<p><b>2. Pot scaling.</b> The optical mass is in pixels, the leaf area in mm². If the camera distance differed between
plants, the same plant would give a different pixel count. Every plant's optical mass is multiplied by
(199 / its median pot width)², 199 px being the median over all photos. The median over the plant's 18 photos is
used because a single photo's width jitters by 2–3% with the detection.</p>
<p class="small muted">Both are tested on the baseline (leaf, kernel 64, cap 0.90) and on the best run of 04 (leaf
+ stem, kernel 144, cap 0.995). The "old masks" runs are taken from experiment 04, made before the fix. These are
not a sweep: compare each model's three versions with each other; the nested score doesn't mean much here.</p>
"""


def photo_job(path):
    leaf, stem = data.masks(path)
    out = {"pot_width": data.pot_width(path)}
    for name, m in MODELS.items():
        out[name] = data.optical_mass(leaf | stem if m["stems"] else leaf, m["kernel"], m["cap"])
    return out


def old_runs():
    """{old run name: {plant: optical mass}} from experiment 04 (masks before the fix)."""
    runs = {}
    for r in csv.DictReader(open(OLD_RUNS, newline="")):
        runs.setdefault(r["run"], {})[r["plant"]] = float(r["optical_mass"])
    return runs


def write_report_notes(folder):
    (folder / "method.html").write_text(METHOD_HTML.strip() + "\n", encoding="utf-8")
    with open(folder / "settings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "meaning", "values"])
        w.writerow(["model", "baseline: leaf mask, kernel 64, cap 0.90. 04 best: leaf + stem mask, kernel 144, cap "
                    "0.995", "baseline, 04 best"])
        w.writerow(["masks", "old: the segmentation before the pot fix (results of experiment 04). new: with the pot "
                    "fix", "old, new"])
        w.writerow(["pot_scale", "yes: every plant's optical mass multiplied by (199 / its median pot width)^2",
                    "no, yes"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--plants", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=data.JOBS)
    a = ap.parse_args()
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    write_report_notes(out)

    photos = data.for_each_photo(a.photo_set, photo_job, a.plants, a.jobs)
    scale = data.pot_scale(photos)
    old = old_runs()
    runs = [(data.BASELINE, {"model": "baseline", "masks": "old", "pot_scale": "no"}, old["baseline"])]
    for name, m in MODELS.items():
        tag = name.replace(" ", "_")
        new = data.plant_means(photos, lambda r, n=name: r[n])
        if name != "baseline":
            runs.append((f"{tag}_old_masks", {"model": name, "masks": "old", "pot_scale": "no"}, old[m["old_run"]]))
        runs.append((f"{tag}_new_masks", {"model": name, "masks": "new", "pot_scale": "no"}, new))
        runs.append((f"{tag}_new_masks_scaled", {"model": name, "masks": "new", "pot_scale": "yes"},
                     {p: v * scale[p] for p, v in new.items()}))
    print(data.write_runs(out / "runs.csv", runs))

    widths = {}
    for plant, _, _, r in photos:
        widths.setdefault(plant, []).append(r["pot_width"])
    with open(out / "pot_scale.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plant", "median_pot_width_px", "min_px", "max_px", "scale"])
        for p in sorted(scale, key=data.plant_sort_key):
            v = np.array(widths[p], float)
            w.writerow([p, round(float(np.nanmedian(v)), 1), round(float(np.nanmin(v)), 1),
                        round(float(np.nanmax(v)), 1), round(scale[p], 4)])
    print("scale: " + ", ".join(f"{p} {scale[p]:.3f}" for p in sorted(scale, key=data.plant_sort_key)))


if __name__ == "__main__":
    main()
