"""Experiment 01: check the leaf mask by eye on every photo.

    python 01_mask_check/mask_check.py PHOTO_SET [--plants P08 P03] [--jobs 16]

With winter coming, some leaves turn red or brown. Is every leaf in the mask, and is nothing else in it? This runs
the leaf mask of the regression (common/masks.py, mask M1, 1/4 resolution) on every photo of every plant
folder (side and top) and saves original | overlay:

    green    counted as leaf, green
    orange   counted as leaf, not green (red / brown leaves, accepted by the M1 rules)
    yellow   plant, but NOT counted as leaf: stems, and non-green parts the rules did not accept as leaf
             (a red or brown leaf painted yellow is a missed leaf)
    red      green-ish pixels the M1 rules removed again (wall noise, or a dropped leaf)
    blue     the area not searched for leaves (pot, soil, objects in the room)

Output (results/):
    pixels.csv             per photo: leaf pixels (green, not green), not-leaf plant pixels, removed pixels
    examples/              a few full-size pictures for the README (EXAMPLES)
    <plant>/sheet.jpg      all overlays of one plant on one page
    index.html             every photo as a thumbnail, click for the full picture (with <plant>/*.jpg, not in git)
"""
import argparse
import csv
import html
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common.data import IMG_EXT, JOBS, seg  # noqa: E402

RESULTS = HERE / "results"
# copied to results/examples/ for the README: the most uncounted plant, missed dark leaves, a clean mask
EXAMPLES = ["P08_side220", "P03_side20", "P11_side00"]
COLOURS = [  # name, BGR, opacity
    ("leaf, green", (0, 210, 0), 0.50),
    ("leaf, not green (red/brown)", (0, 140, 255), 0.75),
    ("plant, not counted as leaf (stem / rejected)", (0, 255, 255), 0.80),
    ("removed by the rules", (0, 0, 255), 0.85),
]


def classes(img, s):
    """Boolean masks in the order of COLOURS, and the not-searched area."""
    leaf = s["plant1"] > 0
    green = seg.green_mask(img) > 0
    return [leaf & green, leaf & ~green, s["stem"] > 0, (s["plant0"] > 0) & ~(s["m1"] > 0)], s["zone"] == 0


def paint(img, cls, outside):
    vis = img.copy()
    vis[outside] = (0.7 * vis[outside] + 0.3 * np.array([255, 120, 0])).astype(np.uint8)
    for m, (_, c, a) in zip(cls, COLOURS):
        vis[m] = ((1 - a) * vis[m] + a * np.array(c)).astype(np.uint8)
    return vis


def legend(width):
    bar = np.full((34, width, 3), 255, np.uint8)
    x = 10
    items = COLOURS + [("not searched (pot, objects)", (255, 120, 0), 0.3)]
    for name, c, _ in items:
        cv2.rectangle(bar, (x, 9), (x + 18, 25), c, -1)
        cv2.putText(bar, name, (x + 24, 23), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        x += 24 + cv2.getTextSize(name, cv2.FONT_HERSHEY_SIMPLEX, 0.5, 1)[0][0] + 26
    return bar


def crop_box(cls, outside, shape, pad=60):
    m = np.zeros(shape, bool)
    for c in cls[:3]:
        m |= c
    ys, xs = np.nonzero(m)
    if len(ys) == 0:
        return 0, shape[0], 0, shape[1]
    return (max(0, ys.min() - pad), min(shape[0], ys.max() + pad), max(0, xs.min() - pad),
            min(shape[1], xs.max() + pad))


def job(args):
    path, out_dir = args
    img = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_4)
    if img is None:
        return dict(photo=path.name, error="cannot read")
    s = seg.segment(img)
    cls, outside = classes(img, s)
    vis = paint(img, cls, outside)
    y0, y1, x0, x1 = crop_box(cls, outside, img.shape[:2])
    pair = np.hstack([img[y0:y1, x0:x1], np.full((y1 - y0, 8, 3), 255, np.uint8), vis[y0:y1, x0:x1]])
    title = np.full((30, pair.shape[1], 3), 255, np.uint8)
    cv2.putText(title, f"{path.name}   original | mask", (8, 21), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1,
                cv2.LINE_AA)
    full = np.vstack([title, pair, legend(pair.shape[1])])
    cv2.imwrite(str(out_dir / f"{path.stem}.jpg"), full, [cv2.IMWRITE_JPEG_QUALITY, 90])
    th = vis[y0:y1, x0:x1]
    h = 300
    th = cv2.resize(th, (max(1, round(th.shape[1] * h / th.shape[0])), h), interpolation=cv2.INTER_AREA)
    cv2.imwrite(str(out_dir / "thumbs" / f"{path.stem}.jpg"), th, [cv2.IMWRITE_JPEG_QUALITY, 82])
    n = [int(c.sum()) for c in cls]
    return dict(photo=path.name, leaf_green=n[0], leaf_not_green=n[1], not_leaf=n[2], removed=n[3],
                leaf=n[0] + n[1], not_green_share=round(n[1] / max(n[0] + n[1], 1), 4), error="")


def sheet(out_dir, names, ncols=6, pad=6):
    tiles = []
    for nm in names:
        t = cv2.imread(str(out_dir / "thumbs" / f"{Path(nm).stem}.jpg"))
        if t is None:
            continue
        bar = np.full((24, t.shape[1], 3), 255, np.uint8)
        cv2.putText(bar, Path(nm).stem, (5, 17), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (0, 0, 0), 1, cv2.LINE_AA)
        tiles.append(np.vstack([bar, t]))
    if not tiles:
        return
    rows = []
    for i in range(0, len(tiles), ncols):
        r = tiles[i:i + ncols]
        h = max(t.shape[0] for t in r)
        rows.append(np.hstack([np.pad(t, ((0, h - t.shape[0]), (0, pad), (0, 0)), constant_values=255) for t in r]))
    w = max(r.shape[1] for r in rows)
    img = np.vstack([np.pad(r, ((0, pad), (0, w - r.shape[1]), (0, 0)), constant_values=255) for r in rows])
    img = np.vstack([img, legend(img.shape[1])])
    cv2.imwrite(str(out_dir / "sheet.jpg"), img, [cv2.IMWRITE_JPEG_QUALITY, 85])


def write_index(out, plants, rows):
    e = html.escape
    leg = "".join(f"<span class='k'><i style='background:rgb{c[::-1]}'></i>{e(n)}</span>" for n, c, _ in COLOURS)
    leg += "<span class='k'><i style='background:rgb(0,120,255)'></i>not searched (pot, objects)</span>"
    secs = []
    for p, photos in plants:
        cards = []
        for ph in photos:
            r = rows.get((p, ph.name), {})
            share = r.get("not_green_share")
            tip = (f"leaf {r.get('leaf', 0):,} px, not green {100 * share:.1f}%" if share is not None
                   else r.get("error", ""))
            cards.append(f"<a href='{e(p)}/{e(ph.stem)}.jpg' target='_blank'><img loading='lazy' "
                         f"src='{e(p)}/thumbs/{e(ph.stem)}.jpg' alt='{e(ph.name)}'><span>{e(ph.stem)}"
                         f"<br><small>{e(tip)}</small></span></a>")
        secs.append(f"<h2 id='{e(p)}'>{e(p)} <small><a href='{e(p)}/sheet.jpg' target='_blank'>sheet</a>"
                    f"</small></h2><div class='g'>{''.join(cards)}</div>")
    nav = " · ".join(f"<a href='#{e(p)}'>{e(p)}</a>" for p, _ in plants)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Leaf mask check</title><style>
:root {{ --bg:#fff; --fg:#1f2937; --muted:#6b7280; --card:#f3f4f6; --line:#e5e7eb; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111827; --fg:#e5e7eb; --muted:#9ca3af; --card:#1f2937;
  --line:#374151; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.5 system-ui, sans-serif; margin:0 auto; max-width:1400px;
  padding:20px 16px 60px; }}
a {{ color:inherit; }} h2 {{ margin:28px 0 8px; border-bottom:1px solid var(--line); }}
.k {{ display:inline-flex; align-items:center; gap:6px; margin:0 16px 6px 0; font-size:14px; }}
.k i {{ width:16px; height:16px; border-radius:3px; display:inline-block; }}
.g {{ display:grid; grid-template-columns:repeat(auto-fill, minmax(200px, 1fr)); gap:10px; }}
.g a {{ background:var(--card); border-radius:8px; overflow:hidden; text-decoration:none; display:block; }}
.g img {{ width:100%; height:190px; object-fit:contain; background:#444; display:block; }}
.g span {{ display:block; padding:4px 8px 6px; font-size:13px; }} small {{ color:var(--muted); }}
.nav {{ position:sticky; top:0; background:var(--bg); padding:8px 0; border-bottom:1px solid var(--line); }}
</style></head><body><h1>Leaf mask check</h1>
<p>{leg}</p><p class="muted"><small>Click a photo for original | mask at full size. A red or brown leaf painted
<b>yellow</b> is a leaf the mask missed; one painted <b>orange</b> is counted.</small></p>
<div class="nav">{nav}</div>{''.join(secs)}</body></html>"""
    (out / "index.html").write_text(page, encoding="utf-8")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("parent", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--plants", nargs="*", default=None, help="only these plant folders (e.g. P10 P12)")
    ap.add_argument("--jobs", type=int, default=JOBS)
    a = ap.parse_args()

    out = RESULTS
    plants = []
    for d in sorted((p for p in a.parent.expanduser().iterdir() if p.is_dir()), key=lambda p: p.name):
        photos = sorted(p for p in d.iterdir() if p.is_file() and p.suffix.lower() in IMG_EXT)
        if not photos or not any("side" in p.stem.lower() for p in photos):
            continue                       # not a plant folder (e.g. picked_leaves)
        if a.plants and d.name not in a.plants:
            continue
        plants.append((d.name, photos))
    jobs = []
    for p, photos in plants:
        (out / p / "thumbs").mkdir(parents=True, exist_ok=True)
        jobs += [(ph, out / p) for ph in photos]
    print(f"{len(plants)} plants, {len(jobs)} photos -> {out}")

    rows = {}
    with ProcessPoolExecutor(max_workers=a.jobs) as ex:
        for i, ((ph, od), r) in enumerate(zip(jobs, ex.map(job, jobs))):
            rows[(od.name, ph.name)] = r
            print(f"\r{i + 1}/{len(jobs)}", end="", file=sys.stderr, flush=True)
    print(file=sys.stderr)
    for p, photos in plants:
        sheet(out / p, [ph.name for ph in photos])
    with open(out / "pixels.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["plant", "photo", "view", "leaf_px", "leaf_green_px", "leaf_not_green_px", "not_green_share",
                    "not_leaf_plant_px", "removed_px", "error"])
        for p, photos in plants:
            for ph in photos:
                r = rows[(p, ph.name)]
                w.writerow([p, ph.name, "top" if "top" in ph.stem.lower() else "side", r.get("leaf", ""),
                            r.get("leaf_green", ""), r.get("leaf_not_green", ""), r.get("not_green_share", ""),
                            r.get("not_leaf", ""), r.get("removed", ""), r.get("error", "")])
    write_index(out, plants, rows)
    ex = out / "examples"
    ex.mkdir(exist_ok=True)
    for name in EXAMPLES:
        src = out / name.split("_")[0] / f"{name}.jpg"
        if src.exists():
            (ex / src.name).write_bytes(src.read_bytes())
    print(out / "index.html")


if __name__ == "__main__":
    main()
