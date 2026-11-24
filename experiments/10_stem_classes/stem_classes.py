"""Experiment 08: split the "stem" pixels into leaf edges, missed leaf and twigs, and treat twigs as wood.

    python 08_stem_classes/stem_classes.py PHOTO_SET [--plants P2 P8] [--jobs 16]
    python 00_evaluation/evaluate.py 08_stem_classes/results/runs.csv

The "stem" mask of common/masks.py is not a stem detector: it is every pixel the segmentation sees as plant
in front of the wall but did not accept as leaf. Counting all of it as leaf (experiment 03) overcounts P8, the plant
with the most red twigs. Here the stem pixels are split into three classes with fixed rules (chosen before scoring):

    edge   stem pixels within EDGE px of a leaf pixel: the blurred rim of the leaf itself      -> leaf
    wide   the rest, in pieces at least WIDE px across (~5 mm) and compact (area <= MAX_ELONG x width^2, the
           same shape test as the leaf mask): leaf parts the leaf rules missed                -> leaf
    twig   everything else: thin, or long and narrow (a thick red stem is ~5 mm wide too)     -> wood

Twigs have no leaf area, but they block the view like leaves. So in the twig-corrected run they count for how full a
window is, but their share of the layers is taken out (the woody correction of canopy instruments):

    f_all  = share of (leaf + edge + wide + twig) in the window
    f_leaf = share of (leaf + edge + wide) in the window
    value  = -ln(1 - min(f_all, cap)) x f_leaf / f_all

Runs, all at kernel 144 and cap 0.99 (the best settings of experiment 03):
    leaf            leaf only
    all_stems       leaf + every stem pixel (experiment 03)
    no_twigs        leaf + edge + wide; twigs left out
    twig_corrected  leaf + edge + wide, twigs only block the view (the formula above)
plus the baseline (leaf, kernel 64, cap 0.90).

Output (results/):
    runs.csv            for 00_evaluation
    classes.csv         per plant: the pixels of each class, as % of the leaf pixels
    pictures/           the classes drawn on one photo of every plant (00_evaluation shows them in the report)
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data  # noqa: E402

KERNEL = 144
CAP = 0.99
EDGE = 2          # px: stem pixels this close to a leaf are its rim
WIDE = 7          # px (~5 mm at 0.75 mm/px): a missed leaf piece is at least this wide ...
MAX_ELONG = 3.0   # ... and compact: area / width^2 at most this (as MAX_ELONG in masks.py); longer pieces are twigs
RUNS = ["leaf", "all_stems", "no_twigs", "twig_corrected"]
# BGR colours of the classes in the pictures
COLOURS = {"leaf": (0, 200, 0), "edge": (255, 220, 0), "wide": (0, 150, 255), "twig": (0, 0, 230)}
EXTRA = {"P8": [220]}          # more photos in the pictures for these plants (angles): P8 has the most twigs


def classes(path):
    """leaf, edge, wide, twig: boolean masks of one photo."""
    leaf, stem = data.masks(path)
    stem = stem & ~leaf
    near_leaf = cv2.distanceTransform((~leaf).astype(np.uint8), cv2.DIST_L2, 3) <= EDGE
    edge = stem & near_leaf
    rest = (stem & ~edge).astype(np.uint8)
    n, cc, st, _ = cv2.connectedComponentsWithStats(rest, connectivity=8)
    width = np.zeros(n)
    np.maximum.at(width, cc.ravel(), 2 * cv2.distanceTransform(rest, cv2.DIST_L2, 5).ravel())
    area = st[:, cv2.CC_STAT_AREA].astype(float)
    leafy = (width >= WIDE) & (area <= MAX_ELONG * np.maximum(width, 1) ** 2)
    leafy[0] = False
    wide = leafy[cc] & (rest > 0)
    twig = (rest > 0) & ~wide
    return leaf, edge, wide, twig


def photo_job(path):
    leaf, edge, wide, twig = classes(path)
    leafish = leaf | edge | wide
    f_leaf = data.density(leafish, KERNEL)
    f_all = data.density(leafish | twig, KERNEL)
    lay_all = data.layers(f_all, CAP)
    corrected = np.divide(lay_all * f_leaf, f_all, out=np.zeros_like(f_all), where=f_all > 1e-6)
    n = max(int(leaf.sum()), 1)
    return {"baseline": data.optical_mass(leaf),
            "leaf": data.optical_mass(leaf, KERNEL, CAP),
            "all_stems": data.optical_mass(leafish | twig, KERNEL, CAP),
            "no_twigs": data.optical_mass(leafish, KERNEL, CAP),
            "twig_corrected": float(corrected.sum()),
            "share": {k: m.sum() / n for k, m in (("edge", edge), ("wide", wide), ("twig", twig))}}


def picture(path):
    """original | classes, cropped to the plant, with a legend and the class shares."""
    img = data.read_photo(path)
    leaf, edge, wide, twig = classes(path)
    vis = (img.astype(np.float32) * 0.55)
    for name, m in (("leaf", leaf), ("edge", edge), ("wide", wide), ("twig", twig)):
        a = 0.5 if name == "leaf" else 0.9
        vis[m] = img[m] * (1 - a) + np.array(COLOURS[name]) * a
    vis = vis.astype(np.uint8)
    ys, xs = np.nonzero(leaf | edge | wide | twig)
    h, w = leaf.shape
    y0, y1, x0, x1 = max(0, ys.min() - 30), min(h, ys.max() + 30), max(0, xs.min() - 30), min(w, xs.max() + 30)
    pair = np.hstack([img[y0:y1, x0:x1], np.full((y1 - y0, 8, 3), 255, np.uint8), vis[y0:y1, x0:x1]])
    n = max(int(leaf.sum()), 1)
    bar = np.full((58, pair.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, f"{path.stem}   original | classes", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1,
                cv2.LINE_AA)
    x = 8
    for name, label in (("leaf", "leaf"), ("edge", f"leaf edge +{edge.sum() / n * 100:.0f}%"),
                        ("wide", f"missed leaf +{wide.sum() / n * 100:.0f}%"),
                        ("twig", f"twig +{twig.sum() / n * 100:.0f}%")):
        cv2.rectangle(bar, (x, 34), (x + 16, 50), COLOURS[name], -1)
        cv2.putText(bar, label, (x + 22, 48), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        x += 32 + cv2.getTextSize(label, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0]
    return np.vstack([bar, pair])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--plants", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=data.JOBS)
    a = ap.parse_args()
    out = HERE / "results"

    photos = data.for_each_photo(a.photo_set, photo_job, a.plants, a.jobs)
    runs = [(data.BASELINE, {"mask": "leaf", "kernel": 64, "cap": 0.9}, data.plant_means(photos, lambda r: r["baseline"]))]
    masks = {"leaf": "leaf", "all_stems": "leaf+edge+wide+twig", "no_twigs": "leaf+edge+wide",
             "twig_corrected": "leaf+edge+wide, twig as wood"}
    runs += [(n, {"mask": masks[n], "kernel": KERNEL, "cap": CAP}, data.plant_means(photos, lambda r, n=n: r[n]))
             for n in RUNS]
    print(data.write_runs(out / "runs.csv", runs))

    shares = {k: data.plant_means(photos, lambda r, k=k: r["share"][k]) for k in ("edge", "wide", "twig")}
    with open(out / "classes.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plant", "edge_pct_of_leaf", "wide_pct_of_leaf", "twig_pct_of_leaf"])
        for p in shares["edge"]:
            w.writerow([p, *[round(shares[k][p] * 100, 1) for k in ("edge", "wide", "twig")]])
            print(f"{p:4s} edge {shares['edge'][p] * 100:4.1f}%  wide {shares['wide'][p] * 100:4.1f}%  "
                  f"twig {shares['twig'][p] * 100:4.1f}%")

    pics = out / "pictures"
    pics.mkdir(parents=True, exist_ok=True)
    for old in pics.glob("*.jpg"):
        old.unlink()
    rows = []
    for d in data.plant_dirs(a.photo_set, a.plants):
        p = data.plant_name(d)
        sides = dict(data.side_photos(d))
        for ang in [0] + EXTRA.get(p, []):
            path = sides.get(ang)
            if path is None:
                continue
            name = f"{path.stem}.jpg"
            cv2.imwrite(str(pics / name), picture(path), [cv2.IMWRITE_JPEG_QUALITY, 85])
            rows.append((name, f"{path.stem}: green = leaf (the leaf mask), yellow = leaf edge, orange = missed leaf "
                               "(both counted as leaf), red = twig (only blocks the view). The percentages are the "
                               "pixels of each class as a share of the leaf pixels.",
                         "" if p == "P8" else "The other plants"))
    rows.sort(key=lambda r: (r[2] != "", r[0]))
    with open(pics / "captions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "caption", "section"])
        w.writerows(rows)


if __name__ == "__main__":
    main()
