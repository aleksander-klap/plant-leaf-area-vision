"""Experiment 02: the baseline with the stems and twigs counted in.

    python 02_stems_as_leaf/stems_as_leaf.py PHOTO_SET [--plants P1 P12] [--jobs 16]
    python 00_evaluation/evaluate.py 02_stems_as_leaf/results/runs.csv

The mask check (experiment 01) showed that stems, twigs, brown leaf edges and parts of reddish leaves are not in
the leaf mask: they are the "stem" part of the segmentation. Here the optical mass is computed on leaf + stem, i.e.
on everything the segmentation sees as plant (without the pot), with everything else as in the baseline:

    mask:       leaf (M1, the baseline)  or  leaf + stem
    per photo:  optical mass = sum over all pixels of -ln(1 - min(f, 0.9)),  f = mask share in the 64 px window
    per plant:  mean over its side photos

One run (leaf + stem) against the baseline (leaf). Nothing is tuned, so there is no luck from choosing among runs.

Output (results/):
    runs.csv        the run and the baseline, for 00_evaluation
    stem_share.csv  per plant: the stem pixels added, as a % of the leaf pixels
    settings.csv    what the setting means, shown in the report
    method.html     the method in a few lines, shown in the report
    pictures/       one photo per plant: the mask, and the leaf layers with and without the stems
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
CAP = 0.9
PICTURE_PLANTS = ["P8", "P3", "P10"]      # the most red twigs, a dense and an open plant

METHOD_HTML = """
<p><b>Question:</b> does the optical mass get better if the stems and twigs count as leaf?</p>
<p>The mask check (experiment 01) showed that the leaf mask leaves out 12–20% of the plant: twigs, brown leaf edges
and parts of reddish leaves. The segmentation calls them "stem". Two reasons they might belong in the optical
mass:</p>
<ul>
<li><b>Some of it is leaf</b> the mask misses (brown edges, reddish leaves).</li>
<li><b>Twigs block the view</b> like leaves do. The optical mass reads how much wall shows through the plant, and a
twig in front of the wall is not a gap.</li>
</ul>
<p><b>The method</b> is the baseline with only the mask changed:</p>
<ol>
<li><b>Mask:</b> leaf + stem, i.e. everything the segmentation sees as plant (without the pot), instead of leaf
only.</li>
<li><b>Per pixel:</b> f = the mask's share in the 64 px window around it, layers = −ln(1 − min(f, 0.9)).</li>
<li><b>Per photo:</b> the sum of the layers over all pixels; <b>per plant:</b> the mean over its side photos.</li>
</ol>
<p class="small muted">One run against the baseline, with nothing tuned, so the honest score is the run's own score.
The kernel (64 px) and the cap (0.90) are the baseline's; the cap is tested in experiment 03.</p>
"""


def photo_job(path):
    leaf, stem = data.masks(path)
    return {"leaf+stem": data.optical_mass(leaf | stem, KERNEL, CAP), "baseline": data.optical_mass(leaf),
            "stem_share": stem.sum() / max(leaf.sum(), 1)}


def label(img, text, sub=""):
    """A white title strip above a picture."""
    bar = np.full((52, img.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(bar, sub, (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 90, 90), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def picture(path):
    """One photo four ways, same crop: photo | mask (leaf green, stem orange) | layers, leaf | layers, leaf + stem."""
    img = data.read_photo(path)
    leaf, stem = data.masks(path)
    both = leaf | stem
    box = zones.crop_box(both)
    y0, y1, x0, x1 = box
    mask = (img.astype(np.float32) * 0.35).astype(np.uint8)
    mask[leaf] = (60, 220, 60)
    mask[stem & ~leaf] = (0, 140, 255)
    panels = [
        label(img[y0:y1, x0:x1].copy(), f"{data.plant_name(path)} {path.stem.split('_')[-1]}",
              f"stems add {stem.sum() / max(leaf.sum(), 1) * 100:.0f}% to the leaf pixels"),
        label(mask[y0:y1, x0:x1], "mask: leaf (green), stem (orange)",
              f"leaf {int(leaf.sum()):,} px, stem {int((stem & ~leaf).sum()):,} px"),
        label(zones.pixel_picture(img, leaf, KERNEL, CAP, box=box), "layers, leaf only (baseline)",
              f"optical mass {data.optical_mass(leaf, KERNEL, CAP):,.0f}"),
        label(zones.pixel_picture(img, both, KERNEL, CAP, box=box), "layers, leaf + stem",
              f"optical mass {data.optical_mass(both, KERNEL, CAP):,.0f}"),
    ]
    pad = np.full((panels[0].shape[0], 8, 3), 255, np.uint8)
    row = np.hstack([x for p in panels for x in (p, pad)][:-1])
    leg = np.full((34, row.shape[1], 3), 255, np.uint8)
    leg[10:24, 140:440] = zones.legend(300, 14)
    cv2.putText(leg, "leaf layers  0", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(leg, f"{zones.LAYER_MAX:g}   (mask share 0.9 = 2.30 layers)", (448, 22), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return np.vstack([row, leg])


CAPTIONS = {
    "P8": "P8, the plant with the most red twigs (here the stems add 21% to the leaf pixels). The twigs (orange) run "
          "through the whole plant; counted in, they fill the gaps in its central column, which reaches the cap "
          "(yellow). The optical mass rises by 35% (156,806 to 211,835).",
    "P3": "P3, a dense plant. The stems sit mostly in the lower core, between the leaves and on reddish leaf parts. "
          "Counted in, the core fills up to the cap over a large area: the optical mass rises by 41% (201,264 to "
          "284,137), much more than the 22% extra pixels, because a fuller window counts for more layers.",
    "P10": "P10, an open plant. The stems are mainly the bare shoots at the base and some leaf edges. The dense "
           "clumps grow a little and the optical mass rises by 23% (163,793 to 201,755).",
}


def write_pictures(photo_set, plants):
    pics = HERE / "results" / "pictures"
    pics.mkdir(parents=True, exist_ok=True)
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
    """results/settings.csv and results/method.html, shown in the report."""
    (folder / "method.html").write_text(METHOD_HTML.strip() + "\n", encoding="utf-8")
    with open(folder / "settings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "meaning", "values"])
        w.writerow(["mask", "which pixels count as plant: leaf only (the baseline), or leaf + stem (everything the "
                    "segmentation sees as plant, without the pot)", "leaf (baseline), leaf+stem"])


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
        runs = [(data.BASELINE, {"mask": "leaf"}, data.plant_means(photos, lambda r: r["baseline"])),
                ("leaf_stem", {"mask": "leaf+stem"}, data.plant_means(photos, lambda r: r["leaf+stem"]))]
        print(data.write_runs(out / "runs.csv", runs))
        share = data.plant_means(photos, lambda r: r["stem_share"])
        with open(out / "stem_share.csv", "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["plant", "stem_pixels_pct_of_leaf"])
            for p, v in sorted(share.items(), key=lambda t: data.plant_sort_key(t[0])):
                w.writerow([p, round(v * 100, 1)])
        print("stem pixels added, % of the leaf pixels: "
              + ", ".join(f"{p} {v * 100:.0f}" for p, v in sorted(share.items(),
                                                                   key=lambda t: data.plant_sort_key(t[0]))))
    print(write_pictures(a.photo_set, a.plants or PICTURE_PLANTS))


if __name__ == "__main__":
    main()
