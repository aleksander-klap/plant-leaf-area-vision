"""Experiment 05: optical mass by density zones instead of per pixel.

    python 05_density_zones/density_zones.py PHOTO_SET [--quick] [--plants P1 P12] [--jobs 16]
    python 00_evaluation/evaluate.py 05_density_zones/results/runs.csv

The baseline gives every pixel its own number of leaf layers, from the leaf share in the 64 px window around it.
Here each photo is cut into a few zones of similar density (common/zones.py), and every pixel of a zone gets the
zone's layers:

    per zone:   layers = -ln(1 - min(f_zone, cap)),   value = zone pixels x layers
    per photo:  optical mass = sum of the zone values
    per plant:  mean over its side photos

Every combination of GRID is one run (1080 runs, about 40 min on 16 cores). --quick runs only the default settings.
The zones are drawn once per (window, levels, min_zone, edge); the cap only changes the layers of each zone.
--pictures-only skips the runs and only makes the pictures (a few seconds).

To look at the zones of one plant with your own settings, use the window: gui.py.

Output (results/):
    runs.csv        every run, plus the baseline, for 00_evaluation
    settings.csv    what every setting means and the values of the sweep, shown in the report
    method.html     the method in a few lines, shown in the report
    pictures/       per-pixel method vs zones on one photo of a few plants (00_evaluation shows them in the report)
"""
import argparse
import csv
import itertools
import sys
from functools import partial
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data, zones  # noqa: E402

GRID = dict(window=[32, 48, 64, 96, 128, 192], levels=[1, 2, 3, 4, 5], min_zone=[2000, 4000, 8000],
            edge=[0.02, 0.05, 0.10], cap=[0.85, 0.90, 0.95, 0.98])
DEFAULT = dict(window=64, levels=3, min_zone=4000, edge=0.05, cap=0.90)
GOOD = dict(window=64, levels=2, min_zone=8000, edge=0.02, cap=0.85)       # the best run of the sweep (current leaf areas)
SHAPE_KEYS = ["window", "levels", "min_zone", "edge"]
# what every setting means, written to results/settings.csv for the report (letter = its part of the run name)
SETTING_DOC = {
    "window": "w: side of the square window, in px at 1/4 photo resolution (a leaf is ~35 px across), in which the "
              "leaf share around every pixel is measured. This density map only draws the zones: a small window "
              "follows single leaves, a large one draws smooth rings around the dense core.",
    "levels": "l: how many density groups (airy ... dense) the plant is split into, by k-means on the density of its "
              "leaf pixels. 1 = one density for the whole plant.",
    "min_zone": "m: smallest zone, in px (a leaf is ~1000 px). Smaller pieces are merged into the zone around them, "
                "so the zones don't fall apart into specks.",
    "edge": "e: lowest density that still counts as plant. Where the density map is at least this, the pixels belong "
            "to the plant area (leaves plus the gaps between them); below it is background. A lower edge makes the "
            "outer zones reach further out, with more gaps, so their leaf share is lower.",
    "cap": "c: highest leaf share f a zone may have when it is turned into layers, layers = -ln(1 - min(f, cap)). "
           "It limits how many layers a nearly solid zone counts: 0.85 = 1.9, 0.90 = 2.3, 0.95 = 3.0, 0.98 = 3.9 "
           "layers. The only setting that doesn't change the zones themselves.",
}
PICTURE_PLANTS = ["P10", "P5", "P12"]       # an open, a medium and the densest plant


def run_name(s):
    return f"w{s['window']}_l{s['levels']}_m{s['min_zone']}_e{s['edge']:.2f}_c{s['cap']:.2f}"


def settings_list(quick):
    grid = {k: [v] for k, v in DEFAULT.items()} if quick else GRID
    return [dict(zip(grid, v)) for v in itertools.product(*grid.values())]


def photo_job(settings, path):
    """{run name: optical mass of this photo} for every setting, and the baseline."""
    leaf, _ = data.masks(path)
    out = {data.BASELINE: data.optical_mass(leaf)}
    shapes = {}
    for s in settings:
        key = tuple(s[k] for k in SHAPE_KEYS)
        if key not in shapes:
            shapes[key] = zones.make_zones(leaf, zones.Params(*key))[1]
        out[run_name(s)] = zones.optical_mass_zones(shapes[key], s["cap"])
    return out


def label(img, text, sub=""):
    """A white title strip above a picture."""
    bar = np.full((52, img.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(bar, sub, (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 90, 90), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def comparison(path):
    """One photo four ways, same crop: photo | per pixel (baseline) | zones, default | zones, best run."""
    img = data.read_photo(path)
    leaf, _ = data.masks(path)
    zd = zones.make_zones(leaf, zones.Params(*(DEFAULT[k] for k in SHAPE_KEYS)))
    zg = zones.make_zones(leaf, zones.Params(*(GOOD[k] for k in SHAPE_KEYS)))
    box = zones.crop_box(leaf, zd[0] | zg[0])
    y0, y1, x0, x1 = box
    panels = [
        label(img[y0:y1, x0:x1].copy(), f"{data.plant_name(path)} {path.stem.split('_')[-1]}",
              f"leaf pixels {int(leaf.sum()):,}"),
        label(zones.pixel_picture(img, leaf, box=box), "per pixel (baseline)",
              f"optical mass {data.optical_mass(leaf):,.0f}"),
        label(zones.zones_picture(img, leaf, *zd, DEFAULT["cap"], box=box), "zones, default settings",
              f"{len(zd[1])} zones, optical mass {zones.optical_mass_zones(zd[1], DEFAULT['cap']):,.0f}"),
        label(zones.zones_picture(img, leaf, *zg, GOOD["cap"], box=box), "zones, best run of the sweep",
              f"{len(zg[1])} zones, optical mass {zones.optical_mass_zones(zg[1], GOOD['cap']):,.0f}"),
    ]
    pad = np.full((panels[0].shape[0], 8, 3), 255, np.uint8)
    row = np.hstack([x for p in panels for x in (p, pad)][:-1])
    leg = np.full((34, row.shape[1], 3), 255, np.uint8)
    bar = zones.legend(300, 14)
    leg[10:24, 140:440] = bar
    cv2.putText(leg, "leaf layers  0", (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.45, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(leg, f"{zones.LAYER_MAX:g}   (leaf share 0.9 = 2.30 layers)", (448, 22), cv2.FONT_HERSHEY_SIMPLEX,
                0.45, (0, 0, 0), 1, cv2.LINE_AA)
    return np.vstack([row, leg])


def write_pictures(photo_set, plants):
    """results/pictures/: the comparison for one photo of each plant, and captions.csv for the report."""
    pics = HERE / "results" / "pictures"
    pics.mkdir(parents=True, exist_ok=True)
    good = run_name(GOOD)
    captions = {
        "P10": "P10, an open plant. Per pixel, only small clusters of overlapping leaves reach many layers (yellow); "
               "the open shoots stay low. The default zones turn this into nested bands (airy edge, medium, core). "
               "The best run has only 2 levels: an airy edge and one core. Its optical mass (164,068) is almost the "
               "same as per pixel (163,793).",
        "P5": "P5, a medium plant. The default zones find the same dense patches as the per-pixel method and make them "
              "whole zones at the cap (yellow), so the zones count more than per pixel (222,698 against 205,620). "
              "The best run's 2 levels and 0.85 cap give one core with fewer layers: no zone reaches the cap and the "
              "optical mass (199,352) is a little below per pixel.",
        "P12": "P12, the densest plant. Per pixel and with the default zones the core reaches the cap (yellow): a "
               "single photo cannot show how deep it goes, so P12 is predicted too low by every method. The best "
               "run's single core stays below the cap and ends up close to per pixel (191,260 against 193,443), so "
               "it doesn't fix that either.",
    }
    rows = []
    for d in data.plant_dirs(photo_set, plants):
        _, path = data.side_photos(d)[0]
        name = f"{data.plant_name(d)}_{path.stem.split('_')[-1]}.jpg"
        cv2.imwrite(str(pics / name), comparison(path), [cv2.IMWRITE_JPEG_QUALITY, 85])
        rows.append((name, captions.get(data.plant_name(d), data.plant_name(d))))
    with open(pics / "captions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "caption"])
        w.writerows(rows)
    print(pics)


METHOD_HTML = """
<p><b>Question:</b> is the optical mass better if the leaf layers are measured per zone of similar density instead
of per pixel?</p>
<p>A bush has regions: an airy edge, a medium part, a dense core. The baseline gives every pixel its own number of
leaf layers, from the leaf share in the 64 px window around it. Here those regions are found first, each one's
density is measured on the mask itself, and all its pixels get the region's layers.</p>
<p><b>How each photo is cut into zones:</b></p>
<ol>
<li><b>Density map:</b> the leaf share in a <i>window</i> around every pixel. It is used only to draw the zones.</li>
<li><b>Plant area:</b> where that density is at least <i>edge</i>, plus every leaf pixel. It includes the gaps
between the leaves, so a zone can have a leaf share below 1.</li>
<li><b>Levels:</b> the densities of the leaf pixels are grouped into <i>levels</i> groups, from airy to dense.
Pieces smaller than <i>min zone</i> are merged into the zone around them.</li>
<li><b>Zones:</b> every connected piece of one level is a zone.</li>
</ol>
<p><b>Then, per zone:</b> f = leaf pixels / zone pixels, layers = −ln(1 − min(f, <i>cap</i>)), and the zone counts
zone pixels × layers. The optical mass of a photo is the sum over its zones; of a plant, the mean over its side
photos. An airy zone counts about as its leaf pixels; only dense zones are scaled up.</p>
<p class="small muted">Sizes are in px at 1/4 of the photo resolution, where a leaf is about 35 px across and about
1000 px in area. A run's name lists its settings: <code>w192_l4_m2000_e0.02_c0.85</code> is window 192, levels 4,
min zone 2000, edge 0.02, cap 0.85.</p>
"""


def write_setting_doc(path):
    """results/settings.csv: what every setting means and the values of the sweep, and results/method.html: the
    method in a few lines. Both are shown in the report."""
    path.with_name("method.html").write_text(METHOD_HTML.strip() + "\n", encoding="utf-8")
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "meaning", "values"])
        for k, doc in SETTING_DOC.items():
            w.writerow([k, doc, ", ".join(f"{v:g}" for v in GRID[k]) + f" (default {DEFAULT[k]:g})"])
    return path


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--quick", action="store_true", help="only the default settings")
    ap.add_argument("--pictures-only", action="store_true", help="only make the pictures, no runs")
    ap.add_argument("--plants", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=data.JOBS)
    a = ap.parse_args()
    if a.pictures_only:
        write_pictures(a.photo_set, a.plants or PICTURE_PLANTS)
        return
    settings = settings_list(a.quick)
    print(f"{len(settings)} runs + baseline")

    photos = data.for_each_photo(a.photo_set, partial(photo_job, settings), a.plants, a.jobs)
    runs = [(data.BASELINE, {}, data.plant_means(photos, lambda r: r[data.BASELINE]))]
    runs += [(run_name(s), s, data.plant_means(photos, lambda r, n=run_name(s): r[n])) for s in settings]
    print(data.write_runs(HERE / "results" / "runs.csv", runs))
    print(write_setting_doc(HERE / "results" / "settings.csv"))

    write_pictures(a.photo_set, a.plants or PICTURE_PLANTS)

if __name__ == "__main__":
    main()
