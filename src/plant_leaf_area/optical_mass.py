"""Plant mask -> optical mass.

The leaf density f around every pixel is the plant's share of the kernel x kernel window. Where leaves overlap, one
pixel hides several layers; Beer-Lambert gives the number of layers from the density: -ln(1 - f). The density is
capped (f <= cap) so that a fully covered window counts a finite number of layers. The optical mass of a photo is the
sum of the layers over all pixels; the leaf area is proportional to it.
"""
from dataclasses import dataclass

import cv2
import numpy as np


@dataclass
class OpticalMass:
    value: float            # the optical mass of the photo
    density: np.ndarray     # leaf density f per pixel, 1/4 resolution
    layers: np.ndarray      # leaf layers per pixel, 1/4 resolution


def quarter(mask, scale):
    """The mask at 1/4 resolution as fractions: at full resolution (scale 4) each value is the plant's share of a
    4 x 4 block, so the kernel means the same at both resolutions."""
    m = mask.astype(np.float32)
    if scale == 1:
        return m
    h, w = m.shape
    return cv2.resize(m, (w // scale, h // scale), interpolation=cv2.INTER_AREA)


def density(mask, kernel):
    """Plant share in the kernel x kernel window around every pixel (outside the photo counts as empty)."""
    return cv2.boxFilter(mask, -1, (kernel, kernel), normalize=True, borderType=cv2.BORDER_CONSTANT)


def layers(f, cap):
    """Beer-Lambert: -ln(1 - min(f, cap))."""
    return -np.log1p(-np.minimum(f, cap))


def optical_mass(mask, kernel, cap, scale=1):
    f = density(quarter(mask, scale), kernel)
    lay = layers(f, cap)
    return OpticalMass(float(lay.sum()), f, lay)
