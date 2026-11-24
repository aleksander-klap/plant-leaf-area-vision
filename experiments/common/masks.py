"""Segmentation of the side photos: leaf mask, stem mask, pot. Our own copy, to change for the experiments.

Copied from implementation/image_processing/masks.py (the version the regression used), with only the parts that
turn a photo into masks:

* `_get_leaf_mask` / `_get_red_mask`  - the green rule plus the red-brown leaf cue (mask M0)
* `plant_mask` / `find_pot`           - keep only the blob that is the plant; locate the pot
* `segment`                           - mask M1: M0 plus "anything that is clearly not wall" in front of the wall,
                                        so dark red, purple and brown leaves are counted and red stems are not;
                                        and the stem mask: in front of the wall, near the plant, but not leaf
* `overlay`                           - the picture that shows what M1 added and dropped

Left out: analyze_img, _get_outline, _compute_metrics and draw_overlay (the main pipeline's outline and metrics),
and the import of plant_img_process_analyzer/settings.py: the tunables of the red cue are below, with the values the
original uses (settings.py doesn't set any of them).

Changes against the original:

1. **Pot top from the bottom** (`find_pot`, POT_H): the rim line is the pot's bottom minus POT_H x its width, instead
   of the top of the dark pot blob, which leaves hanging over the rim can raise.
2. **Nothing above the rim is pot** (`segment`): dark shaded leaves right above the pot merged with it into one dark
   "background object", where neither leaf nor stem was looked for (P12 lost a dense, fully covered triangle of
   leaves this way). The part of that object above the rim line, near the pot, is freed.
3. **No trunk zone:** the original never accepted non-green pixels as leaf in a strip just above the rim (0.22 x the
   pot width high), taking them for the trunk and the soil. Removed: they go through the normal leaf/stem rules.

Changing this file changes the masks: common/data.py segments every photo again when this file is newer than its
cached mask.

    python common/masks.py PHOTO [PHOTO ...]      # segment photos, write overlays to /tmp/seg
"""
import sys
from pathlib import Path

import cv2
import numpy as np

# tunables of the red-brown leaf cue (M0); the defaults the original reads through settings.py
CFG = dict(RED_CUE=True, RED_H_LO=14, RED_H_HI=160, RED_S_MIN=70, RED_V_MIN=40, RED_V_MAX=200,
           RED_OPEN_FRAC=0.0035, RED_NEAR_FRAC=0.01, RED_BASE_CUT=0.10, RED_MIN_AREA_FRAC=2e-5)

def _cfg(name, default):
    """A tuning value of the red cue (CFG above)."""
    return CFG.get(name, default)


def _get_leaf_mask(img, s=1):
    # Smooth the image to reduce sensor noise before color analysis.
    img = cv2.GaussianBlur(img, (odd(5 * s), odd(5 * s)), 0)
    # Split into BGR channels as signed 16-bit so the ExG math can't underflow.
    b, g, r = [c.astype(np.int16) for c in cv2.split(img)]
    # Excess Green index: strongly positive for green vegetation.
    exg = 2 * g - r - b
    # Clamp to the 0-255 range and convert back to 8-bit for thresholding.
    exg = np.clip(exg, 0, 255).astype(np.uint8)
    # Otsu picks the threshold automatically; result is 0/255 binary.
    _, mask = cv2.threshold(
        exg, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU
    )
    # Morphological opening removes isolated noise pixels.
    kernel = np.ones((3 * s, 3 * s), np.uint8)
    mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, kernel)

    # Red-brown leaves have R >= G, so ExG ~ 0 and they are missed above.
    # Add them as leaf too (set CFG['RED_CUE'] = False to switch off).
    if _cfg("RED_CUE", True):
        mask = cv2.bitwise_or(mask, _get_red_mask(img, mask))

    return mask


def _get_red_mask(blurred_bgr, green_mask):
    """Red-brown leaf pixels that the green rule missed, cleaned of stems/soil."""
    h_img, w_img = green_mask.shape
    hsv = cv2.cvtColor(blurred_bgr, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    # Hue wraps around 0 for red: accept both ends. Saturated, mid-brightness only
    # (dark = shadow/soil, bright = background).
    cand = (
        ((h <= _cfg("RED_H_LO", 14)) | (h >= _cfg("RED_H_HI", 160)))
        & (s >= _cfg("RED_S_MIN", 70))
        & (v >= _cfg("RED_V_MIN", 40))
        & (v <= _cfg("RED_V_MAX", 200))
        & (green_mask == 0)
    ).astype(np.uint8)

    # Opening removes thin things (stems, twigs) that share the colour.
    k = max(3, int(_cfg("RED_OPEN_FRAC", 0.0035) * w_img)) | 1
    cand = cv2.morphologyEx(
        cand, cv2.MORPH_OPEN, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k))
    )

    # A red leaf must touch/sit next to green foliage: drops soil and background.
    kn = max(3, int(_cfg("RED_NEAR_FRAC", 0.01) * w_img)) | 1
    near = cv2.dilate(green_mask, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (kn, kn)))
    cand &= (near > 0).astype(np.uint8)

    # Ignore the lowest part of the plant (pot rim, soil, stem base).
    ys, _ = np.where(green_mask > 0)
    if len(ys) > 0:
        y0, y1 = np.percentile(ys, 0.5), np.percentile(ys, 99.5)
        cand[int(y0 + (1 - _cfg("RED_BASE_CUT", 0.10)) * (y1 - y0)):, :] = 0

    # Drop tiny specks.
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= _cfg("RED_MIN_AREA_FRAC", 2e-5) * h_img * w_img
    return (keep[lab].astype(np.uint8)) * 255


# =============================================================================================
# Plant and pot (moved here from analysis_v2/extract_features.py)
# =============================================================================================

def plant_mask(leaf, s=1):
    """Keep leaf pixels belonging to the plant: the dilated region with most leaf pixels."""
    k = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (odd(41 * s), odd(41 * s)))
    big = cv2.dilate(leaf, k)
    n, lab, _, _ = cv2.connectedComponentsWithStats(big, connectivity=8)
    if n <= 1:
        return leaf
    counts = np.bincount(lab[leaf > 0], minlength=n)
    counts[0] = 0
    return np.where((lab == counts.argmax()) & (leaf > 0), 255, 0).astype(np.uint8)


def find_pot(img, plant, s=1):
    """Dark grey pot under the plant. Returns (axis_x, pot_top_y, pot_bottom_y, pot_width).

    pot_top_y is the rim line, measured from the bottom: bottom - POT_H x width. The bottom and the sides are never
    hidden by leaves, the top often is (leaves hanging over the rim), and all pots are the same model."""
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    dark = ((hsv[..., 2] < 95) & (hsv[..., 1] < 70)).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5 * s, 5 * s), np.uint8))
    ys, xs = np.nonzero(plant)
    xc = np.median(xs)
    y_low = np.percentile(ys, 60)
    n, lab, st, cen = cv2.connectedComponentsWithStats(dark, connectivity=8)
    best, best_score = None, -1
    for i in range(1, n):
        x, y, w, h, a = st[i]
        if a < 3000 * s * s or cen[i][1] < y_low or abs(cen[i][0] - xc) > 250 * s:
            continue
        if not (100 * s < w < 400 * s and 80 * s < h < 350 * s):
            continue
        if a > best_score:
            best, best_score = i, a
    if best is None:
        return np.nan, np.nan, np.nan, np.nan
    # convex hull of the blob: repairs the notch cut by the white label / overhanging leaves
    cnt, _ = cv2.findContours((lab == best).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    comp = np.zeros(dark.shape, np.uint8)
    cv2.fillConvexPoly(comp, cv2.convexHull(np.vstack(cnt)), 1)
    comp = comp > 0
    rows = np.nonzero(comp.any(1))[0]
    top, bot = rows.min(), rows.max()
    band = rows[(rows > top + 0.3 * (bot - top)) & (rows < top + 0.7 * (bot - top))]
    lefts = np.array([np.nonzero(comp[r])[0].min() for r in band])
    rights = np.array([np.nonzero(comp[r])[0].max() for r in band])
    width = float(np.median(rights - lefts))
    return (float(np.median((lefts + rights) / 2)), float(bot - POT_H * width), float(bot), width)


# =============================================================================================
# Mask M1: leaf against the wall (moved here from analysis_v3/seg.py)
# =============================================================================================

# --- tunables (px at 1/4 resolution; 1 px ~ 0.75 mm at the pot) -------------------------------
BG_WIN = 121          # window of the local wall model
D_L = 35.0            # foreground if this much darker than the local wall (L of Lab, 0..255)
D_C = 12.0            # ... or this much more colourful (chroma of Lab)
CORE = 13             # non-green foreground counts as leaf only where it is at least this wide (~10 mm)
MAX_ELONG = 3.0       # ... and compact: area / width^2 above this is a ribbon (trunk), not a leaf
REGROW = 4            # margins and tips given back to an accepted blob
NEAR = 25             # ... and lie within this distance of accepted leaf pixels (grown iteratively)
MAX_BLOB = 8000       # ... and not be larger than this (a cluster of dark leaves, not a laptop)
OBJ_MIN_FRAC = 0.012  # dark non-green blobs larger than this share of the image are background objects
OBJ_GROW = 6          # safety margin around those objects
POT_H = 0.945         # pot height (bottom to the top of the rim) / pot width: all pots are the same model. 5th
                      # percentile of the measured ratio over all 234 photos (median 0.963: there leaves on the rim
                      # make the pot look taller); on the photos this line lies on the top edge of the rim
POT_FREE = 1.0        # above the rim, a dark object touching the pot is freed within this x pot width of its axis


def odd(n):
    """Nearest odd integer >= 1 (kernel sizes)."""
    return max(1, int(round(n)) | 1)


def ell(d):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (d, d))


def green_mask(img, s=1):
    """The pipeline's green rule only (ExG + Otsu + 3x3 opening), without the red cue."""
    b = cv2.GaussianBlur(img, (odd(5 * s), odd(5 * s)), 0)
    bb, g, r = [c.astype(np.int16) for c in cv2.split(b)]
    exg = np.clip(2 * g - r - bb, 0, 255).astype(np.uint8)
    _, m = cv2.threshold(exg, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3 * s, 3 * s), np.uint8))


def wall_background(lab, s=1):
    """Local wall colour. Returns (bg Lab float32 image, valid mask, wall-candidate mask)."""
    L, a, b = lab[..., 0], lab[..., 1] - 128, lab[..., 2] - 128
    chroma = np.hypot(a, b)
    # the wall is the dominant bright, colourless surface: take its brightness from the histogram
    bright = L[(chroma < 12) & (L > 120)]
    l_wall = np.percentile(bright, 60) if bright.size else 190.0
    cand = ((L > l_wall - 45) & (chroma < 12)).astype(np.float32)
    cand = cv2.erode(cand, np.ones((5 * s, 5 * s), np.uint8))    # stay away from object borders
    win = odd(BG_WIN * s)
    for _ in range(2):
        den = cv2.boxFilter(cand, -1, (win, win), normalize=False)
        bg = np.dstack([cv2.boxFilter(lab[..., i] * cand, -1, (win, win), normalize=False) for i in range(3)])
        ok = den > 0.04 * win * win
        bg = bg / np.maximum(den, 1)[..., None]
        # refine: wall candidates are the pixels close to the local estimate
        d = np.abs(lab[..., 0] - bg[..., 0])
        cand = (ok & (d < 10) & (chroma < 12)).astype(np.float32)
        cand = cv2.erode(cand, np.ones((3 * s, 3 * s), np.uint8))
    # fill pixels with too few wall neighbours (dense foliage) from a much larger window
    big = 4 * win + 1
    den2 = cv2.boxFilter(cand, -1, (big, big), normalize=False)
    bg2 = np.dstack([cv2.boxFilter(lab[..., i] * cand, -1, (big, big), normalize=False) for i in range(3)])
    bg2 = bg2 / np.maximum(den2, 1)[..., None]
    bg[~ok] = bg2[~ok]
    valid = ok | (den2 > 0.02 * big ** 2)
    return bg, valid, cand > 0


def scene_zones(img, lab, green, s=1):
    """Big dark background objects (opening on the left, laptop, marker squares, pot, dark table front).
    Returns (zone uint8: 1 = bright uniform background behind this pixel is plausible, object mask)."""
    h, w = img.shape[:2]
    L = lab[..., 0]
    gd = cv2.dilate(green, ell(odd(5 * s))) > 0
    dark = ((L < 110) & ~gd).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, ell(odd(15 * s)))   # breaks stems that link plant and objects
    n, cc, st, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    big = np.zeros(n, bool)
    big[1:] = st[1:, cv2.CC_STAT_AREA] > OBJ_MIN_FRAC * h * w
    obj = big[cc].astype(np.uint8)
    obj = cv2.dilate(obj, ell(odd(2 * OBJ_GROW * s + 1)))
    return (1 - obj).astype(np.uint8), obj


def segment(img, want_debug=False, s=1):
    """img: BGR at 1/4 res, or at s x that (s=4: full resolution; every size in px is scaled with s, every area with
    s^2). Returns dict(m0, m1, stem, plant0, plant1, pot=(ax,top,bot,w), info), pot in the image's own px."""
    h, w = img.shape[:2]
    m0 = _get_leaf_mask(img, s)
    pm0 = plant_mask(m0, s)
    pot = find_pot(img, pm0, s)
    green = green_mask(img, s)
    blur = cv2.GaussianBlur(img, (odd(5 * s), odd(5 * s)), 0)
    lab = cv2.cvtColor(blur, cv2.COLOR_BGR2LAB).astype(np.float32)
    bg, valid, cand = wall_background(lab, s)
    dL = lab[..., 0] - bg[..., 0]
    ch = np.hypot(lab[..., 1] - 128, lab[..., 2] - 128)
    chbg = np.hypot(bg[..., 1] - 128, bg[..., 2] - 128)
    fg = valid & ((dL < -D_L) | (ch - chbg > D_C))
    zone, obj = scene_zones(img, lab, green, s)
    ax, ptop, pbot, pw = pot
    if np.isfinite(ptop):
        rim = max(0, int(round(ptop)))
        x0, x1 = max(0, int(ax - 0.62 * pw)), min(w, int(ax + 0.62 * pw))
        # Nothing above the rim line is pot. Dark shaded leaves right above the pot touch it and merge with it into one
        # dark "background object" (scene_zones); free the part of that object above the rim, near the pot.
        nobj, cobj = cv2.connectedComponents((zone == 0).astype(np.uint8), connectivity=8)
        ids = np.unique(cobj[rim:int(pbot) + 1, x0:x1])
        ids = ids[ids > 0]
        f0, f1 = max(0, int(ax - POT_FREE * pw)), min(w, int(ax + POT_FREE * pw))
        free = np.zeros((h, w), bool)
        free[:rim, f0:f1] = np.isin(cobj[:rim, f0:f1], ids)
        zone[free] = 1
        # the pot and everything under its rim, a bit wider than the pot (rim, label, soil)
        zone[max(0, rim - 4 * s):, x0:x1] = 0
    zone_b = zone > 0
    fgz = (fg & zone_b).astype(np.uint8)
    g = (green > 0)
    # non-green foreground in front of the wall: wide compact blobs are leaves, thin or ribbon shapes are stems
    ng = ((fgz > 0) & ~g).astype(np.uint8)
    core = cv2.morphologyEx(ng, cv2.MORPH_OPEN, ell(odd(CORE * s)))   # locally at least CORE px wide
    n, cc, st, _ = cv2.connectedComponentsWithStats(core, connectivity=8)
    dt = cv2.distanceTransform(core, cv2.DIST_L2, 5)
    dmax = np.zeros(n)
    np.maximum.at(dmax, cc.ravel(), 2 * dt.ravel())
    area = st[:, cv2.CC_STAT_AREA].astype(float)
    leaf_like = (area / np.maximum(dmax, 1) ** 2 <= MAX_ELONG) & (area <= MAX_BLOB * s * s)
    leaf_like[0] = False
    # accept leaf-like cores only next to accepted leaf, growing outwards (red shoot tips etc.)
    acc = ((pm0 > 0) & (g | ~zone_b)).astype(np.uint8)     # start: the plant's green pixels (+ M0 outside the zone)
    remaining = set(np.nonzero(leaf_like)[0].tolist())
    okcore = np.zeros(n, bool)
    changed = True
    while changed and remaining:
        changed = False
        near = cv2.dilate(acc, ell(odd(2 * NEAR * s + 1))) > 0
        for i in np.unique(cc[near & (cc > 0)]):
            if i in remaining:
                okcore[i] = True
                acc[cc == i] = 1
                remaining.discard(i)
                changed = True
    # give the accepted cores their margins and tips back (a few px, only inside the non-green foreground)
    grown = cv2.dilate(okcore[cc].astype(np.uint8), ell(odd(2 * REGROW * s + 1))) & ng
    acc |= grown
    m1 = np.where(zone_b, acc > 0, m0 > 0)
    # inside the zone, green pixels must also be foreground against the wall (drops green-ish wall noise)
    m1 &= np.where(zone_b, (fg | g), True)
    m1 = (m1.astype(np.uint8)) * 255
    pm1 = plant_mask(m1, s)
    stem = ((fgz > 0) & ~(m1 > 0)).astype(np.uint8) * 255
    stem = cv2.bitwise_and(stem, cv2.dilate(pm1, ell(odd(2 * NEAR * s + 1))))
    out = dict(m0=m0, m1=m1, plant0=pm0, plant1=pm1, stem=stem, pot=pot, zone=zone,
               info=dict(obj_px=int(obj.sum())))
    if want_debug:
        out.update(fg=fg.astype(np.uint8) * 255, bg=bg, dL=dL)
    return out


def overlay(img, s):
    """green = leaf in both masks, magenta = added by M1, red = dropped by M1, yellow = stem, blue tint = not wall zone."""
    vis = img.copy()
    both = (s["plant0"] > 0) & (s["plant1"] > 0)
    add = (s["plant1"] > 0) & ~(s["m0"] > 0)
    drop = (s["plant0"] > 0) & ~(s["m1"] > 0)
    st = s["stem"] > 0
    for m, c, a in [(both, (0, 220, 0), 0.45), (st, (0, 255, 255), 0.8), (add, (255, 0, 255), 0.85), (drop, (0, 0, 255), 0.85)]:
        vis[m] = ((1 - a) * vis[m] + a * np.array(c)).astype(np.uint8)
    z = s["zone"] == 0
    vis[z] = (0.75 * vis[z] + 0.25 * np.array([255, 120, 0])).astype(np.uint8)
    return vis


if __name__ == "__main__":
    out = Path("/tmp/seg")
    out.mkdir(parents=True, exist_ok=True)
    for arg in sys.argv[1:]:
        p = Path(arg)
        img = cv2.imread(str(p), cv2.IMREAD_REDUCED_COLOR_4)
        s = segment(img)
        n0, n1 = int((s["plant0"] > 0).sum()), int((s["plant1"] > 0).sum())
        print(f"{p.name}: M0 {n0}  M1 {n1}  ({100 * (n1 / n0 - 1):+.1f}%)  "
              f"stem {int((s['stem'] > 0).sum())}  pot {tuple(round(float(v), 1) for v in s['pot'])}  {s['info']}")
        cv2.imwrite(str(out / f"seg_{p.stem}.jpg"), overlay(img, s), [cv2.IMWRITE_JPEG_QUALITY, 90])
