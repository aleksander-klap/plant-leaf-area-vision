"""Measure the leaf area of picked leaves photographed on paper (test 07). Window: gui.py.

    .venv/bin/python leafarea.py PHOTO_OR_FOLDER [...] [--name P08] [--px-per-mm 4]

The photos: picked leaves under a clear plate on white paper, with a printed black marker square of 150 x 150 mm.

1. Scale and perspective (`homography`). Three ways:
     marker         the marker's 4 corners are mapped to a 150 x 150 mm square. Simple, but the marker is small,
                    so a small error in its corners grows over the 1 m sheet.
     plate          the 4 corners of the clear plate (a rectangle spanning all leaves) give the perspective; the
                    marker gives the plate's aspect ratio (the marker must come out square) and the scale.
     plate + size   the plate corners are mapped to the plate's known size in mm (the marker is not needed).
   The photo is warped so the paper is seen from above at ppm px/mm (4: one pixel = 0.0625 mm2).
2. Area to search: a region of interest (ROI) polygon drawn in the window, or, without one, the white paper found
   automatically (marker cut out, thin printing near it dropped).
3. The local paper colour is modelled from the paper between the leaves (glare, shading, reflections).
4. Per pixel: colour difference from the local paper (dC, Lab a/b) and darkness (r = L / L paper). A shadow is
   darker but has the paper's colour; a leaf has its own colour or is very dark.
5. Local thresholds ("kernel"): the colour threshold is found per tile (Otsu, within dc_min..dc_max) and smoothly
   interpolated, so pale and dark leaves each get a fitting threshold.
6. Sure leaf pixels grown into connected weaker ones; glare holes filled; specks and thin lines dropped.

Output (results/<name>/): <photo>_overlay.jpg, <photo>_steps.jpg, areas.csv
"""
import argparse
import csv
from dataclasses import asdict, dataclass
from pathlib import Path

import cv2
import numpy as np

HERE = Path(__file__).resolve().parent
RESULTS = HERE / "results"
MARKER_MM = 150.0
IMG_EXT = {".jpg", ".jpeg", ".png"}


@dataclass
class Params:
    ppm: float = 4.0            # px per mm of the straightened image
    dc_min: float = 9.0         # limits of the local colour threshold (Lab a/b distance from the paper)
    dc_max: float = 30.0
    dc_sure: float = 1.6        # sure leaf: colour difference above this x the local threshold
    r_dark: float = 0.45        # sure leaf: darker than this share of the paper, whatever the colour
    r_shadow: float = 0.96      # weak leaf pixels must be darker than this share of the paper, or coloured
    tile_mm: float = 80.0       # tile size of the local thresholds
    bg_mm: float = 12.0         # smoothing of the paper colour model
    min_leaf_mm2: float = 6.0   # smaller pieces are specks
    core_mm: float = 1.2        # a piece must be at least this wide somewhere (drops lines)
    hole_mm2: float = 400.0     # holes up to this size inside a leaf are filled (glare)
    label_mm: float = 10.0      # automatic paper only: near the marker, pieces nowhere this wide are printing


# ----------------------------------------------------------------------------------------------
# 1. marker, plate, perspective
# ----------------------------------------------------------------------------------------------

def order_corners(q):
    """4 points -> top-left, top-right, bottom-right, bottom-left (image coordinates)."""
    q = np.asarray(q, np.float32)
    s, d = q.sum(1), np.diff(q, axis=1).ravel()
    return np.array([q[np.argmin(s)], q[np.argmin(d)], q[np.argmax(s)], q[np.argmax(d)]], np.float32)


def find_marker(img):
    """Outer corners of the black marker square (4x2, ordered), or raise."""
    g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    _, dark = cv2.threshold(cv2.GaussianBlur(g, (5, 5), 0), 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    cnts, _ = cv2.findContours(dark, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    best = None
    for c in cnts:
        a = cv2.contourArea(c)
        if a < 0.002 * g.size:
            continue
        ap = cv2.approxPolyDP(c, 0.02 * cv2.arcLength(c, True), True)
        if len(ap) != 4 or not cv2.isContourConvex(ap):
            continue
        q = order_corners(ap.reshape(4, 2))
        sides = [np.linalg.norm(q[i] - q[(i + 1) % 4]) for i in range(4)]
        if min(sides) < 1 or max(sides) / min(sides) > 1.35:
            continue
        m = np.zeros_like(g)
        cv2.fillConvexPoly(m, q.astype(np.int32), 255)
        dark_share = (dark[m > 0] > 0).mean()
        if not 0.35 < dark_share < 0.9:       # a dark frame with a white pattern inside
            continue
        if best is None or a > best[0]:
            best = (a, q)
    if best is None:
        raise RuntimeError("marker not found")
    q = best[1].reshape(-1, 1, 2)
    cv2.cornerSubPix(g, q, (7, 7), (-1, -1), (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 40, 0.01))
    return q.reshape(4, 2)


def side_lengths(q):
    return [float(np.linalg.norm(q[i] - q[(i + 1) % 4])) for i in range(4)]


def homography(marker, ppm, plate=None, plate_mm=None):
    """Photo -> straightened frame (px at ppm px/mm, origin not yet shifted). See the module docstring."""
    marker = order_corners(marker)
    if plate is None:
        s = MARKER_MM * ppm
        return cv2.getPerspectiveTransform(marker, np.array([[0, 0], [s, 0], [s, s], [0, s]], np.float32))
    plate = order_corners(plate)
    if plate_mm is not None:
        w, h = plate_mm[0] * ppm, plate_mm[1] * ppm
        return cv2.getPerspectiveTransform(plate, np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32))
    L = side_lengths(plate)
    w0, h0 = (L[0] + L[2]) / 2, (L[1] + L[3]) / 2
    H0 = cv2.getPerspectiveTransform(plate, np.array([[0, 0], [w0, 0], [w0, h0], [0, h0]], np.float32))
    m = cv2.perspectiveTransform(marker.reshape(1, 4, 2), H0)[0]
    u, v = m[1] - m[0], m[3] - m[0]
    den = u[1] ** 2 - v[1] ** 2
    k2 = (v[0] ** 2 - u[0] ** 2) / den if abs(den) > 1e-6 else np.nan
    k = float(np.sqrt(k2)) if np.isfinite(k2) and k2 > 0 else 1.0
    m2 = m * np.array([1.0, k], np.float32)
    f = MARKER_MM * ppm / np.sqrt(abs(cv2.contourArea(m2.reshape(-1, 1, 2))))
    return np.diag([f, f * k, 1.0]) @ H0


def rectify(img, H, roi=None, max_px=14000):
    """Warp so the paper is seen from above. The canvas covers the ROI (or the whole photo). Returns the warped
    photo, the valid area and the full homography (with the shift)."""
    h, w = img.shape[:2]
    pts = np.asarray(roi, np.float32) if roi is not None else np.array([[0, 0], [w, 0], [w, h], [0, h]], np.float32)
    box = cv2.perspectiveTransform(pts.reshape(1, -1, 2), H)[0]
    x0, y0 = np.floor(box.min(0)) - 10
    x1, y1 = np.ceil(box.max(0)) + 10
    if x1 - x0 > max_px or y1 - y0 > max_px:
        raise RuntimeError("the straightened photo would be too big: check the marker / plate corners")
    T = np.array([[1, 0, -x0], [0, 1, -y0], [0, 0, 1]], np.float64)
    H2 = T @ H
    size = (int(x1 - x0), int(y1 - y0))
    warped = cv2.warpPerspective(img, H2, size, flags=cv2.INTER_LINEAR, borderValue=(0, 0, 0))
    valid = cv2.warpPerspective(np.full((h, w), 255, np.uint8), H2, size, flags=cv2.INTER_NEAREST) > 0
    return warped, valid, H2


def check_shapes(H2, marker, plate, ppm):
    """How the marker and the plate come out after straightening: side lengths in mm, corner angles."""
    out = {}
    for name, q in (("marker", marker), ("plate", plate)):
        if q is None:
            continue
        r = cv2.perspectiveTransform(order_corners(q).reshape(1, 4, 2), H2)[0] / ppm
        ang = []
        for i in range(4):
            a, b = r[i - 1] - r[i], r[(i + 1) % 4] - r[i]
            ang.append(float(np.degrees(np.arccos(np.clip(a @ b / np.linalg.norm(a) / np.linalg.norm(b), -1, 1)))))
        out[name] = dict(sides_mm=side_lengths(r), angles=ang)
    return out


# ----------------------------------------------------------------------------------------------
# 2-6. paper, background, leaves
# ----------------------------------------------------------------------------------------------

def disk(r):
    r = max(1, int(round(r)))
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * r + 1, 2 * r + 1))


def norm_blur(v, w, sigma):
    """Smooth v using only the pixels with weight w (normalized convolution)."""
    k = int(6 * sigma) | 1
    num = cv2.GaussianBlur(v * w, (k, k), sigma)
    den = cv2.GaussianBlur(w, (k, k), sigma)
    return num / np.maximum(den, 1e-6)


def paper_area(lab, valid, marker_r, ppm):
    """Without an ROI: the outline around the white sheets, the marker cut out."""
    L, ch = lab[..., 0], np.hypot(lab[..., 1] - 128, lab[..., 2] - 128)
    s = 1.0 / ppm
    small = lambda x: cv2.resize(x.astype(np.float32), None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    Ls, cs, vs = small(L), small(ch), small(valid) > 0.99
    Lp = np.percentile(Ls[vs], 95)
    white = vs & (Ls > 0.72 * Lp) & (cs < 14)
    white = cv2.morphologyEx(white.astype(np.uint8), cv2.MORPH_OPEN, disk(2))
    n, cc, st, _ = cv2.connectedComponentsWithStats(white, connectivity=8)
    if n < 2:
        raise RuntimeError("paper not found")
    keep = 1 + np.argsort(-st[1:, cv2.CC_STAT_AREA])
    big = st[keep, cv2.CC_STAT_AREA]
    sheets = np.isin(cc, keep[big > 0.15 * big[0]]).astype(np.uint8)
    paper = np.zeros_like(sheets)
    cv2.fillConvexPoly(paper, cv2.convexHull(cv2.findNonZero(sheets)), 1)
    paper &= vs.astype(np.uint8)
    paper = cv2.erode(paper, disk(4))
    mk = marker_r * s
    c = mk.mean(0)
    cut = np.zeros_like(paper)
    cv2.fillConvexPoly(cut, (c + (mk - c) * 1.12).astype(np.int32), 1)
    paper &= 1 - cut
    return cv2.resize(paper, (lab.shape[1], lab.shape[0]), interpolation=cv2.INTER_NEAREST) > 0


def tile_threshold(feat, mask, prm):
    """Otsu threshold of feat inside mask, per overlapping tile, smoothly interpolated. Returns a map."""
    lo, hi = prm.dc_min, prm.dc_max
    t = int(prm.tile_mm * prm.ppm)
    H, W = feat.shape
    ny, nx = max(1, round(H / (t / 2))), max(1, round(W / (t / 2)))
    grid = np.full((ny, nx), np.nan, np.float32)
    for i in range(ny):
        for j in range(nx):
            cy, cx = (i + 0.5) * H / ny, (j + 0.5) * W / nx
            y0, y1 = int(max(0, cy - t / 2)), int(min(H, cy + t / 2))
            x0, x1 = int(max(0, cx - t / 2)), int(min(W, cx + t / 2))
            v = feat[y0:y1, x0:x1][mask[y0:y1, x0:x1]]
            if v.size < 200:
                continue
            v8 = np.clip(v / (2 * hi) * 255, 0, 255).astype(np.uint8)
            thr, _ = cv2.threshold(v8.reshape(-1, 1), 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
            tv = thr / 255 * 2 * hi
            if (v > tv).mean() < 0.02:        # hardly any leaf in the tile: Otsu would split the paper noise
                tv = hi
            grid[i, j] = np.clip(tv, lo, hi)
    if np.all(np.isnan(grid)):
        grid[:] = (lo + hi) / 2
    grid[np.isnan(grid)] = np.nanmedian(grid)
    if min(grid.shape) >= 3:
        grid = cv2.GaussianBlur(grid, (3, 3), 0)
    return cv2.resize(grid, (W, H), interpolation=cv2.INTER_CUBIC)


def segment(warped, area, prm, marker_r=None, auto_paper=False):
    """Leaf and shadow masks in the straightened photo, inside `area`."""
    ppm = prm.ppm
    lab = cv2.cvtColor(cv2.GaussianBlur(warped, (3, 3), 0), cv2.COLOR_BGR2LAB).astype(np.float32)
    L, a, b = lab[..., 0], lab[..., 1], lab[..., 2]
    # paper colour model at 2 px/mm: first guess of what is paper, then smooth its colour around the leaves
    s = 2.0 / ppm
    sm = lambda x: cv2.resize(x, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
    up = lambda x: cv2.resize(x, (L.shape[1], L.shape[0]), interpolation=cv2.INTER_LINEAR)
    Ls, as_, bs, ps = sm(L), sm(a), sm(b), sm(area.astype(np.float32)) > 0.99
    Lp = np.percentile(Ls[ps], 90) if ps.any() else 200.0
    guess = ps & (Ls > 0.8 * Lp) & (np.hypot(as_ - 128, bs - 128) < 10)
    sig = prm.bg_mm * 2
    Lb, ab_, bb_ = Ls, as_, bs
    for _ in range(2):
        w = guess.astype(np.float32)
        Lb, ab_, bb_ = norm_blur(Ls, w, sig), norm_blur(as_, w, sig), norm_blur(bs, w, sig)
        guess = ps & (Ls > 0.85 * Lb) & (np.hypot(as_ - ab_, bs - bb_) < 6)
    Lb, ab_, bb_ = up(Lb), up(ab_), up(bb_)
    dC = np.hypot(a - ab_, b - bb_)
    r = L / np.maximum(Lb, 1)

    cand = area & ((r < 0.97) | (dC > prm.dc_min))
    tC = tile_threshold(dC, cand, prm)
    sure = area & ((dC > prm.dc_sure * tC) | (r < prm.r_dark))
    weak = area & ((dC > tC) | (r < prm.r_dark + 0.1)) & (r < prm.r_shadow)
    n, cc = cv2.connectedComponents((weak | sure).astype(np.uint8), connectivity=8)
    ok = np.zeros(n, bool)
    ok[np.unique(cc[sure])] = True
    ok[0] = False
    leaf = ok[cc]
    # glare holes inside leaves
    n, cc, st, _ = cv2.connectedComponentsWithStats((~leaf & area).astype(np.uint8), connectivity=4)
    small = st[:, cv2.CC_STAT_AREA] < prm.hole_mm2 * ppm * ppm
    small[0] = False
    small[np.unique(np.concatenate([cc[0], cc[-1], cc[:, 0], cc[:, -1]]))] = False
    leaf |= small[cc]
    leaf = cv2.morphologyEx(leaf.astype(np.uint8), cv2.MORPH_OPEN, disk(0.4 * ppm)) > 0
    leaf &= area
    # specks, thin lines, (automatic paper) printing near the marker
    n, cc, st, _ = cv2.connectedComponentsWithStats(leaf.astype(np.uint8), connectivity=8)
    has = lambda m: np.isin(np.arange(n), np.unique(cc[m > 0]))
    keep = has(cv2.erode(leaf.astype(np.uint8), disk(prm.core_mm / 2 * ppm)))
    keep &= st[:, cv2.CC_STAT_AREA] >= prm.min_leaf_mm2 * ppm * ppm
    if auto_paper and marker_r is not None:
        zone = np.zeros(leaf.shape, np.uint8)
        c = marker_r.mean(0)
        cv2.fillConvexPoly(zone, (c + (marker_r - c) * 2.4).astype(np.int32), 1)
        keep &= ~(has(zone) & ~has(cv2.erode(leaf.astype(np.uint8), disk(prm.label_mm / 2 * ppm))))
    keep[0] = False
    leaf = keep[cc]
    shadow = area & ~leaf & (r < 0.88) & (dC < tC)
    return dict(leaf=leaf, shadow=shadow, n_leaves=int(keep.sum()), dC=dC, r=r, tC=tC)


def brush_mask(strokes, shape):
    """Hand corrections painted on the photo, as one map in photo pixels: 0 untouched, 1 = leaf, 2 = not leaf.
    strokes: [{"mode": "add" | "remove", "radius": px, "points": [[x, y], ...]}], in photo pixels; later strokes
    paint over earlier ones."""
    out = np.zeros(shape[:2], np.uint8)
    for st in strokes or []:
        pts = np.round(np.asarray(st["points"], np.float32)).astype(np.int32).reshape(-1, 2)
        if len(pts) == 0:
            continue
        v, r = (1 if st["mode"] == "add" else 2), max(1, int(round(st["radius"])))
        cv2.circle(out, tuple(int(c) for c in pts[0]), r, v, -1, cv2.LINE_8)
        if len(pts) > 1:
            cv2.polylines(out, [pts], False, v, 2 * r, cv2.LINE_8)
    return out


def apply_brush(seg, strokes, img_shape, H2, area):
    """Correct the leaf mask by hand: brushed "add" pixels are leaf, "remove" pixels not. Only inside the counted
    area (the ROI without the marker). Returns the pixels the brush added to and removed from the leaf mask."""
    b = brush_mask(strokes, img_shape)
    if not b.any():
        return 0, 0
    bw = cv2.warpPerspective(b, H2, (area.shape[1], area.shape[0]), flags=cv2.INTER_NEAREST)
    add, rem = (bw == 1) & area, (bw == 2)
    before = seg["leaf"]
    leaf = (before | add) & ~rem
    seg["leaf"] = leaf
    seg["shadow"] = seg["shadow"] & ~leaf
    seg["n_leaves"] = int(cv2.connectedComponents(leaf.astype(np.uint8), connectivity=8)[0] - 1)
    return int((leaf & ~before).sum()), int((before & ~leaf).sum())


def measure(img, prm=None, marker=None, plate=None, plate_mm=None, roi=None, brush=None):
    """Everything for one photo. marker / plate / roi: points in photo pixels (None: marker found automatically,
    no plate, automatic paper area). brush: hand corrections painted on the photo (see brush_mask)."""
    prm = prm or Params()
    marker = order_corners(find_marker(img) if marker is None else marker)
    plate = None if plate is None else order_corners(plate)
    H = homography(marker, prm.ppm, plate, plate_mm)
    warped, valid, H2 = rectify(img, H, roi)
    marker_r = cv2.perspectiveTransform(marker.reshape(1, 4, 2), H2)[0]
    if roi is not None:
        area = np.zeros(valid.shape, np.uint8)
        poly = cv2.perspectiveTransform(np.asarray(roi, np.float32).reshape(1, -1, 2), H2)[0]
        cv2.fillPoly(area, [np.round(poly).astype(np.int32)], 1)
        c = marker_r.mean(0)                    # the marker never counts, whatever the ROI
        cv2.fillConvexPoly(area, np.round(c + (marker_r - c) * 1.08).astype(np.int32), 0)
        area = (area > 0) & valid
    else:
        lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB).astype(np.float32)
        area = paper_area(lab, valid, marker_r, prm.ppm)
    seg = segment(warped, area, prm, marker_r, auto_paper=roi is None)
    added, removed = apply_brush(seg, brush, img.shape, H2, area)
    leaf = seg["leaf"]
    # the same leaves with one scale for the whole photo (marker's mean side), for comparison
    h0, w0 = img.shape[:2]
    back = cv2.warpPerspective(leaf.astype(np.uint8), np.linalg.inv(H2), (w0, h0), flags=cv2.INTER_NEAREST)
    side_px = float(np.mean(side_lengths(marker)))
    mode = "marker" if plate is None else ("plate + size" if plate_mm is not None else "plate + marker")
    return dict(area_mm2=float(leaf.sum() / prm.ppm ** 2),
                area_one_scale_mm2=float(back.sum()) * (MARKER_MM / side_px) ** 2,
                brush_added_mm2=added / prm.ppm ** 2, brush_removed_mm2=removed / prm.ppm ** 2,
                mode=mode, marker=marker, plate=plate, H2=H2, warped=warped, area=area, marker_r=marker_r,
                check=check_shapes(H2, marker, plate, prm.ppm), **seg)


# ----------------------------------------------------------------------------------------------
# pictures
# ----------------------------------------------------------------------------------------------

def overlay(m, name=""):
    vis = m["warped"].copy()
    out = ~m["area"]
    vis[out] = (0.45 * vis[out] + 0.55 * np.array([150, 60, 0])).astype(np.uint8)
    sh = m["shadow"]
    vis[sh] = (0.5 * vis[sh] + 0.5 * np.array([255, 0, 255])).astype(np.uint8)
    lf = m["leaf"]
    vis[lf] = (0.45 * vis[lf] + 0.55 * np.array([0, 230, 0])).astype(np.uint8)
    cnts, _ = cv2.findContours(lf.astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
    cv2.drawContours(vis, cnts, -1, (0, 90, 0), 1)
    cv2.polylines(vis, [m["marker_r"].astype(np.int32)], True, (0, 0, 255), 3)
    if name:
        y = 40
        for t in [name, f"leaf area {m['area_mm2']:,.0f} mm2 ({m['mode']})", f"{m['n_leaves']} pieces"]:
            cv2.putText(vis, t, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (0, 0, 0), 5, cv2.LINE_AA)
            cv2.putText(vis, t, (20, y), cv2.FONT_HERSHEY_SIMPLEX, 1.2, (255, 255, 255), 2, cv2.LINE_AA)
            y += 44
    return vis


def steps(m, prm):
    def col(x, lo, hi):
        v = np.clip((x - lo) / (hi - lo) * 255, 0, 255).astype(np.uint8)
        return cv2.applyColorMap(v, cv2.COLORMAP_VIRIDIS)
    panels = [("colour difference dC", col(m["dC"], 0, 40)), ("darkness L / paper", col(m["r"], 0.2, 1.05)),
              ("local colour threshold", col(m["tC"], prm.dc_min, prm.dc_max)), ("result", overlay(m))]
    s = 900 / panels[0][1].shape[0]
    out = []
    for t, p in panels:
        p = cv2.resize(p, None, fx=s, fy=s, interpolation=cv2.INTER_AREA)
        cv2.putText(p, t, (10, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.8, (255, 255, 255), 2, cv2.LINE_AA)
        out.append(np.pad(p, ((0, 0), (0, 8), (0, 0)), constant_values=255))
    return np.hstack(out)


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("paths", nargs="+", type=Path)
    ap.add_argument("--name", default=None)
    ap.add_argument("--px-per-mm", type=float, default=4.0)
    a = ap.parse_args()
    prm = Params(ppm=a.px_per_mm)
    photos = []
    for p in a.paths:
        photos += sorted(q for q in p.iterdir() if q.suffix.lower() in IMG_EXT) if p.is_dir() else [p]
    name = a.name or (a.paths[0].name if a.paths[0].is_dir() else a.paths[0].stem)
    out = RESULTS / name
    out.mkdir(parents=True, exist_ok=True)
    rows = []
    for p in photos:
        m = measure(cv2.imread(str(p)), prm)
        cv2.imwrite(str(out / f"{p.stem}_overlay.jpg"), overlay(m, p.name), [cv2.IMWRITE_JPEG_QUALITY, 88])
        cv2.imwrite(str(out / f"{p.stem}_steps.jpg"), steps(m, prm), [cv2.IMWRITE_JPEG_QUALITY, 85])
        rows.append([p.name, round(m["area_mm2"], 1), round(m["area_one_scale_mm2"], 1), m["n_leaves"], m["mode"]])
        print(f"{p.name}: {m['area_mm2']:,.0f} mm2 straightened, {m['area_one_scale_mm2']:,.0f} mm2 one scale, "
              f"{m['n_leaves']} pieces")
    with open(out / "areas.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["photo", "leaf_area_mm2_straightened", "leaf_area_mm2_one_scale", "pieces", "mode", *asdict(prm)])
        for r in rows:
            w.writerow([*r, *asdict(prm).values()])
        w.writerow(["TOTAL", round(sum(r[1] for r in rows), 1), round(sum(r[2] for r in rows), 1),
                    sum(r[3] for r in rows), ""])
    print(f"total {sum(r[1] for r in rows):,.0f} mm2 straightened, {sum(r[2] for r in rows):,.0f} mm2 one scale"
          f" -> {out}")


if __name__ == "__main__":
    main()
