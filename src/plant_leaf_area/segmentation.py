"""Photo -> plant mask: every pixel of the plant in front of the wall, leaves and twigs alike.

1. **Seed:** green pixels (excess green, Otsu) plus red-brown leaves next to them; the largest blob is the plant.
2. **Pot:** the dark grey blob under the plant; the rim line is measured from its bottom (bottom - POT_H x width).
3. **Wall:** the local colour of the bright wall, around every pixel.
4. **Foreground:** pixels clearly darker or more colourful than the wall behind them.
5. **Background objects:** large dark blobs (dark opening, laptop, the pot, the table front). Dark leaves above the
   pot merge with it into one blob; the part of it above the rim line is freed, and everything under the rim is pot.
6. **Plant:** foreground outside the background objects, within NEAR px of the seed, plus the seed itself.
   No colour or shape rule decides between leaf and twig: both count.
"""
from dataclasses import dataclass

import cv2
import numpy as np

from . import config as C


def odd(n):
    """Nearest odd integer >= 1 (kernel sizes)."""
    return max(1, int(round(n)) | 1)


def disk(d):
    return cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (odd(d), odd(d)))


@dataclass
class Pot:
    axis: float = np.nan        # x of the pot's centre line
    rim: float = np.nan         # y of the rim line
    bottom: float = np.nan      # y of the pot's bottom
    width: float = np.nan       # px

    @property
    def found(self):
        return bool(np.isfinite(self.width))


@dataclass
class Segmentation:
    """The result and every intermediate step (boolean masks at the photo's resolution)."""
    green: np.ndarray           # 1. green pixels
    red: np.ndarray             # 1. red-brown leaf pixels
    seed: np.ndarray            # 1. the plant blob of green + red
    pot: Pot                    # 2.
    foreground: np.ndarray      # 4. not wall
    objects: np.ndarray         # 5. background objects, after the pot fix
    freed: np.ndarray           # 5. the part of the objects freed above the rim
    plant: np.ndarray           # 6. the plant mask


# --- 1. seed --------------------------------------------------------------------------------------------------------

def green_mask(blur, s):
    """Excess green 2G - R - B, thresholded by Otsu, specks removed."""
    b, g, r = [c.astype(np.int16) for c in cv2.split(blur)]
    exg = np.clip(2 * g - r - b, 0, 255).astype(np.uint8)
    _, m = cv2.threshold(exg, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)
    return cv2.morphologyEx(m, cv2.MORPH_OPEN, np.ones((3 * s, 3 * s), np.uint8)) > 0


def red_mask(blur, green):
    """Red-brown leaf pixels the green rule misses (R >= G): red hue, saturated, mid-brightness, not thin, next to
    green and not at the base of the plant. Sizes are fractions of the image width, so they need no scale."""
    h_img, w_img = green.shape
    hsv = cv2.cvtColor(blur, cv2.COLOR_BGR2HSV)
    h, sat, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    cand = (((h <= C.RED_H_LO) | (h >= C.RED_H_HI)) & (sat >= C.RED_S_MIN)
            & (v >= C.RED_V_MIN) & (v <= C.RED_V_MAX) & ~green).astype(np.uint8)
    cand = cv2.morphologyEx(cand, cv2.MORPH_OPEN, disk(max(3, int(C.RED_OPEN_FRAC * w_img)) | 1))
    near = cv2.dilate(green.astype(np.uint8), disk(max(3, int(C.RED_NEAR_FRAC * w_img)) | 1)) > 0
    cand &= near.astype(np.uint8)
    ys = np.nonzero(green)[0]
    if len(ys):
        y0, y1 = np.percentile(ys, 0.5), np.percentile(ys, 99.5)
        cand[int(y0 + (1 - C.RED_BASE_CUT) * (y1 - y0)):, :] = 0
    n, lab, st, _ = cv2.connectedComponentsWithStats(cand, connectivity=8)
    keep = np.zeros(n, bool)
    keep[1:] = st[1:, cv2.CC_STAT_AREA] >= C.RED_MIN_AREA_FRAC * h_img * w_img
    return keep[lab]


def main_blob(mask, s):
    """The pixels of `mask` in the region (mask dilated by SEED_JOIN) that holds most of them."""
    big = cv2.dilate(mask.astype(np.uint8), disk(C.SEED_JOIN * s))
    n, lab = cv2.connectedComponents(big, connectivity=8)
    if n <= 1:
        return mask
    counts = np.bincount(lab[mask], minlength=n)
    counts[0] = 0
    return (lab == counts.argmax()) & mask


# --- 2. pot ---------------------------------------------------------------------------------------------------------

def find_pot(img, seed, s):
    """The largest dark grey blob of pot size under the plant. Its convex hull repairs the notches cut by the label
    and by leaves hanging over it; the width is the median over the middle rows, the rim line bottom - POT_H x width.
    """
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    dark = ((hsv[..., 2] < C.POT_V_MAX) & (hsv[..., 1] < C.POT_S_MAX)).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, np.ones((5 * s, 5 * s), np.uint8))
    ys, xs = np.nonzero(seed)
    if not len(ys):
        return Pot()
    xc, y_low = np.median(xs), np.percentile(ys, 60)
    n, lab, st, cen = cv2.connectedComponentsWithStats(dark, connectivity=8)
    best, best_area = None, -1
    for i in range(1, n):
        _, _, w, h, a = st[i]
        if a < C.POT_MIN_AREA * s * s or cen[i][1] < y_low or abs(cen[i][0] - xc) > C.POT_MAX_OFFSET * s:
            continue
        if not (C.POT_W[0] * s < w < C.POT_W[1] * s and C.POT_H_RANGE[0] * s < h < C.POT_H_RANGE[1] * s):
            continue
        if a > best_area:
            best, best_area = i, a
    if best is None:
        return Pot()
    cnt, _ = cv2.findContours((lab == best).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    hull = np.zeros(dark.shape, np.uint8)
    cv2.fillConvexPoly(hull, cv2.convexHull(np.vstack(cnt)), 1)
    rows = np.nonzero(hull.any(1))[0]
    top, bot = rows.min(), rows.max()
    band = rows[(rows > top + 0.3 * (bot - top)) & (rows < top + 0.7 * (bot - top))]
    lefts = np.array([np.nonzero(hull[r])[0].min() for r in band])
    rights = np.array([np.nonzero(hull[r])[0].max() for r in band])
    width = float(np.median(rights - lefts))
    return Pot(float(np.median((lefts + rights) / 2)), float(bot - C.POT_H * width), float(bot), width)


# --- 3. wall --------------------------------------------------------------------------------------------------------

def wall_colour(lab, s):
    """Local wall colour (Lab) around every pixel: the mean of the wall pixels in a WALL_WIN window, refined twice;
    where too little wall shows (dense foliage), from a 4x larger window. Returns (wall Lab, valid)."""
    L = lab[..., 0]
    chroma = np.hypot(lab[..., 1] - 128, lab[..., 2] - 128)
    bright = L[(chroma < 12) & (L > 120)]
    l_wall = np.percentile(bright, 60) if bright.size else 190.0
    cand = ((L > l_wall - 45) & (chroma < 12)).astype(np.float32)
    cand = cv2.erode(cand, np.ones((5 * s, 5 * s), np.uint8))           # stay away from object borders
    win = odd(C.WALL_WIN * s)

    def local_mean(weights, size):
        den = cv2.boxFilter(weights, -1, (size, size), normalize=False)
        num = np.dstack([cv2.boxFilter(lab[..., i] * weights, -1, (size, size), normalize=False) for i in range(3)])
        return num / np.maximum(den, 1)[..., None], den

    for _ in range(2):
        wall, den = local_mean(cand, win)
        ok = den > 0.04 * win * win
        cand = (ok & (np.abs(L - wall[..., 0]) < 10) & (chroma < 12)).astype(np.float32)
        cand = cv2.erode(cand, np.ones((3 * s, 3 * s), np.uint8))
    big = 4 * win + 1
    wall2, den2 = local_mean(cand, big)
    wall[~ok] = wall2[~ok]
    return wall, ok | (den2 > 0.02 * big ** 2)


# --- 4. foreground --------------------------------------------------------------------------------------------------

def foreground(lab, wall, valid):
    """Clearly darker (D_L) or more colourful (D_C) than the wall behind it."""
    darker = lab[..., 0] - wall[..., 0] < -C.D_L
    chroma = np.hypot(lab[..., 1] - 128, lab[..., 2] - 128)
    colourful = chroma - np.hypot(wall[..., 1] - 128, wall[..., 2] - 128) > C.D_C
    return valid & (darker | colourful)


# --- 5. background objects ------------------------------------------------------------------------------------------

def background_objects(lab, green, s):
    """Large dark blobs that are not next to green, with a safety margin."""
    h, w = green.shape
    near_green = cv2.dilate(green.astype(np.uint8), disk(5 * s)) > 0
    dark = ((lab[..., 0] < C.OBJ_L_MAX) & ~near_green).astype(np.uint8)
    dark = cv2.morphologyEx(dark, cv2.MORPH_OPEN, disk(C.OBJ_OPEN * s))
    n, cc, st, _ = cv2.connectedComponentsWithStats(dark, connectivity=8)
    big = np.zeros(n, bool)
    big[1:] = st[1:, cv2.CC_STAT_AREA] > C.OBJ_MIN_FRAC * h * w
    return cv2.dilate(big[cc].astype(np.uint8), disk(2 * C.OBJ_GROW * s + 1)) > 0


def pot_fix(objects, pot, s):
    """Nothing above the rim line is pot; everything under it, a bit wider than the pot, is.
    Returns (objects, freed): the object pixels above the rim, near the pot, of objects that reach into the pot."""
    h, w = objects.shape
    freed = np.zeros((h, w), bool)
    if not pot.found:
        return objects, freed
    objects = objects.copy()
    rim, bot = max(0, int(round(pot.rim))), int(pot.bottom)
    x0, x1 = max(0, int(pot.axis - C.POT_HALF * pot.width)), min(w, int(pot.axis + C.POT_HALF * pot.width))
    _, cc = cv2.connectedComponents(objects.astype(np.uint8), connectivity=8)
    ids = np.unique(cc[rim:bot + 1, x0:x1])
    ids = ids[ids > 0]
    f0, f1 = max(0, int(pot.axis - C.POT_FREE * pot.width)), min(w, int(pot.axis + C.POT_FREE * pot.width))
    freed[:rim, f0:f1] = np.isin(cc[:rim, f0:f1], ids)
    objects[freed] = False
    objects[max(0, rim - 4 * s):, x0:x1] = True
    return objects, freed


# --- all steps ------------------------------------------------------------------------------------------------------

def segment(img, scale=1):
    """img: BGR at 1/4 resolution (scale 1) or full resolution (scale 4)."""
    s = scale
    blur = cv2.GaussianBlur(img, (odd(5 * s), odd(5 * s)), 0)
    green = green_mask(blur, s)
    red = red_mask(blur, green)
    seed = main_blob(green | red, s)
    pot = find_pot(img, seed, s)
    lab = cv2.cvtColor(blur, cv2.COLOR_BGR2LAB).astype(np.float32)
    wall, valid = wall_colour(lab, s)
    fg = foreground(lab, wall, valid)
    objects, freed = pot_fix(background_objects(lab, green, s), pot, s)
    near_seed = cv2.dilate(seed.astype(np.uint8), disk(2 * C.NEAR * s + 1)) > 0
    # the seed counts where it is green, or inside an object (leaves hanging over the pot); elsewhere, like all
    # other pixels, only if it is foreground
    plant = (fg & ~objects & near_seed) | (seed & (green | objects))
    plant = main_blob(plant, s)
    return Segmentation(green, red, seed, pot, fg, objects, freed, plant)
