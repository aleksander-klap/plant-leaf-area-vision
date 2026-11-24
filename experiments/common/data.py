"""Photos, leaf masks, leaf areas and optical mass: what every experiment shares.

Every experiment works the same way:

    1. take the side photos of every plant that has a real leaf area (common/real_leaf_area_mm2.csv)
    2. compute one number per photo with the method under test   -> for_each_photo()
    3. average it over each plant's photos                       -> plant_means()
    4. write it as a run to results/runs.csv                     -> write_runs()
    5. test it with 00_evaluation/evaluate.py

The leaf mask is the one the regression uses, mask M1 at 1/4 resolution, from our own copy of the segmentation:
common/masks.py (copied from image_processing/masks.py). Segmenting a photo takes about a second, so the masks are
cached in experiments/cache/ and reused while neither the photo nor common/masks.py has changed.
"""
import csv
import os
import re
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

ROOT = Path(__file__).resolve().parents[1]                    # experiments/
sys.path.insert(0, str(ROOT))
from common import masks as seg  # noqa: E402  (our copy of the segmentation: common/masks.py)

LABELS = ROOT / "common" / "real_leaf_area_mm2.csv"
CACHE = ROOT / "cache" / "masks"
IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
SIDE_RE = re.compile(r"side_?(\d+)", re.IGNORECASE)
PLANT_RE = re.compile(r"P(\d+)", re.IGNORECASE)
BASELINE = "baseline"         # the run name of the current method in every runs.csv
JOBS = os.cpu_count() or 4


# ----------------------------------------------------------------------------------------------
# plants and photos
# ----------------------------------------------------------------------------------------------

def plant_name(s):
    """'P01', 'P01_side20.JPG', a folder ... -> 'P1'."""
    m = PLANT_RE.search(Path(str(s)).name)
    return f"P{int(m.group(1))}" if m else Path(str(s)).name


def plant_sort_key(name):
    m = PLANT_RE.search(name)
    return int(m.group(1)) if m else 10 ** 6


def labels():
    """Real leaf area per plant: {'P1': mm², ...}."""
    with open(LABELS, newline="") as fh:
        return {plant_name(r["plant"]): float(r["area_mm2"]) for r in csv.DictReader(fh)}


def side_photos(plant_dir):
    """The side photos of one plant folder, sorted by angle: [(angle, path)]. Top photos are skipped."""
    out = []
    for p in Path(plant_dir).iterdir():
        m = SIDE_RE.search(p.stem)
        if p.is_file() and p.suffix.lower() in IMG_EXT and m:
            out.append((int(m.group(1)), p))
    return sorted(out)


def plant_dirs(photo_set, plants=None):
    """The plant folders of the photo set that have a real leaf area (or only `plants`), sorted P1, P2, ..."""
    known = labels()
    want = {plant_name(p) for p in plants} if plants else set(known)
    dirs = [d for d in Path(photo_set).expanduser().iterdir()
            if d.is_dir() and plant_name(d) in want and plant_name(d) in known and side_photos(d)]
    if not dirs:
        raise SystemExit(f"no plant folders with side photos and a real leaf area in {photo_set}")
    return sorted(dirs, key=lambda d: plant_sort_key(plant_name(d)))


# ----------------------------------------------------------------------------------------------
# masks
# ----------------------------------------------------------------------------------------------

def read_photo(path):
    """The photo at 1/4 resolution (BGR), as the regression uses it."""
    img = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_4)
    if img is None:
        raise RuntimeError(f"cannot read {path}")
    return img


def _segmented(path):
    """The cached segmentation of one photo: (leaf, stem, pot width in px). Segments it if the photo or
    common/masks.py changed since it was cached."""
    path = Path(path)
    cp = CACHE / path.parent.name / (path.stem + ".npz")
    if cp.exists() and cp.stat().st_mtime >= max(path.stat().st_mtime, Path(seg.__file__).stat().st_mtime):
        z = np.load(cp)
        if "pot_width" in z:
            h, w = z["shape"]
            unpack = lambda a: np.unpackbits(a)[: h * w].reshape(h, w).astype(bool)  # noqa: E731
            return unpack(z["leaf"]), unpack(z["stem"]), float(z["pot_width"])
    s = seg.segment(read_photo(path))
    leaf, stem, pot_width = s["plant1"] > 0, s["stem"] > 0, float(s["pot"][3])
    cp.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cp, leaf=np.packbits(leaf), stem=np.packbits(stem), shape=np.array(leaf.shape),
                        pot_width=np.array(pot_width))
    return leaf, stem, pot_width


def masks(path):
    """(leaf, stem) of one photo, boolean, 1/4 resolution.

    leaf = mask M1 of common/masks.py (copied from image_processing/masks.py, the leaf mask of the regression)
    stem = what the segmentation sees as plant but not as leaf: stems, twigs, some brown leaf edges
    """
    leaf, stem, _ = _segmented(path)
    return leaf, stem


def pot_width(path):
    """Width of the pot in one photo, px at 1/4 resolution (nan if no pot was found)."""
    return _segmented(path)[2]


POT_REF_PX = 199.0      # median pot width over all photos (px at 1/4 resolution); the scale every plant is brought to


def pot_scale(photos):
    """{plant: (POT_REF_PX / median pot width over its photos)^2}: brings every plant's optical mass to the same scale.
    photos: the output of for_each_photo whose results hold "pot_width". The median per plant, because the width of
    a single photo jitters by 2-3% with the detection, while the real width hardly changes between photos."""
    widths = {}
    for plant, _, _, r in photos:
        if np.isfinite(r["pot_width"]):
            widths.setdefault(plant, []).append(r["pot_width"])
    return {p: (POT_REF_PX / float(np.median(w))) ** 2 for p, w in widths.items()}


# ----------------------------------------------------------------------------------------------
# optical mass
# ----------------------------------------------------------------------------------------------

def density(mask, window):
    """Leaf share f in the window x window square around every pixel."""
    return cv2.boxFilter(mask.astype(np.float32), -1, (window, window), normalize=True,
                         borderType=cv2.BORDER_CONSTANT)


def layers(f, cap):
    """Beer-Lambert: leaf layers from the leaf share, -ln(1 - min(f, cap))."""
    return -np.log1p(-np.minimum(f, cap))


def optical_mass(mask, window=64, cap=0.9):
    """Optical mass of one photo: the sum over all pixels of -ln(1 - min(f, cap)).
    window 64 and cap 0.9 on the leaf mask is the current method, T_64_0.9 of image_processing/features.py."""
    return float(layers(density(mask, window), cap).sum())


# ----------------------------------------------------------------------------------------------
# running over all photos
# ----------------------------------------------------------------------------------------------

def for_each_photo(photo_set, func, plants=None, jobs=JOBS):
    """Call func(path) for every side photo of every plant, in parallel.
    func must be a module-level function. Returns [(plant, angle, path, result)] in photo order."""
    todo = [(plant_name(d), a, p) for d in plant_dirs(photo_set, plants) for a, p in side_photos(d)]
    out = []
    with ProcessPoolExecutor(max_workers=jobs) as ex:
        for i, ((plant, a, p), r) in enumerate(zip(todo, ex.map(func, [p for _, _, p in todo]))):
            out.append((plant, a, p, r))
            print(f"\r{i + 1}/{len(todo)} photos", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    return out


def plant_means(photos, value=lambda r: r):
    """{plant: mean of value(result) over its photos}, from the output of for_each_photo."""
    vals = {}
    for plant, _, _, r in photos:
        vals.setdefault(plant, []).append(value(r))
    return {p: float(np.mean(v)) for p, v in vals.items()}


def write_runs(path, runs):
    """Write the runs of an experiment to one CSV, the input of 00_evaluation/evaluate.py.

    runs: [(run name, {setting: value}, {plant: optical mass})]. Every run should have the same settings keys;
    the baseline run (BASELINE) may have none. One row per run and plant:

        run, <settings...>, plant, optical_mass
    """
    keys = []
    for _, s, _ in runs:
        keys += [k for k in s if k not in keys]
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["run", *keys, "plant", "optical_mass"])
        for name, s, values in runs:
            for plant in sorted(values, key=plant_sort_key):
                w.writerow([name, *[s.get(k, "") for k in keys], plant, round(values[plant], 1)])
    return path
