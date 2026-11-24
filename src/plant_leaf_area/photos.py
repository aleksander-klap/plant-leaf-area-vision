"""Finding and reading the side photos."""
import re
from pathlib import Path

import cv2

IMG_EXT = {".jpg", ".jpeg", ".png", ".tif", ".tiff"}
SIDE_RE = re.compile(r"side_?(\d+)", re.IGNORECASE)
PLANT_RE = re.compile(r"P(\d+)", re.IGNORECASE)


def plant_name(path):
    """'P01', 'P01_side20.JPG', a folder ... -> 'P1' (the name itself if there is no P<number> in it)."""
    m = PLANT_RE.search(Path(path).name)
    return f"P{int(m.group(1))}" if m else Path(path).name


def side_angle(path):
    """'P01_side20.JPG' -> 20; None for a photo that is not a side photo (e.g. the top photo)."""
    m = SIDE_RE.search(Path(path).stem)
    return int(m.group(1)) if m else None


def _side_photos(folder):
    return [p for p in folder.iterdir()
            if p.is_file() and p.suffix.lower() in IMG_EXT and side_angle(p) is not None]


def find_photos(paths):
    """Side photos from photo files, plant folders or a photo set (a folder of plant folders).

    Returns [(plant, angle, path)] sorted by plant number and angle. Top photos are skipped."""
    found = []
    for path in map(Path, paths):
        if path.is_file():
            found.append(path)
        elif path.is_dir():
            found += _side_photos(path)
            for sub in path.iterdir():
                if sub.is_dir():
                    found += _side_photos(sub)
        else:
            raise SystemExit(f"not found: {path}")
    out = {(plant_name(p.parent if PLANT_RE.search(p.parent.name) else p), side_angle(p) or 0, p) for p in found}

    def key(item):
        m = PLANT_RE.search(item[0])
        return (int(m.group(1)) if m else 10 ** 6, item[0], item[1])
    return sorted(out, key=key)


def read_photo(path, scale=1):
    """The photo as BGR: at 1/4 resolution (scale 1, decoded directly at that size) or at full resolution (scale 4)."""
    img = cv2.imread(str(path), cv2.IMREAD_REDUCED_COLOR_4 if scale == 1 else cv2.IMREAD_COLOR)
    if img is None:
        raise RuntimeError(f"cannot read {path}")
    return img
