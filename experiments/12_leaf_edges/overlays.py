"""Experiment 11: whole-plant overlays of the best run, to see what counts as leaf and what is left out.

    python 11_stem_weight/overlays.py PHOTO_SET [--photos P6_side00 P8_side00 ...] [--d 3]

The best run of experiment 11: masks at full resolution, stem pixels within d px (at 1/4 resolution; x4 at full) of
the leaf mask count as leaf (the leaves' own edges), the rest of the stem mask is left out (w = 0).

Per photo: the photo | what is counted: leaf (green), leaf edge from the stem mask (cyan), and left out: the rest of
the stem mask (orange, twigs and stems). Full resolution, cropped to the plant.

Output: results/overlays/*.jpg and results/overlays.md (one page with all of them).
"""
import argparse
import base64
import csv
import html
import sys
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data, html_to_md, masks as seg  # noqa: E402

PHOTOS = ["P6_side00", "P8_side00", "P10_side00", "P12_side00", "P13_side00", "P14_side00", "P15_side00"]
COL = dict(leaf=(60, 200, 60), edge=(230, 200, 0), stem=(0, 140, 255))
BEST_RUN = "full_d3_w0.00_k144"


def find_photo(photo_set, name):
    """Any plant folder, also one without a measured leaf area (P14)."""
    plant, side = name.split("_")
    d = [q for q in sorted(photo_set.iterdir()) if q.is_dir() and data.plant_name(q.name) == plant][0]
    return [q for _, q in data.side_photos(d) if q.stem.lower().endswith(side.lower())][0]


def errors():
    """{plant: error % of the best run and of the baseline}, plant left out, from the runs of experiment 11."""
    sys.path.insert(0, str(HERE.parent))
    from common import regression as rg
    runs = {}
    for r in csv.DictReader(open(HERE / "results" / "runs.csv", newline="")):
        runs.setdefault(r["run"], {})[r["plant"]] = float(r["optical_mass"])
    lab = data.labels()
    pl = [p for p in sorted(lab, key=data.plant_sort_key) if p in runs[BEST_RUN]]
    y = np.array([lab[p] for p in pl])
    out = {}
    for name in ("baseline", BEST_RUN):
        x = np.array([runs[name][p] for p in pl])
        pred = rg.loo("origin", x, y)[0]
        for p, e in zip(pl, (pred - y) / y * 100):
            out.setdefault(p, {})[name] = e
    return out


def overlay(path, d):
    img = cv2.imread(str(path))
    s = seg.segment(img, s=4)
    leaf, stem = s["plant1"] > 0, s["stem"] > 0
    edge = stem & (cv2.distanceTransform((~leaf).astype(np.uint8), cv2.DIST_L2, 5) <= 4 * d)
    out = (img * 0.35).astype(np.uint8)
    out[leaf] = COL["leaf"]
    out[edge] = COL["edge"]
    out[stem & ~edge] = COL["stem"]
    ys, xs = np.nonzero(leaf | stem)
    y0, y1 = max(0, ys.min() - 80), min(img.shape[0], ys.max() + 80)
    x0, x1 = max(0, xs.min() - 80), min(img.shape[1], xs.max() + 80)
    pad = np.full((y1 - y0, 24, 3), 255, np.uint8)
    row = np.hstack([img[y0:y1, x0:x1], pad, out[y0:y1, x0:x1]])
    sc = min(1.0, 3200 / row.shape[1])                     # keep enough detail to zoom in
    stats = dict(leaf=int(leaf.sum()), edge=int(edge.sum()), stem_out=int((stem & ~edge).sum()))
    return cv2.resize(row, None, fx=sc, fy=sc, interpolation=cv2.INTER_AREA), stats


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path)
    ap.add_argument("--photos", nargs="*", default=PHOTOS)
    ap.add_argument("--d", type=int, default=3, help="leaf-edge distance, px at 1/4 resolution")
    a = ap.parse_args()
    out = HERE / "results" / "overlays"
    out.mkdir(parents=True, exist_ok=True)
    err = errors()
    figs = []
    for name in a.photos:
        img, st = overlay(find_photo(a.photo_set, name), a.d)
        cv2.imwrite(str(out / f"{name}.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 88])
        plant = name.split("_")[0]
        counted = st["leaf"] + st["edge"]
        e = err.get(plant)
        etxt = (f"error with the best run {e[BEST_RUN]:+.1f}% (baseline {e['baseline']:+.1f}%)" if e
                else "no measured leaf area, so no error")
        b64 = base64.b64encode((out / f"{name}.jpg").read_bytes()).decode()
        figs.append(f"<h2>{html.escape(name.replace('_', ' '))}</h2><p class='small'>{etxt}. Counted: leaf "
                    f"{st['leaf']:,} px + leaf edge {st['edge']:,} px (+{st['edge'] / max(st['leaf'], 1) * 100:.0f}%); "
                    f"left out: {st['stem_out']:,} px of stem ({st['stem_out'] / max(counted, 1) * 100:.0f}% of what "
                    f"is counted). Full-resolution px.</p><a href='overlays/{name}.jpg'>"
                    f"<img src='data:image/jpeg;base64,{b64}' alt='{html.escape(name)}'></a>")
        print(name, st, etxt)
    sw = lambda k: (f"<span style='display:inline-block;width:12px;height:12px;background:rgb{tuple(reversed(COL[k]))};"  # noqa: E731
                    f"margin:0 4px 0 10px;vertical-align:-1px'></span>")
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Leaf edges overlays</title><style>
:root {{ --bg:#fff; --fg:#1f2937; --muted:#6b7280; --line:#e5e7eb; --card:#f9fafb; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111827; --fg:#e5e7eb; --muted:#9ca3af; --line:#374151; --card:#1f2937; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.55 system-ui, sans-serif; margin:0 auto; max-width:1600px;
       padding:24px 16px 60px; }}
h1 {{ font-size:26px; margin:0 0 4px; }} h2 {{ font-size:19px; margin:30px 0 4px; }}
img {{ max-width:100%; height:auto; border-radius:6px; border:1px solid var(--line); }}
.small {{ font-size:13px; color:var(--muted); }}
.box {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 16px; }}
</style></head><body>
<h1>What the best run of experiment 11 counts</h1>
<div class="box"><p>The best run (<code>{BEST_RUN}</code>, 2.93%, honest 2.99%): masks segmented at full resolution;
stem pixels within {a.d} px of a leaf (at 1/4 resolution, {4 * a.d} px at full) count as leaf, because they are the
leaves' own edges; the rest of the stem mask is left out. Kernel 144, cap 0.995.</p>
<p>Each picture: the photo | {sw('leaf')}<b>leaf</b> (counted) {sw('edge')}<b>leaf edge</b>, from the stem mask
(counted as leaf) {sw('stem')}<b>stem / twig</b>, the rest of the stem mask (left out). Click a picture for the full
size.</p>
<p class="small">P6 went well with the best run; the others are the problem plants (P14 has no measured leaf area).
One photo per plant (0°).</p></div>
{''.join(figs)}
</body></html>"""
    print(html_to_md.save(page, HERE / "results" / "overlays.md"))


if __name__ == "__main__":
    main()
