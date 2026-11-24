"""Experiment 11: leaf edges by distance, a weight for the stems, and the masks at full resolution.

    python 11_stem_weight/stem_weight.py PHOTO_SET [--plants P2 P12] [--jobs 3] [--pictures-only]
    python 00_evaluation/evaluate.py 11_stem_weight/results/runs.csv

The stem mask of the segmentation is "in front of the wall, near the plant, but not leaf": real twigs, but also leaf
edges (reddish, brown), leaves seen edge-on and shaded leaf. Three simple ways to treat it better:

1. Leaf edges by distance: stem pixels within d px of the leaf mask are the leaf's own edges and count as leaf.
   Twigs touch leaves only where a leaf grows off them, so most of a twig stays further away.
2. A weight for the rest: the remaining stem pixels count with a weight w (0 = left out, as the baseline;
   1 = counted fully, as experiment 02-04). The best average treatment of twigs, edge-on leaves and shaded leaf.
3. Full resolution: the masks segmented at full resolution (common/masks.py with s=4), where a twig is 12-24 px wide
   instead of 3-6, then reduced to 1/4 resolution as fractions, so the optical mass uses the same windows.

Each photo:  mask = leaf + edge_d + w x (stem - edge_d),   at 1/4 or from full resolution
             optical mass = sum of -ln(1 - min(f, cap)), f = the mask's share in the kernel window
On the pot-fixed masks (experiment 09), for the baseline's settings (kernel 64, cap 0.90) and those of the best run of
experiment 04 (kernel 144, cap 0.995). d in px at 1/4 resolution (x4 at full resolution).

Output (results/):
    runs.csv        one run per resolution, d, w and model, plus the baseline (1/4, d 0, w 0, kernel 64, cap 0.90)
    settings.csv    what the settings mean, shown in the report
    method.html     the method in a few lines, shown in the report
    pictures/       leaf, leaf edges and stems at 1/4 and full resolution, on a few photos
The full-resolution parts of every photo are cached in cache/masks_full/ (segmenting at full resolution takes ~16 s
per photo and ~2 GB of memory; use few --jobs).
"""
import argparse
import csv
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data, masks as seg  # noqa: E402

DS = [0, 1, 2, 3, 4]                     # leaf-edge distance, px at 1/4 resolution
WS = [0.0, 0.25, 0.5, 0.75, 1.0]         # weight of the remaining stem pixels
MODELS = {"k64": (64, 0.90), "k144": (144, 0.995)}
RES = {"quarter": 1, "full": 4}
FULL_CACHE = data.ROOT / "cache" / "masks_full"
PICTURE_PHOTOS = ["P10_side00", "P8_side00", "P12_side00"]
PICTURE_D = 2

METHOD_HTML = """
<p><b>Question:</b> how should the stem mask be counted? The segmentation's "stem" mask is everything in front of the
wall, near the plant, that isn't leaf: real twigs, but also reddish and brown leaf edges, leaves seen edge-on and
shaded leaf. Leaving it out (the baseline) loses the leaf parts; counting it fully (experiments 02–04) counts the twigs
as leaf, which overshoots on P8.</p>
<ol>
<li><b>Leaf edges by distance (d):</b> stem pixels within d px of the leaf mask are the leaf's own edges and count as
leaf. Twigs touch leaves only where a leaf grows off them, so most of a twig stays further away.</li>
<li><b>A weight for the rest (w):</b> the remaining stem pixels count with a weight w, from 0 (left out, as the
baseline) to 1 (counted fully, as in 02–04): the best average treatment of twigs, edge-on leaves and shaded leaf.</li>
<li><b>Full resolution (res):</b> the masks segmented at full resolution, where a twig is 12–24 px wide instead of
3–6 px and leaf edges are sharper, then reduced to 1/4 resolution as fractions, so the optical mass uses the same
windows. Every size in the segmentation is scaled ×4 (areas ×16).</li>
</ol>
<p>Per photo: <code>mask = leaf + edge_d + w × (stem − edge_d)</code>, then the optical mass as always. Both on the
baseline's settings (kernel 64, cap 0.90) and on those of the best run of 04 (kernel 144, cap 0.995). All on the
pot-fixed masks of experiment 09.</p>
<p class="small muted">A run's name is its resolution, d, w and model: <code>full_d2_w0.50_k144</code> is full
resolution, leaf edges within 2 px, the remaining stems at weight 0.5, kernel 144 with cap 0.995. d is in px at 1/4
resolution (×4 at full). The baseline is <code>quarter_d0_w0.00_k64</code>: leaf only, kernel 64, cap 0.90, on the
pot-fixed masks.</p>
"""


def parts_quarter(path):
    """leaf, stem and edge_d (stem within d px of the leaf) at 1/4 resolution, as float masks."""
    leaf, stem = data.masks(path)
    dist = cv2.distanceTransform((~leaf).astype(np.uint8), cv2.DIST_L2, 5)
    edges = {d: (stem & (dist <= d)).astype(np.float32) for d in DS if d > 0}
    return leaf.astype(np.float32), stem.astype(np.float32), edges


def parts_full(path):
    """The same from the full-resolution masks, reduced to 1/4 resolution as fractions (cached)."""
    cp = FULL_CACHE / path.parent.name / (path.stem + ".npz")
    newest = max(path.stat().st_mtime, Path(seg.__file__).stat().st_mtime)
    if cp.exists() and cp.stat().st_mtime >= newest:
        z = np.load(cp)
        return (z["leaf"] / 16.0, z["stem"] / 16.0, {d: z[f"edge{d}"] / 16.0 for d in DS if d > 0})
    img = cv2.imread(str(path))
    s = seg.segment(img, s=4)
    leaf, stem = s["plant1"] > 0, s["stem"] > 0
    dist = cv2.distanceTransform((~leaf).astype(np.uint8), cv2.DIST_L2, 5)
    h, w = leaf.shape[0] // 4, leaf.shape[1] // 4

    def counts(m):           # number of full-resolution pixels of m in every 4 x 4 block: 0..16
        return m[: 4 * h, : 4 * w].reshape(h, 4, w, 4).sum(axis=(1, 3)).astype(np.uint8)
    arrays = {"leaf": counts(leaf), "stem": counts(stem)}
    arrays |= {f"edge{d}": counts(stem & (dist <= 4 * d)) for d in DS if d > 0}
    cp.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(cp, **arrays)
    return arrays["leaf"] / 16.0, arrays["stem"] / 16.0, {d: arrays[f"edge{d}"] / 16.0 for d in DS if d > 0}


def run_name(res, d, w, model):
    return f"{res}_d{d}_w{w:.2f}_{model}"


def photo_job(path):
    """Optical mass of every run for one photo."""
    out = {}
    for res in RES:
        leaf, stem, edges = parts_quarter(path) if res == "quarter" else parts_full(path)
        if leaf.shape != data.masks(path)[0].shape:       # full-resolution parts must line up with the 1/4 photo
            raise RuntimeError(f"{path}: full-resolution parts {leaf.shape} don't match the 1/4 photo")
        for model, (k, cap) in MODELS.items():
            # the window density is linear in the mask: combine the densities of the parts
            dl, dst = data.density(leaf, k), data.density(stem, k)
            de = {0: np.zeros_like(dl)} | {d: data.density(e, k) for d, e in edges.items()}
            for d in DS:
                for w in WS:
                    f = dl + de[d] + w * (dst - de[d])
                    out[run_name(res, d, w, model)] = float(data.layers(f, cap).sum())
    return out


# ----------------------------------------------------------------------------------------------
# pictures
# ----------------------------------------------------------------------------------------------

def label(img, text, sub=""):
    bar = np.full((52, img.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(bar, sub, (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 90, 90), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def classes(img, leaf, stem, edge):
    """leaf green, leaf edge (stem near the leaf, counted as leaf) cyan, remaining stem (weighted) orange."""
    out = (img * 0.35).astype(np.uint8)
    out[leaf] = (60, 200, 60)
    out[stem & ~edge] = (0, 140, 255)
    out[edge] = (230, 200, 0)
    return out


def picture(path):
    """photo | 1/4 resolution | full resolution, with the leaf edges at d = PICTURE_D. Crop around the plant, shown at
    full resolution so the difference is visible."""
    full = cv2.imread(str(path))
    sf = seg.segment(full, s=4)
    lf, sf_ = sf["plant1"] > 0, sf["stem"] > 0
    ef = sf_ & (cv2.distanceTransform((~lf).astype(np.uint8), cv2.DIST_L2, 5) <= 4 * PICTURE_D)
    lq, sq = data.masks(path)
    eq = sq & (cv2.distanceTransform((~lq).astype(np.uint8), cv2.DIST_L2, 5) <= PICTURE_D)
    up = lambda m: cv2.resize(m.astype(np.uint8), (full.shape[1], full.shape[0]), interpolation=cv2.INTER_NEAREST) > 0  # noqa: E731
    # a crop of the middle of the plant, where leaves, edges and twigs mix, at full resolution
    ys, xs = np.nonzero(lf | sf_)
    cy, cx = int(np.median(ys)), int(np.median(xs))
    y0, x0 = max(0, cy - 450), max(0, cx - 600)
    c = lambda a: a[y0:y0 + 900, x0:x0 + 1200].copy()  # noqa: E731
    n = lambda a, b: f"stem {int(a.sum()):,} px, of which leaf edge {int(b.sum()):,} ({b.sum() / max(a.sum(), 1) * 100:.0f}%)"
    panels = [label(c(full), f"{path.stem}, middle of the plant", "full resolution"),
              label(c(classes(full, up(lq), up(sq), up(eq))), f"masks at 1/4 resolution, d = {PICTURE_D}",
                    n(sq, eq) + " (1/4 px)"),
              label(c(classes(full, lf, sf_, ef)), f"masks at full resolution, d = {4 * PICTURE_D} px",
                    n(sf_, ef) + " (full px)")]
    pad = np.full((panels[0].shape[0], 8, 3), 255, np.uint8)
    row = np.hstack([panels[0], pad, panels[1], pad, panels[2]])
    return cv2.resize(row, None, fx=0.6, fy=0.6, interpolation=cv2.INTER_AREA)


def find_photo(photo_set, name):
    plant, side = name.split("_")
    d = data.plant_dirs(photo_set, [plant])[0]
    return [q for _, q in data.side_photos(d) if q.stem.lower().endswith(side.lower())][0]


def write_pictures(photo_set, out):
    pics = out / "pictures"
    pics.mkdir(parents=True, exist_ok=True)
    rows = []
    captions = {
        "P10_side00": "P10, whose leaf edges are often reddish or brown.",
        "P8_side00": "P8, the plant with the most red twigs.",
        "P12_side00": "P12, a dense plant.",
    }
    for name in PICTURE_PHOTOS:
        cv2.imwrite(str(pics / f"{name}.jpg"), picture(find_photo(photo_set, name)), [cv2.IMWRITE_JPEG_QUALITY, 85])
        rows.append((f"{name}.jpg", captions.get(name, name) + " Green: leaf. Cyan: stem pixels within d of a leaf, "
                     "counted as leaf (its edges). Orange: the remaining stem pixels, counted with weight w."))
    with open(pics / "captions.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["file", "caption"])
        w.writerows(rows)


def write_report_notes(folder):
    (folder / "method.html").write_text(METHOD_HTML.strip() + "\n", encoding="utf-8")
    with open(folder / "settings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "meaning", "values"])
        w.writerow(["res", "resolution of the segmentation: quarter (as always) or full (x4, reduced to 1/4 as "
                    "fractions)", "quarter, full"])
        w.writerow(["d", "stem pixels within d px of the leaf mask count as leaf (its edges); px at 1/4 resolution",
                    ", ".join(map(str, DS))])
        w.writerow(["w", "weight of the remaining stem pixels: 0 = left out (baseline), 1 = counted fully (02-04)",
                    ", ".join(f"{x:g}" for x in WS)])
        w.writerow(["model", "k64: kernel 64, cap 0.90 (the baseline's). k144: kernel 144, cap 0.995 (best run of 04)",
                    "k64, k144"])


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--plants", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=3, help="parallel photos; full resolution needs ~2 GB each")
    ap.add_argument("--pictures-only", action="store_true")
    a = ap.parse_args()
    out = HERE / "results"
    out.mkdir(exist_ok=True)
    write_report_notes(out)
    if not a.pictures_only:
        photos = data.for_each_photo(a.photo_set, photo_job, a.plants, a.jobs)
        base = run_name("quarter", 0, 0.0, "k64")
        runs = [(data.BASELINE, {}, data.plant_means(photos, lambda r: r[base]))]
        for res in RES:
            for d in DS:
                for w in WS:
                    for model in MODELS:
                        n = run_name(res, d, w, model)
                        runs.append((n, {"res": res, "d": d, "w": w, "model": model},
                                     data.plant_means(photos, lambda r, n=n: r[n])))
        print(data.write_runs(out / "runs.csv", runs))
    write_pictures(a.photo_set, out)


if __name__ == "__main__":
    main()
