"""Experiment 03: the cap, from 0.85 to 0.999, on both masks: leaf only (the baseline) and leaf + stem (experiment 02).

    python 03_cap/cap.py PHOTO_SET [--plants P1 P12] [--jobs 16] [--pictures-only]
    python 00_evaluation/evaluate.py 03_cap/results/runs.csv

Every pixel gets -ln(1 - min(f, cap)) leaf layers, f = the share of the mask in the 64 px window around it. The cap
stops a nearly solid window from counting for an unlimited number of layers: 0.90 allows at most 2.30 layers. In a
dense core, leaves hide behind leaves deeper than that, so a higher cap might count them:

    cap      0.85  0.90  0.95  0.97  0.98  0.99  0.995  0.999
    layers   1.90  2.30  3.00  3.51  3.91  4.61  5.30   6.91

Every cap on both masks, at the baseline's kernel (64 px): 22 runs. Counting the stems fills the windows, so the cap
acts on more pixels with leaf + stem than with leaf only.

Output (results/):
    runs.csv            one run per mask and cap, plus the baseline, for 00_evaluation
    capped_share.csv    per plant and mask: the share of the mask pixels whose window is fuller than 0.90
    settings.csv        what the settings mean, shown in the report
    method.html         the method in a few lines, shown in the report
    pictures/           where the window is fuller than 0.90, with and without the stems
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

KERNEL = 64
CAPS = [0.85, 0.90, 0.92, 0.94, 0.95, 0.96, 0.97, 0.98, 0.99, 0.995, 0.999]
MASKS = ["leaf", "leaf+stem"]
PICTURE_PLANTS = ["P10", "P12"]

METHOD_HTML = """
<p><b>Question:</b> is 0.90 the right cap, and does the answer change when the stems are counted in?</p>
<p>Every pixel gets −ln(1 − min(f, cap)) leaf layers, where f is the mask's share in the 64 px window around it. The
cap stops a nearly solid window from counting for an unlimited number of layers. At 0.90 a window counts for at most
2.30 layers, but in a dense core leaves hide behind leaves deeper than that. A higher cap lets those windows count
for more:</p>
<table><tr><th>cap</th><td>0.85</td><td>0.90</td><td>0.95</td><td>0.97</td><td>0.98</td><td>0.99</td><td>0.995</td>
<td>0.999</td></tr>
<tr><th>max layers</th><td>1.90</td><td>2.30</td><td>3.00</td><td>3.51</td><td>3.91</td><td>4.61</td><td>5.30</td>
<td>6.91</td></tr></table>
<p><b>The method</b> is the baseline with the cap changed, on both masks:</p>
<ol>
<li><b>Mask:</b> leaf only (the baseline), or leaf + stem (experiment 02).</li>
<li><b>Per pixel:</b> f = the mask's share in the 64 px window around it, layers = −ln(1 − min(f, cap)).</li>
<li><b>Per photo:</b> the sum of the layers over all pixels; <b>per plant:</b> the mean over its side photos.</li>
</ol>
<p class="small muted">The cap only changes pixels whose window is fuller than the cap. Counting the stems fills the
windows, so with leaf + stem the cap acts on more of the plant. A run's name is its mask and cap:
<code>leaf_stem_cap_0.990</code>. <code>leaf_cap_0.900</code> is the baseline itself.</p>
"""


def photo_job(path):
    leaf, stem = data.masks(path)
    out: dict = {"baseline": data.optical_mass(leaf)}             # leaf only, kernel 64, cap 0.9
    for mask, m in (("leaf", leaf), ("leaf+stem", leaf | stem)):
        f = data.density(m, KERNEL)
        out |= {(mask, cap): float(data.layers(f, cap).sum()) for cap in CAPS}
        out[("capped", mask)] = float((f[m] > 0.9).mean())
    return out


def panel(img, m, title, box):
    """The mask (grey) with the pixels whose window is fuller than 0.90 (yellow) and 0.97 (red)."""
    f = data.density(m, KERNEL)
    out = img.astype(np.float32) * 0.4
    out[m] = img[m] * 0.4 + np.array([200, 200, 200]) * 0.6                  # mask: light grey
    out[m & (f > 0.90)] = (0, 200, 255)                                        # cap 0.90 acts: yellow
    out[m & (f > 0.97)] = (0, 0, 220)                                          # even 0.97 acts: red
    y0, y1, x0, x1 = box
    out = out.astype(np.uint8)[y0:y1, x0:x1]
    bar = np.full((52, out.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, title, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(bar, f"> 0.90: {(f[m] > 0.90).mean() * 100:.0f}% of the mask   > 0.97: {(f[m] > 0.97).mean() * 100:.0f}%",
                (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 60, 60), 1, cv2.LINE_AA)
    return np.vstack([bar, out])


def picture(path):
    """One photo with both masks, side by side, same crop."""
    img = data.read_photo(path)
    leaf, stem = data.masks(path)
    box = zones.crop_box(leaf | stem)
    p1 = panel(img, leaf, f"{data.plant_name(path)}, leaf only (baseline)", box)
    p2 = panel(img, leaf | stem, f"{data.plant_name(path)}, leaf + stem", box)
    return np.hstack([p1, np.full((p1.shape[0], 8, 3), 255, np.uint8), p2])


def run_name(mask, cap):
    return f"{mask.replace('+', '_')}_cap_{cap:.3f}"


def write_report_notes(folder):
    (folder / "method.html").write_text(METHOD_HTML.strip() + "\n", encoding="utf-8")
    with open(folder / "settings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "meaning", "values"])
        w.writerow(["mask", "which pixels count as plant: leaf only (the baseline), or leaf + stem (everything the "
                    "segmentation sees as plant, without the pot; experiment 02)", "leaf, leaf+stem"])
        w.writerow(["cap", "highest mask share f a window may have when it is turned into layers, "
                    "layers = -ln(1 - min(f, cap)). It limits how many layers a nearly solid window counts: 0.90 = "
                    "2.3, 0.99 = 4.6, 0.999 = 6.9 layers.", ", ".join(f"{c:g}" for c in CAPS) + " (baseline 0.9)"])


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


CAPTIONS = {
    "P10": "P10, an open plant, at kernel 64: the mask (grey), the pixels whose window is fuller than 0.90 (yellow), "
           "where the 0.90 cap acts, and fuller than 0.97 (red), where even a 0.97 cap would act. Only these pixels "
           "change when the cap is raised. On this open plant the cap acts on a few small clumps: 3% of the mask "
           "with leaf only, 7% with the stems.",
    "P12": "P12, the densest plant, the same way. With the stems counted in, the gaps in the core fill up: the cap "
           "acts on 16% of the mask instead of 6%, and a few spots are even fuller than 0.97.",
}


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
        runs = [(data.BASELINE, {"mask": "leaf", "cap": 0.9}, data.plant_means(photos, lambda r: r["baseline"]))]
        runs += [(run_name(mask, cap), {"mask": mask, "cap": cap},
                  data.plant_means(photos, lambda r, key=(mask, cap): r[key])) for mask in MASKS for cap in CAPS]
        print(data.write_runs(out / "runs.csv", runs))

        shares = {mask: data.plant_means(photos, lambda r, mask=mask: r[("capped", mask)]) for mask in MASKS}
        with open(out / "capped_share.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["plant", *[f"{mask}_mask_pixels_over_0.90_pct" for mask in MASKS]])
            for p in shares[MASKS[0]]:
                w.writerow([p, *[round(shares[mask][p] * 100, 1) for mask in MASKS]])
        for mask in MASKS:
            print(f"{mask}: mask pixels with a window fuller than 0.90: "
                  + ", ".join(f"{p} {v * 100:.0f}%" for p, v in shares[mask].items()))

    print(write_pictures(a.photo_set, a.plants or PICTURE_PLANTS, out))


if __name__ == "__main__":
    main()
