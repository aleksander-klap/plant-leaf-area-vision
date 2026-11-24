"""Experiment 10: find the twigs by tracing them from the pot. Overlays only, no runs.

    python 10_twig_tracing/twig_tracing.py PHOTO_SET [--photos P8_side00 P12_side120 ...]

The stem mask of common/masks.py is "in front of the wall, near the plant, but not leaf": it mixes real twigs with
leaf edges, leaves seen edge-on and shaded leaf parts. Here the twigs are found by their shape and their place:

1. Candidates: the stem mask, plus the thin parts of the leaf mask (green shoots and petioles are in the leaf mask,
   but much narrower than a leaf).
2. Their centrelines (skeletonize), cut into pieces at the junctions and at sharp bends: a twig bends smoothly.
3. Each piece: length, width, straightness (end-to-end distance / length).
4. Seeds: pieces that come out of the soil, just above the pot's rim, around its axis.
5. Growing out from the seeds, a piece becomes a twig if it is straight enough and not too wide, and
   - meets a twig at a junction (a branch may leave at any angle), or
   - lies in the line of a twig's end across a short gap (twigs pass behind leaves).
   Long, straight, thin pieces (longer than a leaf) are seeds too: their base may be hidden behind leaves.
6. Everything else in the stem mask is probably leaf; thin leaf-mask parts that aren't reached stay leaf.

Output (results/):
    pictures/*.jpg  per photo: the photo | the classes | the traced centrelines
    stats.csv       per photo: stem pixels, twig pixels (from the stem and from the leaf mask), stem taken as leaf
    report.md       everything on one page (pictures in report_files/)
"""
import argparse
import base64
import csv
import html
import sys
from pathlib import Path

import cv2
import numpy as np
from scipy import ndimage
from skimage.morphology import skeletonize

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data, html_to_md, masks as seg  # noqa: E402

PHOTOS = ["P8_side00", "P8_side120", "P10_side00", "P10_side120", "P3_side00", "P3_side120",
          "P12_side00", "P12_side120", "P15_side00", "P15_side120"]

# --- tunables (px at 1/4 resolution: a leaf is ~35 px across, the pot ~199 px wide) -------------------------------
THIN = 11           # leaf-mask parts narrower than this are candidates (green shoots, petioles); a leaf is wider
STEP = 6            # px between the points used to measure directions along a centreline
BEND = 45.0         # a turn sharper than this (degrees) cuts a centreline into two pieces: twigs bend smoothly
MIN_STRAIGHT = 0.75  # end-to-end distance / length of a piece; an arc around a leaf (half circle) is 0.64
JUDGE_LEN = 15      # pieces shorter than this are too short to judge their straightness
MAX_WIDTH = 18      # mean width of a twig piece
SPUR = 6            # centreline side branches shorter than this are pruned (ragged mask edges)
SEED_H = 0.15       # seeds: pieces reaching into this x pot width above the rim ...
SEED_X = 0.5        # ... within this x pot width of the pot's axis ...
SEED_WIDTH = 30     # ... the trunk may be wider than a twig ...
SEED_LEN = 10       # ... at least this long ...
SEED_UP = 50.0      # ... and rising: within this angle of vertical (not lying along the rim)
RIM_STRIP = 10      # pieces lying flat (over 60 degrees from vertical) within this many px above the rim are the soil
                    # or the back of the rim, not twigs
LONG_SEED = 50      # a straight, thin piece at least this long is a twig by itself (longer than any leaf: a leaf is
                    # ~35 px across), even where its base is hidden behind leaves
LONG_STRAIGHT = 0.9  # ... straight enough for that
GAP = 45            # a twig continues across a gap up to this long (behind a leaf, ~35 px across) ...
GAP_FROM = 12       # ... from a twig piece at least this long (a shorter one has no reliable direction) ...
GAP_TO = 8          # ... to a piece at least this long ...
CONE = 20.0         # ... that lies within this angle of the twig's direction ...
CONT = 30.0         # ... and runs on in the same direction (angle between the two directions) ...
GAP_IN = 0.6        # ... and the gap runs through the plant (this share of it in the leaf or stem mask)
LONE_LEN = 40       # rejected pieces at least this long and straight are drawn as "straight, not connected"


# ----------------------------------------------------------------------------------------------
# centrelines
# ----------------------------------------------------------------------------------------------

NB = [(-1, -1), (-1, 0), (-1, 1), (0, -1), (0, 1), (1, -1), (1, 0), (1, 1)]


def prune(sk, n=SPUR):
    """Remove side branches shorter than n px: take n px off every free end, then grow the ends that are left back
    along the original centreline (spurs hang off junctions, so they don't grow back)."""
    k = np.ones((3, 3), np.float32)
    cur = sk.copy()
    for _ in range(n):
        nb = cv2.filter2D(cur.astype(np.uint8), -1, k, borderType=cv2.BORDER_CONSTANT) - 1
        cur &= ~(cur & (nb <= 1))
    for _ in range(n):
        nb = cv2.filter2D(cur.astype(np.uint8), -1, k, borderType=cv2.BORDER_CONSTANT) - 1
        ends = cur & (nb == 1)
        cur |= cv2.dilate(ends.astype(np.uint8), k.astype(np.uint8)).astype(bool) & sk
    return cur


def order_path(pix):
    """The pixels of one centreline piece, in order from one end to the other."""
    s = set(map(tuple, pix))
    def nbs(p):
        return [(p[0] + dy, p[1] + dx) for dy, dx in NB if (p[0] + dy, p[1] + dx) in s]
    ends = [p for p in s if len(nbs(p)) <= 1]
    start = ends[0] if ends else next(iter(s))
    path, seen, cur = [start], {start}, start
    while True:
        nxt = [q for q in nbs(cur) if q not in seen]
        if not nxt:
            break
        cur = min(nxt, key=lambda q: abs(q[0] - cur[0]) + abs(q[1] - cur[1]))   # 4-neighbours first
        path.append(cur)
        seen.add(cur)
    return np.array(path, float)


def turns(path):
    """Turning angle (degrees) at every point of an ordered path, measured over STEP px on either side."""
    n = len(path)
    out = np.zeros(n)
    for i in range(STEP, n - STEP):
        d1, d2 = path[i] - path[i - STEP], path[i + STEP] - path[i]
        cos = d1 @ d2 / max(np.linalg.norm(d1) * np.linalg.norm(d2), 1e-9)
        out[i] = np.degrees(np.arccos(np.clip(cos, -1, 1)))
    return out


def split_at_bends(path):
    """Cut a path where it turns sharper than BEND: a twig bends smoothly."""
    t = turns(path)
    i = int(np.argmax(t)) if len(t) else 0
    if len(t) and t[i] > BEND:
        return split_at_bends(path[: i + 1]) + split_at_bends(path[i:])
    return [path]


def length(path):
    return float(np.linalg.norm(np.diff(path, axis=0), axis=1).sum()) if len(path) > 1 else 1.0


def end_dir(path, end):
    """Unit direction pointing out of the path at one end (0 or 1)."""
    k = min(len(path) - 1, 2 * STEP)
    if k == 0:
        return np.zeros(2)
    d = path[0] - path[k] if end == 0 else path[-1] - path[-1 - k]
    return d / max(np.linalg.norm(d), 1e-9)


def angle(u, v):
    return float(np.degrees(np.arccos(np.clip(u @ v / max(np.linalg.norm(u) * np.linalg.norm(v), 1e-9), -1, 1))))


# ----------------------------------------------------------------------------------------------
# tracing
# ----------------------------------------------------------------------------------------------

def trace(leaf, stem, pot):
    """Returns dict(cand, twig, pieces, accepted, seeds, bridges, lone): the twig mask and what the tracing saw."""
    h, w = leaf.shape
    thin_leaf = leaf & ~(cv2.morphologyEx(leaf.astype(np.uint8), cv2.MORPH_OPEN, seg.ell(THIN)) > 0)
    cand = stem | thin_leaf
    sk = prune(skeletonize(cand))
    nbc = cv2.filter2D(sk.astype(np.uint8), -1, np.ones((3, 3), np.float32), borderType=cv2.BORDER_CONSTANT) - 1
    junction = sk & (nbc >= 3)
    nj, jlab = cv2.connectedComponents(junction.astype(np.uint8), connectivity=8)
    jgrow = ndimage.grey_dilation(jlab, size=(3, 3))               # junction id next to a piece's end
    ns, slab = cv2.connectedComponents((sk & ~junction).astype(np.uint8), connectivity=8)
    width_map = 2 * cv2.distanceTransform(cand.astype(np.uint8), cv2.DIST_L2, 5)

    pieces = []
    objs = ndimage.find_objects(slab)
    for i, sl in enumerate(objs, start=1):
        if sl is None:
            continue
        ys, xs = np.nonzero(slab[sl] == i)
        pix = np.stack([ys + sl[0].start, xs + sl[1].start], 1)
        path = order_path(pix)
        parts = split_at_bends(path) if len(path) > 2 * STEP + 1 else [path]
        for k, part in enumerate(parts):
            ends = []
            for e, pt in ((0, part[0]), (1, part[-1])):
                node = int(jgrow[int(pt[0]), int(pt[1])])
                # inner ends made by a bend cut are not junctions: the parts don't connect there
                if (e == 0 and k > 0) or (e == 1 and k < len(parts) - 1):
                    node = 0
                ends.append(dict(pt=pt, dir=end_dir(part, e), node=node))
            L = length(part)
            chord = float(np.linalg.norm(part[-1] - part[0]))
            pieces.append(dict(path=part, length=L, straight=chord / L if L > 0 else 1.0,
                               width=float(np.mean(width_map[part[:, 0].astype(int), part[:, 1].astype(int)])),
                               ends=ends))

    ax, rim, _, pw = pot

    def on_rim(p):
        """Lying flat along the rim: the soil or the back of the rim."""
        if not np.isfinite(rim):
            return False
        d = p["path"][-1] - p["path"][0]
        return (np.mean(p["path"][:, 0]) >= rim - RIM_STRIP and abs(np.mean(p["path"][:, 1]) - ax) <= 0.62 * pw
                and angle(np.abs(d), np.array([1.0, 0.0])) > 60)

    def why_not(p, wmax=MAX_WIDTH):
        """Why a piece can't be a twig ('' if it can)."""
        if on_rim(p):
            return "on the rim"
        if p["width"] > wmax:
            return "wide"
        if p["length"] >= JUDGE_LEN and p["straight"] < MIN_STRAIGHT:
            return "bent"
        return ""

    def shape_ok(p, wmax=MAX_WIDTH):
        return not why_not(p, wmax)

    at_node = {}
    for i, p in enumerate(pieces):
        for e in p["ends"]:
            if e["node"]:
                at_node.setdefault(e["node"], []).append(i)

    # seeds: pieces coming out of the soil, just above the rim, around the pot's axis
    seeds = []
    if np.isfinite(rim):
        y0, y1 = rim - SEED_H * pw, rim + 2
        for i, p in enumerate(pieces):
            ys, xs = p["path"][:, 0], p["path"][:, 1]
            d = p["path"][-1] - p["path"][0]
            rising = angle(np.abs(d), np.array([1.0, 0.0])) <= SEED_UP        # (dy, dx): within SEED_UP of vertical
            if (np.any((ys >= y0) & (ys <= y1) & (np.abs(xs - ax) <= SEED_X * pw)) and p["length"] >= SEED_LEN
                    and rising and shape_ok(p, SEED_WIDTH)):
                seeds.append(i)

    long_seeds = [i for i, p in enumerate(pieces) if i not in seeds and p["length"] >= LONG_SEED
                  and p["straight"] >= LONG_STRAIGHT and p["width"] <= MAX_WIDTH]

    # free ends of the pieces long enough to bridge to, for bridging gaps
    end_ref = [(i, j) for i, p in enumerate(pieces) if p["length"] >= GAP_TO for j in range(2)]
    end_pts = np.array([pieces[i]["ends"][j]["pt"] for i, j in end_ref]) if end_ref else np.zeros((0, 2))
    plant = leaf | stem

    def through_plant(a, b):
        n = int(max(abs(b - a))) + 1
        ys, xs = np.linspace(a[0], b[0], n).astype(int), np.linspace(a[1], b[1], n).astype(int)
        return plant[ys, xs].mean() >= GAP_IN

    accepted, bridges = set(seeds) | set(long_seeds), []
    queue = list(accepted)
    while queue:
        a = queue.pop()
        for e in pieces[a]["ends"]:
            # a junction: every piece meeting there may be a branch, at any angle
            for b in at_node.get(e["node"], []) if e["node"] else []:
                if b not in accepted and shape_ok(pieces[b]):
                    accepted.add(b)
                    queue.append(b)
            # a gap: the next piece lies in the line of this end, and runs on in the same direction
            if not len(end_pts) or pieces[a]["length"] < GAP_FROM:
                continue
            d = end_pts - e["pt"]
            dist = np.linalg.norm(d, axis=1)
            for k in np.nonzero((dist > 1.5) & (dist <= GAP))[0]:
                b, j = end_ref[k]
                if b == a or b in accepted or not shape_ok(pieces[b]):
                    continue
                f = pieces[b]["ends"][j]
                if (angle(e["dir"], d[k]) <= CONE and angle(e["dir"], -f["dir"]) <= CONT
                        and through_plant(e["pt"], f["pt"])):
                    accepted.add(b)
                    queue.append(b)
                    bridges.append((e["pt"], f["pt"]))

    lone = [i for i, p in enumerate(pieces) if i not in accepted and p["length"] >= LONE_LEN
            and p["straight"] >= 0.85 and p["width"] <= MAX_WIDTH]

    # every candidate pixel belongs to the nearest centreline piece
    pid = np.zeros((h, w), np.int32)
    for i, p in enumerate(pieces, start=1):
        pid[p["path"][:, 0].astype(int), p["path"][:, 1].astype(int)] = i
    _, (iy, ix) = ndimage.distance_transform_edt(pid == 0, return_indices=True)
    nearest = pid[iy, ix]
    acc = np.zeros(len(pieces) + 1, bool)
    acc[[i + 1 for i in accepted]] = True
    twig = cand & acc[nearest]
    reason = {i: (why_not(p) or "not connected") for i, p in enumerate(pieces) if i not in accepted}
    return dict(cand=cand, twig=twig, pieces=pieces, accepted=accepted, seeds=seeds, long_seeds=long_seeds,
                bridges=bridges, lone=lone, reason=reason)


# ----------------------------------------------------------------------------------------------
# pictures and report
# ----------------------------------------------------------------------------------------------

COL = dict(leaf=(60, 200, 60), twig_stem=(40, 40, 230), twig_green=(230, 140, 30), stem_leaf=(0, 220, 255))
REASON_COL = {"wide": (0, 140, 255), "bent": (200, 120, 255), "not connected": (150, 150, 150),
              "on the rim": (0, 90, 160)}   # rejected centrelines
LEGEND = [("leaf", "leaf"), ("twig (in the stem mask)", "twig_stem"), ("twig (green shoot, in the leaf mask)", "twig_green"),
          ("stem mask, probably leaf", "stem_leaf")]


def label(img, text, sub=""):
    bar = np.full((52, img.shape[1], 3), 255, np.uint8)
    cv2.putText(bar, text, (8, 22), cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 1, cv2.LINE_AA)
    cv2.putText(bar, sub, (8, 44), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (90, 90, 90), 1, cv2.LINE_AA)
    return np.vstack([bar, img])


def pictures(img, leaf, stem, pot, t, name):
    """photo | classes | centrelines, same crop."""
    twig = t["twig"]
    cls = (img * 0.35).astype(np.uint8)
    cls[leaf & ~twig] = COL["leaf"]
    cls[stem & ~twig] = COL["stem_leaf"]
    cls[twig & stem] = COL["twig_stem"]
    cls[twig & leaf & ~stem] = COL["twig_green"]
    lines = (img * 0.15).astype(np.uint8)
    lines[leaf] = (35, 60, 35)
    lines[stem] = (30, 55, 80)
    for i, p in enumerate(t["pieces"]):
        pts = p["path"][:, ::-1].astype(np.int32).reshape(-1, 1, 2)
        col = ((255, 255, 255) if i in t["accepted"] else (255, 0, 255) if i in t["lone"]
               else REASON_COL[t["reason"][i]])
        cv2.polylines(lines, [pts], False, col, 2 if i in t["accepted"] else 1)
    for a, b in t["bridges"]:
        cv2.line(lines, (int(a[1]), int(a[0])), (int(b[1]), int(b[0])), (255, 255, 0), 2)
    for i in t["long_seeds"]:
        y, x = t["pieces"][i]["path"][len(t["pieces"][i]["path"]) // 2]
        cv2.circle(lines, (int(x), int(y)), 6, (0, 255, 255), 2)
    for i in t["seeds"]:
        y, x = t["pieces"][i]["path"][-1] if t["pieces"][i]["path"][-1][0] > t["pieces"][i]["path"][0][0] \
            else t["pieces"][i]["path"][0]
        cv2.circle(lines, (int(x), int(y)), 6, (0, 0, 255), 2)
    ax, rim, _, pw = pot
    if np.isfinite(rim):
        cv2.line(lines, (int(ax - pw), int(rim)), (int(ax + pw), int(rim)), (0, 200, 255), 1)
    ys, xs = np.nonzero(leaf | stem)
    y0, y1 = max(0, ys.min() - 20), min(img.shape[0], int(max(ys.max(), rim if np.isfinite(rim) else 0)) + 30)
    x0, x1 = max(0, xs.min() - 20), min(img.shape[1], xs.max() + 20)
    c = lambda a: a[y0:y1, x0:x1].copy()  # noqa: E731
    n_stem, n_twig = int(stem.sum()), int((twig & stem).sum())
    panels = [label(c(img), name.replace("_", " "), ""),
              label(c(cls), "classes", f"stem px {n_stem:,}: twig {n_twig:,} ({n_twig / max(n_stem, 1) * 100:.0f}%), "
                                       f"probably leaf {n_stem - n_twig:,}; green twig {int((twig & leaf & ~stem).sum()):,}"),
              label(c(lines), "centrelines", f"twig (white) {len(t['accepted'])} of {len(t['pieces'])} pieces, "
                                             f"seeds: {len(t['seeds'])} at the pot (red), {len(t['long_seeds'])} long (yellow); "
                                             f"{len(t['bridges'])} gaps bridged (cyan)")]
    pad = np.full((panels[0].shape[0], 8, 3), 255, np.uint8)
    row = np.hstack([panels[0], pad, panels[1], pad, panels[2]])
    s = min(1.0, 2400 / row.shape[1])
    return cv2.resize(row, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)


def find_photo(photo_set, name):
    plant, side = name.split("_")
    d = data.plant_dirs(photo_set, [plant])[0]
    return [q for _, q in data.side_photos(d) if q.stem.lower().endswith(side.lower())][0]


def report(rows, out):
    legend = " ".join(f"<span style='display:inline-block;width:12px;height:12px;background:rgb"
                      f"{tuple(reversed(COL[k]))};margin:0 4px 0 12px;vertical-align:-1px'></span>{html.escape(t)}"
                      for t, k in LEGEND)
    figs = []
    for r in rows:
        b64 = base64.b64encode((out / "pictures" / r["file"]).read_bytes()).decode()
        figs.append(f"<h3>{html.escape(r['photo'].replace('_', ' '))}</h3><img src='data:image/jpeg;base64,{b64}' "
                    f"alt='{html.escape(r['photo'])}'><p class='small muted'>stem mask {r['stem_px']:,} px: twig "
                    f"{r['twig_from_stem_px']:,} ({r['twig_share_of_stem_pct']}%), probably leaf "
                    f"{r['stem_as_leaf_px']:,}. Green twig (from the leaf mask): {r['twig_from_leaf_px']:,} px.</p>")
    table = "".join(f"<tr><td>{html.escape(r['photo'])}</td><td>{r['stem_px']:,}</td><td>{r['twig_from_stem_px']:,}</td>"
                    f"<td>{r['twig_share_of_stem_pct']}%</td><td>{r['stem_as_leaf_px']:,}</td>"
                    f"<td>{r['twig_from_leaf_px']:,}</td><td>{r['seeds']}</td></tr>" for r in rows)
    page = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><title>Twig tracing</title><style>
:root {{ --bg:#fff; --fg:#1f2937; --muted:#6b7280; --line:#e5e7eb; --card:#f9fafb; }}
@media (prefers-color-scheme: dark) {{ :root {{ --bg:#111827; --fg:#e5e7eb; --muted:#9ca3af; --line:#374151; --card:#1f2937; }} }}
body {{ background:var(--bg); color:var(--fg); font:15px/1.55 system-ui, sans-serif; margin:0 auto; max-width:1400px;
       padding:24px 16px 60px; }}
h1 {{ font-size:26px; margin:0 0 4px; }} h2 {{ font-size:20px; margin:32px 0 8px; border-bottom:1px solid var(--line); }}
img {{ max-width:100%; height:auto; border-radius:6px; border:1px solid var(--line); }}
.muted {{ color:var(--muted); }} .small {{ font-size:13px; }}
table {{ border-collapse:collapse; font-size:14px; }} th, td {{ border-bottom:1px solid var(--line); padding:4px 10px; text-align:right; }}
th:first-child, td:first-child {{ text-align:left; }}
.box {{ background:var(--card); border:1px solid var(--line); border-radius:10px; padding:10px 16px; }}
</style></head><body>
<h1>Twig tracing</h1>
<p class="muted">Experiment 10: overlays only, to check the method by eye. Nothing is scored.</p>
<div class="box">
<p><b>The idea.</b> Twigs grow in fairly straight lines without sudden turns, and they grow out of the pot or out of
other twigs. The stem mask is everything in front of the wall that isn't leaf; it mixes twigs with leaf edges, leaves
seen edge-on and shaded leaf. Here a piece of the stem mask, or a thin part of the leaf mask (a green shoot), is a twig
only if its centreline can be followed, smoothly, back to the pot.</p>
<ol>
<li><b>Candidates:</b> the stem mask plus the parts of the leaf mask narrower than {THIN} px (a leaf is ~35 px across).</li>
<li><b>Centrelines</b> (skeletonize; side spurs under {SPUR} px pruned), cut into pieces at junctions and where they
turn sharper than {BEND:g}°.</li>
<li><b>Not the rim:</b> pieces lying flat within {RIM_STRIP} px above the pot's rim are the soil or the back of the
rim, never twigs.</li>
<li><b>Seeds:</b> pieces just above the pot's rim (within {SEED_H:g} × the pot width), around its axis, at least
{SEED_LEN} px long and rising (within {SEED_UP:g}° of vertical, not lying along the rim).</li>
<li><b>Long straight seeds:</b> a thin piece at least {LONG_SEED} px long with a straightness of at least
{LONG_STRAIGHT:g} is a twig by itself: longer than any leaf (~35 px across). It starts tracing where a twig's base is
hidden behind leaves.</li>
<li><b>Growing out from the seeds,</b> a piece becomes a twig if it is straight (end-to-end distance / length ≥
{MIN_STRAIGHT:g}, or shorter than {JUDGE_LEN} px), at most {MAX_WIDTH} px wide on average, and either meets a twig at a
junction (a branch may leave at any angle) or lies in the line of a twig's end across a gap of up to {GAP} px (within
{CONE:g}°, running on within {CONT:g}°, the gap at least {GAP_IN:.0%} inside the plant): twigs pass behind leaves.
Only twig pieces of at least {GAP_FROM} px bridge gaps, to pieces of at least {GAP_TO} px: a shorter piece has no
reliable direction.</li>
<li>Everything else in the stem mask is <b>probably leaf</b>.</li>
</ol>
<p><b>Each picture:</b> the photo | the classes: {legend} | the centrelines: white = twig; not a twig because
too wide (orange), too bent (pink), lying on the rim (brown) or not connected to a twig (grey); magenta = straight and long but not connected;
cyan = gaps bridged; red circles = seeds at the pot; yellow circles = long straight seeds; orange line = the pot's
rim.</p>
</div>
<h2>Summary</h2>
<table><tr><th>photo</th><th>stem px</th><th>twig</th><th>share</th><th>probably leaf</th><th>green twig</th>
<th>seeds</th></tr>{table}</table>
<h2>Photos</h2>
{''.join(figs)}
</body></html>"""
    html_to_md.save(page, out / "report.md")


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--photos", nargs="*", default=PHOTOS, help="e.g. P8_side00 P12_side120")
    a = ap.parse_args()
    out = HERE / "results"
    (out / "pictures").mkdir(parents=True, exist_ok=True)
    rows = []
    for name in a.photos:
        path = find_photo(a.photo_set, name)
        img = data.read_photo(path)
        s = seg.segment(img)
        leaf, stem = s["plant1"] > 0, s["stem"] > 0
        t = trace(leaf, stem, s["pot"])
        f = f"{name}.jpg"
        cv2.imwrite(str(out / "pictures" / f), pictures(img, leaf, stem, s["pot"], t, name), [cv2.IMWRITE_JPEG_QUALITY, 85])
        n_stem, n_twig = int(stem.sum()), int((t["twig"] & stem).sum())
        rows.append(dict(photo=name, file=f, stem_px=n_stem, twig_from_stem_px=n_twig,
                         twig_share_of_stem_pct=round(n_twig / max(n_stem, 1) * 100), stem_as_leaf_px=n_stem - n_twig,
                         twig_from_leaf_px=int((t["twig"] & leaf & ~stem).sum()), seeds=len(t["seeds"]),
                         long_seeds=len(t["long_seeds"]), pieces=len(t["pieces"]), twig_pieces=len(t["accepted"]),
                         bridges=len(t["bridges"])))
        print(name, {k: v for k, v in rows[-1].items() if k not in ("photo", "file")})
    with open(out / "stats.csv", "w", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    report(rows, out)
    print(out / "report.md")


if __name__ == "__main__":
    main()
