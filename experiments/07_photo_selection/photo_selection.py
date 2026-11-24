"""Experiment 06: one or two chosen photos per plant instead of the mean of all side photos.

    python 06_photo_selection/photo_selection.py PHOTO_SET [--plants P1 P12] [--jobs 16]
    python 00_evaluation/evaluate.py 06_photo_selection/results/runs.csv

Every side photo gets a clumping score from its density zones (common/zones.py, default settings):

    clumping = sqrt( sum_zones area x (f_zone - f_plant)^2 / sum_zones area )     f = leaf share

    low   most of the plant is one zone of one density: leaves evenly spread over the plant shape
    high  a dense clump next to airy parts

Per plant, the photo with the lowest score is "even" and the one with the highest is "clumped". The optical mass is
the baseline's (T_64_0.9) throughout; only the photos it is averaged over change:

    baseline   all side photos (the usual way)
    even       the most even photo only
    clumped    the most clumped photo only
    pair       the mean of those two

The yardstick: the same test with k randomly chosen photos per plant (k = 1, 2, 4, 9), 2000 draws each.

Output (results/):
    runs.csv            the four runs, for 00_evaluation
    random_photos.csv   typical error with k random photos: median and 5-95% range
    photo_scores.csv    every photo: clumping score, rank, optical mass
    pictures/           to check the choice by eye (00_evaluation shows them in the report):
        00_chosen.jpg   the most even and the most clumped photo of every plant
        P<n>.jpg        all photos of one plant with their zones, sorted from even to clumped, the two chosen marked
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data, regression, zones  # noqa: E402

RANDOM_K = [1, 2, 4, 9]
DRAWS = 2000
THUMB = 240                                  # px, height of a photo in the pictures
GREEN, RED, GREY = (40, 150, 40), (40, 40, 210), (90, 90, 90)


def clumping(zs):
    """Area-weighted spread of the leaf share between the zones. Lone specks (level 0) are left out."""
    zs = [z for z in zs if z["level"] > 0]
    A = np.array([z["pixels"] for z in zs], float)
    L = np.array([z["leaf"] for z in zs], float)
    if A.sum() == 0:
        return 0.0
    f, fp = L / A, L.sum() / A.sum()
    return float(np.sqrt((A * (f - fp) ** 2).sum() / A.sum()))


def photo_job(path):
    """Clumping score, baseline optical mass and a small picture of the zones of one photo."""
    leaf, _ = data.masks(path)
    zid, zs = zones.make_zones(leaf)
    pic = zones.zones_picture(data.read_photo(path), leaf, zid, zs)
    pic = cv2.resize(pic, (max(1, round(pic.shape[1] * THUMB / pic.shape[0])), THUMB), interpolation=cv2.INTER_AREA)
    return dict(score=clumping(zs), om=data.optical_mass(leaf), pic=pic)


def random_photos(photos, real):
    """Typical error of c x optical mass (leave-one-out) with k random photos per plant, DRAWS times."""
    plants = [p for p in sorted({p for p, *_ in photos}, key=data.plant_sort_key) if p in real]
    V = {p: np.array([r["om"] for q, _, _, r in photos if q == p]) for p in plants}
    y = np.array([real[p] for p in plants])
    rng = np.random.default_rng(0)
    out = []
    for k in RANDOM_K:
        X = np.array([[rng.choice(V[p], k, replace=False).mean() for p in plants] for _ in range(DRAWS)])
        err = regression.typical(y, regression.loo_origin(X, y))
        out.append((k, *np.percentile(err, [50, 5, 95])))
    return out


def tile(pic, label, colour=GREY, border=None):
    """A picture with a label above it, and a coloured frame for a chosen photo."""
    if border is not None:
        pic = cv2.copyMakeBorder(pic, 5, 5, 5, 5, cv2.BORDER_CONSTANT, value=border)
    bar = np.full((24, pic.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, label, (4, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.48, colour, 1, cv2.LINE_AA)
    return np.vstack([bar, pic])


def hstack(images, pad):
    h = max(i.shape[0] for i in images)
    return np.hstack([np.pad(i, ((0, h - i.shape[0]), (0, pad), (0, 0)), constant_values=255) for i in images])


def grid(images, ncols, pad):
    rows = [hstack(images[i:i + ncols], pad) for i in range(0, len(images), ncols)]
    w = max(r.shape[1] for r in rows)
    return np.vstack([np.pad(r, ((0, pad), (0, w - r.shape[1]), (0, 0)), constant_values=255) for r in rows])


def title(img, text):
    bar = np.full((34, img.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, text, (6, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def write_pictures(out, by_plant, even, clump):
    """results/pictures/: the chosen photos of all plants, one sheet per plant, and captions.csv for the report."""
    pics = out / "pictures"
    pics.mkdir(parents=True, exist_ok=True)
    pairs = []
    for p in by_plant:
        e, c = even[p][3], clump[p][3]
        pairs.append(hstack([tile(e["pic"], f"{p} most even  {e['score']:.3f}", GREEN, GREEN),
                             tile(c["pic"], f"{p} most clumped  {c['score']:.3f}", RED, RED)], 4))
    cv2.imwrite(str(pics / "00_chosen.jpg"), grid(pairs, 3, 16), [cv2.IMWRITE_JPEG_QUALITY, 82])
    rows = [("00_chosen.jpg", "The most even (green) and the most clumped (red) photo of every plant. The zones are "
             "coloured by their leaf layers (purple 0, yellow 2.3); the number is the clumping score. The most even "
             "photo is usually the wide side of the plant, where the shoots are spread out; the most clumped one is "
             "the narrow side, where they line up behind each other into a dense core.", "")]
    for p, v in by_plant.items():
        tiles = []
        for ph in sorted(v, key=lambda ph: ph[3]["score"]):
            r, ang = ph[3], ph[1]
            if ph[2] == even[p][2]:
                tiles.append(tile(r["pic"], f"{ang}deg  {r['score']:.3f}  MOST EVEN", GREEN, GREEN))
            elif ph[2] == clump[p][2]:
                tiles.append(tile(r["pic"], f"{ang}deg  {r['score']:.3f}  MOST CLUMPED", RED, RED))
            else:
                tiles.append(tile(r["pic"], f"{ang}deg  {r['score']:.3f}"))
        sheet = title(grid(tiles, 6, 6), f"{p}: all side photos, sorted from most even (top left) to most clumped "
                                         "(bottom right); number = clumping score")
        cv2.imwrite(str(pics / f"{p}.jpg"), sheet, [cv2.IMWRITE_JPEG_QUALITY, 80])
        rows.append((f"{p}.jpg", f"{p}: all {len(v)} side photos sorted from even to clumped.",
                     "All photos of every plant, sorted from even to clumped"))
    with open(pics / "captions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "caption", "section"])
        w.writerows(rows)
    print(pics)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--plants", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=data.JOBS)
    a = ap.parse_args()
    out = HERE / "results"
    out.mkdir(parents=True, exist_ok=True)

    photos = data.for_each_photo(a.photo_set, photo_job, a.plants, a.jobs)
    by_plant = {}
    for ph in photos:
        by_plant.setdefault(ph[0], []).append(ph)
    even = {p: min(v, key=lambda ph: ph[3]["score"]) for p, v in by_plant.items()}
    clump = {p: max(v, key=lambda ph: ph[3]["score"]) for p, v in by_plant.items()}

    runs = [(data.BASELINE, {"photos": "all"}, data.plant_means(photos, lambda r: r["om"])),
            ("even", {"photos": "most even"}, {p: ph[3]["om"] for p, ph in even.items()}),
            ("clumped", {"photos": "most clumped"}, {p: ph[3]["om"] for p, ph in clump.items()}),
            ("pair", {"photos": "even + clumped"},
             {p: (even[p][3]["om"] + clump[p][3]["om"]) / 2 for p in by_plant})]
    print(data.write_runs(out / "runs.csv", runs))

    with open(out / "photo_scores.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plant", "photo", "angle", "clumping", "rank_even_first", "chosen", "optical_mass"])
        for p, v in by_plant.items():
            for rank, (_, ang, path, r) in enumerate(sorted(v, key=lambda ph: ph[3]["score"]), 1):
                tag = "even" if path == even[p][2] else "clumped" if path == clump[p][2] else ""
                w.writerow([p, path.name, ang, round(r["score"], 4), rank, tag, round(r["om"], 1)])

    with open(out / "random_photos.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["photos", "typical_error_median_pct", "p5_pct", "p95_pct"])
        for k, med, lo, hi in random_photos(photos, data.labels()):
            w.writerow([k, round(med, 2), round(lo, 2), round(hi, 2)])
            print(f"{k} random photos: typical error {med:.1f}% (5-95%: {lo:.1f} - {hi:.1f}%)")

    write_pictures(out, by_plant, even, clump)

if __name__ == "__main__":
    main()
