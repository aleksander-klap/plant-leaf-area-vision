"""Density zones: cut the plant in a photo into a few zones of similar leaf density.

Used by 05_density_zones (optical mass per zone) and 06_photo_selection (how clumped a photo is).

    1. density map: leaf share f in a window around every pixel (only used to draw the zones)
    2. plant area: pixels with f >= edge (the leaves and the gaps between them), plus every leaf pixel
    3. density levels: the f of the leaf pixels is grouped into `levels` levels (k-means); every pixel of the plant
       area gets the nearest level; pieces smaller than min_zone are given to the level around them
    4. zones: every connected piece of one level is a zone. A lone speck smaller than min_zone (away from the plant)
       gets level 0: it has no gaps around it to measure a density from
    5. per zone, counted on the mask itself: f = leaf pixels / zone pixels
"""
from dataclasses import dataclass

import cv2
import numpy as np
from scipy import ndimage

from common.data import density, layers


@dataclass(frozen=True)
class Params:
    window: int = 64       # px at 1/4 resolution, window of the density map that draws the zones (a leaf is ~35 px)
    levels: int = 3        # number of density levels, airy ... dense
    min_zone: int = 4000   # px, smaller pieces are merged into their surroundings (a leaf is ~1000 px)
    edge: float = 0.05     # where the density drops below this, the plant area ends


def _level_map(leaf, f, prm):
    """-1 outside the plant area, 0..levels-1 from airy to dense."""
    area = (f >= prm.edge) | leaf
    vals = f[leaf].reshape(-1, 1).astype(np.float32)
    if len(vals) > 20000:      # k-means on a fixed sample: the same zones on every run, and fast
        vals = vals[np.random.default_rng(0).choice(len(vals), 20000, replace=False)]
    k = max(1, min(prm.levels, len(np.unique(vals))))
    if k == 1:
        centres = np.array([float(vals.mean())])
    else:
        crit = (cv2.TERM_CRITERIA_EPS + cv2.TERM_CRITERIA_MAX_ITER, 50, 1e-4)
        cv2.setRNGSeed(0)
        _, _, c = cv2.kmeans(vals, k, None, crit, 3, cv2.KMEANS_PP_CENTERS)
        centres = np.sort(c.ravel())
    cls = np.full(leaf.shape, -1, np.int32)
    cls[area] = np.digitize(f[area], (centres[1:] + centres[:-1]) / 2)
    return cls, len(centres)


def _merge_small(cls, min_zone, rounds=6):
    """Give pieces smaller than min_zone to the nearest bigger piece. A piece that is a whole island of the plant
    area (nothing around it to join) stays."""
    area = cls >= 0
    isl, _ = ndimage.label(area, structure=np.ones((3, 3)))
    isl_size = np.bincount(isl.ravel())
    for _ in range(rounds):
        small = np.zeros(cls.shape, bool)
        for c in np.unique(cls[area]):
            cc, n = ndimage.label(cls == c, structure=np.ones((3, 3)))
            if n == 0:
                continue
            size = np.bincount(cc.ravel())
            piece_isl = np.zeros(n + 1, np.int64)
            m = cc > 0
            piece_isl[cc[m]] = isl[m]
            bad = (size[1:] < min_zone) & (size[1:] < isl_size[piece_isl[1:]])
            if bad.any():
                small |= np.isin(cc, np.nonzero(bad)[0] + 1)
        if not small.any():
            break
        donor = area & ~small
        if not donor.any():
            break
        _, (ri, ci) = ndimage.distance_transform_edt(~donor, return_indices=True)
        cls[small] = cls[ri[small], ci[small]]
    return cls


def make_zones(leaf, prm=Params()):
    """Zones of one leaf mask. Returns (zone id map: 0 outside, 1.. zones; [zone dicts])."""
    cls, n_levels = _level_map(leaf, density(leaf, prm.window), prm)
    cls = _merge_small(cls, prm.min_zone)
    zid = np.zeros(cls.shape, np.int32)
    zones = []
    for c in range(n_levels):
        cc, n = ndimage.label(cls == c, structure=np.ones((3, 3)))
        for j in range(1, n + 1):
            m = cc == j
            zid[m] = len(zones) + 1
            px, nleaf = int(m.sum()), int((leaf & m).sum())
            zones.append(dict(zone=len(zones) + 1, level=0 if px < prm.min_zone else c + 1, pixels=px, leaf=nleaf,
                              f=nleaf / px))
    return zid, zones


def zone_layers(z, cap):
    """Leaf layers of one zone: -ln(1 - min(f, cap)); a lone speck (level 0) counts as plain leaf pixels."""
    return z["f"] if z["level"] == 0 else float(layers(z["f"], cap))


def optical_mass_zones(zones, cap=0.9):
    """Optical mass of a photo by zones: sum over the zones of zone pixels x zone layers."""
    return float(sum(z["pixels"] * zone_layers(z, cap) for z in zones))


# ----------------------------------------------------------------------------------------------
# picture, to check the zones by eye
# ----------------------------------------------------------------------------------------------

LAYER_MAX = 2.4   # top of the colour scale, a bit above the 0.9 cap (2.30 layers)


def colour(layers):
    """BGR colour of a number of leaf layers (viridis, 0 .. LAYER_MAX), same scale in every picture."""
    v = np.uint8(np.clip(np.asarray(layers, np.float32) / LAYER_MAX, 0, 1) * 255)
    return cv2.applyColorMap(v.reshape(-1, 1), cv2.COLORMAP_VIRIDIS).reshape(*np.shape(layers), 3)


def crop_box(leaf, zid=None, pad=40):
    """(y0, y1, x0, x1) around the plant, so pictures of one photo can share the same crop."""
    m = leaf if zid is None else leaf | (zid > 0)
    ys, xs = np.nonzero(m)
    h, w = leaf.shape
    if len(ys) == 0:
        return 0, h, 0, w
    return max(0, ys.min() - pad), min(h, ys.max() + pad), max(0, xs.min() - pad), min(w, xs.max() + pad)


def _crop(img, box):
    y0, y1, x0, x1 = box
    return img[y0:y1, x0:x1]


def zones_picture(img, leaf, zid, zones, cap=0.9, box=None, highlight=None, numbers=False, show_leaves=True):
    """The photo with every zone tinted by its layers, white zone borders. highlight: a zone id outlined in red;
    numbers: write each zone's id in it (to match a table)."""
    lay = np.zeros(len(zones) + 1, np.float32)
    for z in zones:
        lay[z["zone"]] = zone_layers(z, cap)
    tint = colour(lay[zid])
    inside = zid > 0
    a = 0.55 if show_leaves else 0.85
    out = img.astype(np.float32) * 0.45
    out[inside] = img[inside] * (1 - a) + tint[inside] * a
    if show_leaves:
        out[leaf] = out[leaf] * 0.7 + img[leaf] * 0.3          # leaves keep a bit of their own look
    out = out.astype(np.uint8)
    out[cv2.morphologyEx(zid.astype(np.float32), cv2.MORPH_GRADIENT, np.ones((3, 3))) > 0] = (255, 255, 255)
    if highlight is not None:
        cnt, _ = cv2.findContours((zid == highlight).astype(np.uint8), cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)
        cv2.drawContours(out, cnt, -1, (0, 0, 255), 3)
    if numbers:
        for z in zones:
            if z["level"] == 0:
                continue
            d = cv2.distanceTransform(np.pad((zid == z["zone"]).astype(np.uint8), 1), cv2.DIST_L2, 5)[1:-1, 1:-1]
            y, x = np.unravel_index(np.argmax(d), d.shape)
            txt, sc = str(z["zone"]), (0.6 if d[y, x] > 12 else 0.4)
            (tw, th), _ = cv2.getTextSize(txt, cv2.FONT_HERSHEY_SIMPLEX, sc, 1)
            org = (int(x - tw / 2), int(y + th / 2))
            cv2.putText(out, txt, org, cv2.FONT_HERSHEY_SIMPLEX, sc, (0, 0, 0), 3, cv2.LINE_AA)
            cv2.putText(out, txt, org, cv2.FONT_HERSHEY_SIMPLEX, sc, (255, 255, 255), 1, cv2.LINE_AA)
    return _crop(out, box or crop_box(leaf, zid))


def pixel_picture(img, leaf, window=64, cap=0.9, box=None):
    """The per-pixel method (the baseline at 64 / 0.9): every pixel tinted by its own layers, same colours."""
    lay = layers(density(leaf, window), cap)
    out = img.astype(np.float32) * 0.45
    m = lay > 0.01
    out[m] = img[m] * 0.45 + colour(lay)[m] * 0.55
    return _crop(out.astype(np.uint8), box or crop_box(leaf))


def mask_picture(img, leaf, box=None):
    """The leaf mask in green over the darkened photo."""
    out = (img.astype(np.float32) * 0.35).astype(np.uint8)
    out[leaf] = (60, 220, 60)
    return _crop(out, box or crop_box(leaf))


def legend(width=600, height=18):
    """The colour scale of the pictures, 0 .. LAYER_MAX layers, as a BGR strip."""
    return np.repeat(colour(np.linspace(0, LAYER_MAX, width))[None], height, 0)
