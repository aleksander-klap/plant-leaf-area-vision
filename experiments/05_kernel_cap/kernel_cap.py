"""Experiment 04: kernel and cap together, on the leaf + stem mask.

    python 04_kernel_cap/kernel_cap.py PHOTO_SET [--plants P1 P12] [--jobs 16] [--pictures-only]
    python 00_evaluation/evaluate.py 04_kernel_cap/results/runs.csv

Experiment 03 found that at kernel 64 a high cap fails: a 64 px window is full over single clumps of leaves, which
then count for many layers. A larger window is rarely full over a single clump, so a higher cap might work there.
This tests every kernel with every cap of experiment 03, on leaf + stem (experiment 02):

    per pixel:  f = share of leaf + stem in the kernel x kernel window,  layers = -ln(1 - min(f, cap))
    per photo:  sum over all pixels;   per plant: mean over its side photos

Kernels 32 to 256 px in steps of 16 (15) x 11 caps = 165 runs, plus the baseline (leaf only, 64, 0.90).
The first version of this experiment, with the leaf mask and cap 0.90 only, is kernel_size.py (results_leaf_only/).

Output (results/):
    runs.csv            one run per kernel and cap, plus the baseline, for 00_evaluation
    capped_share.csv    per plant and kernel: the share of the mask pixels whose window is fuller than 0.90
    settings.csv        what the settings mean, shown in the report
    method.html         the method in a few lines, shown in the report
    pictures/           where the window is fuller than 0.90 and 0.97, at a small, the baseline's and a large kernel
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data, zones  # noqa: E402

KERNELS = list(range(32, 257, 16))
CAPS = [0.85, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99, 0.995, 0.999]
PICTURE_KERNELS = [64, 144, 256]
PICTURE_PLANTS = ["P10", "P12"]

METHOD_HTML = """
<p><b>Question:</b> with the stems counted in, which window (kernel) and cap work best together?</p>
<p>Experiment 03 found that at kernel 64 a high cap fails: a 64 px window is full over single clumps of leaves, which
then count for many layers. A larger window is rarely full over a single clump, so a higher cap might work there.
This experiment tests every kernel with every cap, on the leaf + stem mask of experiment 02.</p>
<ol>
<li><b>Mask:</b> leaf + stem, everything the segmentation sees as plant (without the pot).</li>
<li><b>Per pixel:</b> f = the mask's share in the kernel × kernel window around it,
layers = −ln(1 − min(f, cap)).</li>
<li><b>Per photo:</b> the sum of the layers over all pixels; <b>per plant:</b> the mean over its side photos.</li>
</ol>
<p class="small muted">Sizes are in px at 1/4 of the photo resolution, where a leaf is about 35 px across. A run's
name is its kernel and cap: <code>k144_cap_0.990</code>. The baseline is leaf only, kernel 64, cap 0.90.</p>
"""


def photo_job(path):
    leaf, stem = data.masks(path)
    m = leaf | stem
    out: dict = {"baseline": data.optical_mass(leaf)}             # leaf only, kernel 64, cap 0.9
    for k in KERNELS:
        f = data.density(m, k)
        out |= {(k, cap): float(data.layers(f, cap).sum()) for cap in CAPS}
        out[("capped", k)] = float((f[m] > 0.9).mean())
    return out


def run_name(k, cap):
    return f"k{k:03d}_cap_{cap:.3f}"


def panel(img, m, k, box):
    """The mask (grey) with the pixels whose k px window is fuller than 0.90 (yellow) and 0.97 (red)."""
    f = data.density(m, k)
    out = img.astype(np.float32) * 0.4
    out[m] = img[m] * 0.4 + np.array([200, 200, 200]) * 0.6                  # mask: light grey
    out[m & (f > 0.90)] = (0, 200, 255)                                        # cap 0.90 acts: yellow
    out[m & (f > 0.97)] = (0, 0, 220)                                          # even 0.97 acts: red
    y0, y1, x0, x1 = box
    out = out.astype(np.uint8)[y0:y1, x0:x1]
    bar = np.full((52, out.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, f"kernel {k} px", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(bar, f"> 0.90: {(f[m] > 0.90).mean() * 100:.0f}% of the mask   > 0.97: {(f[m] > 0.97).mean() * 100:.0f}%",
                (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 60, 60), 1, cv2.LINE_AA)
    return np.vstack([bar, out])


def picture(path):
    """One photo (leaf + stem) at a few kernels, side by side, same crop."""
    img = data.read_photo(path)
    leaf, stem = data.masks(path)
    m = leaf | stem
    box = zones.crop_box(m)
    panels = [panel(img, m, k, box) for k in PICTURE_KERNELS]
    pad = np.full((panels[0].shape[0], 8, 3), 255, np.uint8)
    return np.hstack([x for p in panels for x in (p, pad)][:-1])


CAPTIONS = {
    "P10": "P10, an open plant, leaf + stem at kernel 64, 144 and 256: the mask (grey), the pixels whose window is "
           "fuller than 0.90 (yellow), where the 0.90 cap acts, and fuller than 0.97 (red). Only these pixels change "
           "when the cap is raised, and a larger window is full less often.",
    "P12": "P12, the densest plant, the same way. At kernel 64 the cap acts on 16% of the mask and a few spots are "
           "fuller than 0.97; at 144 only the dense core (5%) reaches 0.90 and nothing reaches 0.97; at 256 no window "
           "is that full, so the cap no longer matters.",
}


def write_pictures(photo_set, plants, out):
    pics = out / "pictures"
    pics.mkdir(parents=True, exist_ok=True)
    for old in pics.glob("*.jpg"):
        old.unlink()
    rows = []
    for d in data.plant_dirs(photo_set, plants):
        _, path = data.side_photos(d)[0]
        name = f"{data.plant_name(d)}_{path.stem.split('_')[-1]}.jpg"
        cv2.imwrite(str(pics / name), picture(path), [cv2.IMWRITE_JPEG_QUALITY, 85])
        rows.append((name, CAPTIONS.get(data.plant_name(d), data.plant_name(d))))
    with open(pics / "captions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "caption"])
        w.writerows(rows)
    return pics


def write_report_notes(folder):
    (folder / "method.html").write_text(METHOD_HTML.strip() + "\n", encoding="utf-8")
    with open(folder / "settings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "meaning", "values"])
        w.writerow(["kernel", "k: side of the square window, in px at 1/4 photo resolution (a leaf is ~35 px "
                    "across), in which the mask share around every pixel is measured. A small window sees a few "
                    "leaves, a large one a whole part of the plant.",
                    f"{KERNELS[0]} to {KERNELS[-1]} px in steps of {KERNELS[1] - KERNELS[0]} (baseline 64)"])
        w.writerow(["cap", "highest mask share f a window may have when it is turned into layers, "
                    "layers = -ln(1 - min(f, cap)). It limits how many layers a nearly solid window counts: 0.90 = "
                    "2.3, 0.99 = 4.6, 0.999 = 6.9 layers.", ", ".join(f"{c:g}" for c in CAPS) + " (baseline 0.9)"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--plants", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=data.JOBS)
    ap.add_argument("--pictures-only", action="store_true", help="only make the pictures, no runs")
    a = ap.parse_args()
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    write_report_notes(out)

    if not a.pictures_only:
        photos = data.for_each_photo(a.photo_set, photo_job, a.plants, a.jobs)
        runs = [(data.BASELINE, {}, data.plant_means(photos, lambda r: r["baseline"]))]
        runs += [(run_name(k, cap), {"kernel": k, "cap": cap},
                  data.plant_means(photos, lambda r, key=(k, cap): r[key])) for k in KERNELS for cap in CAPS]
        print(data.write_runs(out / "runs.csv", runs))
        shares = {k: data.plant_means(photos, lambda r, k=k: r[("capped", k)]) for k in KERNELS}
        with open(out / "capped_share.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["plant", *[f"kernel_{k}_pct_over_0.90" for k in KERNELS]])
            for p in shares[KERNELS[0]]:
                w.writerow([p, *[round(shares[k][p] * 100, 1) for k in KERNELS]])

    print(write_pictures(a.photo_set, a.plants or PICTURE_PLANTS, out))


if __name__ == "__main__":
    main()
