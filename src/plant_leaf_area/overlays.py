"""One picture per step of the pipeline, to see what happens to a photo.

All pictures are at 1/4 resolution (full-resolution masks are reduced for drawing), each with a caption on top.
"""
from pathlib import Path

import cv2
import numpy as np

from . import config as C

GREEN, RED, YELLOW = (60, 200, 60), (40, 40, 230), (0, 220, 255)
CYAN, MAGENTA, BLUE, ORANGE = (230, 200, 0), (200, 60, 220), (230, 120, 0), (0, 140, 255)


def _small(img, scale):
    if scale == 1:
        return img
    h, w = img.shape[:2]
    return cv2.resize(img, (w // scale, h // scale), interpolation=cv2.INTER_AREA)


def _mask(m, scale):
    return _small(m.astype(np.float32), scale) >= 0.5 if scale != 1 else m


def _paint(base, mask, colour, alpha=0.75):
    out = base.copy()
    out[mask] = ((1 - alpha) * out[mask] + alpha * np.array(colour)).astype(np.uint8)
    return out


def _caption(img, title, legend=()):
    """A white band on top: the title and a legend of (colour, text)."""
    band = np.full((64, img.shape[1], 3), 255, np.uint8)
    cv2.putText(band, title, (12, 26), cv2.FONT_HERSHEY_SIMPLEX, 0.75, (30, 30, 30), 2, cv2.LINE_AA)
    x = 12
    for colour, text in legend:
        cv2.rectangle(band, (x, 38), (x + 16, 54), colour, -1)
        cv2.putText(band, text, (x + 22, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.55, (60, 60, 60), 1, cv2.LINE_AA)
        x += 22 + cv2.getTextSize(text, cv2.FONT_HERSHEY_SIMPLEX, 0.55, 1)[0][0] + 24
    return np.vstack([band, img])


def _heat(values, vmax, cmap, photo):
    v = np.clip(values / max(vmax, 1e-9), 0, 1)
    col = cv2.applyColorMap((v * 255).astype(np.uint8), cmap)
    out = (0.35 * photo).astype(np.uint8)
    show = values > 1e-3
    out[show] = (0.25 * out[show] + 0.75 * col[show]).astype(np.uint8)
    return out


def _colourbar(img, vmax, cmap, label):
    """A small colour bar from 0 to vmax in the top-right corner of the caption band."""
    w, x1 = 260, img.shape[1] - 12
    bar = cv2.applyColorMap(np.tile(np.linspace(0, 255, w).astype(np.uint8), (14, 1)), cmap)
    img[40:54, x1 - w:x1] = bar
    cv2.putText(img, "0", (x1 - w - 18, 52), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 60, 60), 1, cv2.LINE_AA)
    cv2.putText(img, f"{vmax:.2f} {label}", (x1 - w, 30), cv2.FONT_HERSHEY_SIMPLEX, 0.5, (60, 60, 60), 1,
                cv2.LINE_AA)
    return img


def save(out_dir, img, seg, om, settings):
    """Write the pictures of one photo to out_dir/1_seed.jpg ... 7_layers.jpg."""
    s = settings.scale
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    photo = _small(img, s)
    dim = (0.45 * photo).astype(np.uint8)
    m = {k: _mask(getattr(seg, k), s) for k in ("green", "red", "seed", "foreground", "objects", "freed", "plant")}
    pot = seg.pot
    pics = {}

    # 1. seed: green and red-brown pixels; the plant blob outlined
    p = _paint(_paint(dim, m["green"], GREEN), m["red"], RED)
    cnt, _ = cv2.findContours(cv2.dilate(m["seed"].astype(np.uint8), np.ones((9, 9), np.uint8)),
                              cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    cv2.drawContours(p, cnt, -1, YELLOW, 2)
    pics["1_seed"] = _caption(p, "1. Seed: green and red-brown pixels, the plant blob",
                              [(GREEN, "green (excess green)"), (RED, "red-brown leaf"), (YELLOW, "plant blob")])

    # 2. pot: axis, width, bottom and the rim line measured from it
    p = photo.copy()
    legend = [(CYAN, "rim line (bottom - %.3f x width)" % C.POT_H), (ORANGE, "bottom"), (MAGENTA, "axis, width")]
    if pot.found:
        k = 1 / s
        ax, rim, bot, pw = pot.axis * k, pot.rim * k, pot.bottom * k, pot.width * k
        x0, x1 = int(ax - pw / 2), int(ax + pw / 2)
        cv2.line(p, (int(ax), int(rim) - 40), (int(ax), int(bot)), MAGENTA, 2)
        cv2.line(p, (x0, int((rim + bot) / 2)), (x1, int((rim + bot) / 2)), MAGENTA, 2)
        cv2.line(p, (x0 - 30, int(bot)), (x1 + 30, int(bot)), ORANGE, 2)
        cv2.line(p, (x0 - 30, int(rim)), (x1 + 30, int(rim)), CYAN, 2)
        cv2.putText(p, f"width {pot.width:.0f} px", (x1 + 12, int((rim + bot) / 2)), cv2.FONT_HERSHEY_SIMPLEX,
                    0.6, MAGENTA, 2, cv2.LINE_AA)
        title = "2. Pot"
    else:
        title = "2. Pot: NOT FOUND"
    pics["2_pot"] = _caption(p, title, legend)

    # 3. foreground: everything clearly darker or more colourful than the wall behind it
    pics["3_foreground"] = _caption(_paint(dim, m["foreground"], MAGENTA, 0.6),
                                    "3. Foreground: not wall (darker or more colourful than the local wall)",
                                    [(MAGENTA, "foreground")])

    # 4. background objects, with the part freed above the rim
    p = _paint(_paint(dim, m["objects"], BLUE, 0.6), m["freed"], YELLOW, 0.6)
    if pot.found:
        cv2.line(p, (0, int(pot.rim / s)), (p.shape[1], int(pot.rim / s)), CYAN, 1)
    pics["4_objects"] = _caption(p, "4. Background objects: never plant",
                                 [(BLUE, "background object / pot"), (YELLOW, "freed above the rim"),
                                  (CYAN, "rim line")])

    # 5. the plant mask: the seed and what the foreground adds (twigs, dark and brown leaves, leaf edges)
    added = m["plant"] & ~m["seed"]
    p = _paint(_paint(dim, m["plant"] & m["seed"], GREEN, 0.8), added, ORANGE, 0.8)
    pics["5_plant"] = _caption(p, f"5. Plant mask: {int(seg.plant.sum()):,} px",
                               [(GREEN, "seed"), (ORANGE, "added from the foreground")])

    # 6. leaf density in the kernel window
    p = _heat(om.density, 1.0, cv2.COLORMAP_VIRIDIS, photo)
    p = _colourbar(_caption(p, f"6. Leaf density f, kernel {settings.kernel} px"), 1.0, cv2.COLORMAP_VIRIDIS, "")

    pics["6_density"] = p

    # 7. leaf layers -ln(1 - min(f, cap)); their sum is the optical mass
    vmax = float(-np.log1p(-settings.cap))
    p = _heat(om.layers, vmax, cv2.COLORMAP_INFERNO, photo)
    p = _colourbar(_caption(p, f"7. Leaf layers, cap {settings.cap}: optical mass = {om.value:,.0f}"),
                   vmax, cv2.COLORMAP_INFERNO, "layers")
    pics["7_layers"] = p

    for name, pic in pics.items():
        cv2.imwrite(str(out_dir / f"{name}.jpg"), pic, [cv2.IMWRITE_JPEG_QUALITY, 88])
