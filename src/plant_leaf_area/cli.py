"""Optical mass of every side photo, its mean per plant, and how well it predicts the measured leaf area.

    plant-leaf-area PHOTOS... [--labels data/real_leaf_area_mm2.csv] [--out output] [--kernel 144] [--cap 0.995]
                              [--full-res] [--overlays] [--jobs N]

PHOTOS: photo files, plant folders (P01/ with P01_side00.JPG ...) or a photo set (a folder of plant folders).
Top photos are skipped. The evaluation (leave-one-out of leaf area = c x optical mass, see evaluation.py) runs on
the plants that have a measured leaf area in --labels; it is skipped if the file doesn't exist.

Output (in --out):
    per_photo.csv     plant, angle, photo, optical mass, plant px, pot width
    per_plant.csv     plant, number of photos, mean optical mass, its standard deviation
    settings.json     the settings of the run
    report.md         all of it on one page
    evaluation.csv    per plant: measured and predicted leaf area (plant left out), error %
    evaluation.json   the scores, c learned on all plants, the shuffle test
    overlays/<photo>/ one picture per step (with --overlays)
    overlays/index.html  a page to browse them: plant -> angle -> step (with --overlays)
"""
import argparse
import csv
import json
import os
import sys
import time
from concurrent.futures import ProcessPoolExecutor
from dataclasses import asdict
from pathlib import Path

import numpy as np

from . import evaluation, overlays, report, viewer
from .config import Settings
from .optical_mass import optical_mass
from .photos import find_photos, read_photo
from .segmentation import segment


def process(path, settings, overlay_dir=None):
    """One photo -> {optical_mass, plant_px, pot_width}; the step pictures go to overlay_dir if given."""
    img = read_photo(path, settings.scale)
    seg = segment(img, settings.scale)
    om = optical_mass(seg.plant, settings.kernel, settings.cap, settings.scale)
    if overlay_dir is not None:
        overlays.save(overlay_dir, img, seg, om, settings)
    return dict(optical_mass=om.value, plant_px=int(seg.plant.sum()), pot_width=seg.pot.width)


def _job(args):
    return process(*args)


def main(argv=None):
    ap = argparse.ArgumentParser(prog="plant-leaf-area", description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    d = Settings()
    ap.add_argument("photos", nargs="+", type=Path)
    ap.add_argument("--labels", type=Path, default=Path("data/real_leaf_area_mm2.csv"),
                    help="measured leaf area per plant, columns plant, area_mm2 (default data/real_leaf_area_mm2.csv)")
    ap.add_argument("--out", type=Path, default=Path("output"))
    ap.add_argument("--kernel", type=int, default=d.kernel, help=f"density window, px at 1/4 res (default {d.kernel})")
    ap.add_argument("--cap", type=float, default=d.cap, help=f"density cap (default {d.cap})")
    ap.add_argument("--full-res", action="store_true", help="segment at full resolution (~16x slower, ~2 GB/job)")
    ap.add_argument("--overlays", action="store_true", help="save one picture per step for every photo")
    ap.add_argument("--jobs", type=int, default=os.cpu_count() or 4)
    a = ap.parse_args(argv)
    settings = Settings(kernel=a.kernel, cap=a.cap, scale=4 if a.full_res else 1)

    todo = find_photos(a.photos)
    if not todo:
        raise SystemExit("no side photos found")
    a.out.mkdir(parents=True, exist_ok=True)
    jobs = [(p, settings, a.out / "overlays" / p.stem if a.overlays else None) for _, _, p in todo]
    t0 = time.time()
    results = []
    with ProcessPoolExecutor(max_workers=max(1, min(a.jobs, len(jobs)))) as ex:
        for i, r in enumerate(ex.map(_job, jobs)):
            results.append(r)
            print(f"\r{i + 1}/{len(jobs)} photos  {time.time() - t0:.0f} s", end="", file=sys.stderr, flush=True)
    seconds = time.time() - t0
    print(file=sys.stderr)

    with open(a.out / "per_photo.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plant", "angle", "photo", "optical_mass", "plant_px", "pot_width"])
        for (plant, angle, p), r in zip(todo, results):
            w.writerow([plant, angle, p.name, round(r["optical_mass"], 1), r["plant_px"], round(r["pot_width"], 1)])
    per_plant = {}
    for (plant, _, _), r in zip(todo, results):
        per_plant.setdefault(plant, []).append(r["optical_mass"])
    with open(a.out / "per_plant.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plant", "photos", "optical_mass", "optical_mass_sd"])
        for plant, v in per_plant.items():
            w.writerow([plant, len(v), round(float(np.mean(v)), 1), round(float(np.std(v, ddof=1)) if len(v) > 1
                                                                        else 0.0, 1)])
    (a.out / "settings.json").write_text(json.dumps(asdict(settings), indent=2) + "\n")
    if a.overlays:
        page = viewer.write(a.out / "overlays", [(plant, angle, p.stem, r["optical_mass"], r["plant_px"], r["pot_width"])
                                                 for (plant, angle, p), r in zip(todo, results)], settings)
    print(f"{len(todo)} photos of {len(per_plant)} plants -> {a.out}/\n")

    r = None
    if not a.labels.exists():
        print(f"no evaluation: {a.labels} not found (set it with --labels)")
    else:
        try:
            r = evaluation.evaluate({p: float(np.mean(v)) for p, v in per_plant.items()},
                                    evaluation.read_column(a.labels, "area_mm2"))
        except ValueError as e:
            r = None
            print(f"no evaluation: {e}")
        else:
            evaluation.save(r, a.out, settings, a.labels)
            print(evaluation.report(r))
    report.write(a.out / "report.md", settings, len(todo), per_plant, r, a.labels, seconds)
    print(f"\nreport: {a.out / 'report.md'}")
    if a.overlays:
        print(f"overlays: open {page}")


if __name__ == "__main__":
    main()
