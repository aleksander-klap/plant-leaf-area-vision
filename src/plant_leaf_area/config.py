"""All settings in one place.

Sizes are in px at 1/4 resolution (1500 x 1000; 1 px ~ 0.75 mm at the pot). At full resolution (`scale` = 4) every
length is multiplied by 4 and every area by 16, so the settings keep their meaning.
"""
from dataclasses import dataclass


@dataclass(frozen=True)
class Settings:
    """What a run can change from the command line."""
    kernel: int = 144       # side of the square window of the leaf density, px at 1/4 resolution
    cap: float = 0.995      # leaf density is capped at this before Beer-Lambert (-ln(1 - cap) layers at most)
    scale: int = 1          # 1: segment at 1/4 resolution, 4: at full resolution (~16x slower)


# --- green and red-brown leaves: the seed of the plant ------------------------------------------------------------
RED_H_LO, RED_H_HI = 14, 160        # red hue: H <= 14 or H >= 160 (OpenCV HSV, 0..179)
RED_S_MIN = 70                      # ... saturated
RED_V_MIN, RED_V_MAX = 40, 200      # ... mid-brightness (darker: shadow/soil, brighter: wall)
RED_OPEN_FRAC = 0.0035              # opening, x image width: drops thin red things (twigs) from the seed
RED_NEAR_FRAC = 0.01                # red must lie within this x image width of green
RED_BASE_CUT = 0.10                 # no red in the lowest 10% of the green plant (rim, soil, trunk)
RED_MIN_AREA_FRAC = 2e-5            # red specks below this share of the image are dropped
SEED_JOIN = 41                      # leaves closer than this belong to the same plant blob

# --- pot ----------------------------------------------------------------------------------------------------------
POT_V_MAX, POT_S_MAX = 95, 70       # pot pixels: dark (HSV V) and grey (HSV S)
POT_MIN_AREA = 3000                 # px^2
POT_W = (100, 400)                  # plausible pot width, px
POT_H_RANGE = (80, 350)             # plausible pot blob height, px
POT_MAX_OFFSET = 250                # pot centre within this of the plant's median x
POT_H = 0.945                       # pot height (bottom to the top of the rim) / pot width: all pots are the same
                                    # model, so the rim line is measured from the bottom, which leaves never hide
POT_HALF = 0.62                     # x pot width: half the width of the pot zone (rim, label, soil) under the rim
POT_FREE = 1.0                      # x pot width: above the rim, a dark object touching the pot is freed this far

# --- wall and foreground ------------------------------------------------------------------------------------------
WALL_WIN = 121                      # window of the local wall colour
D_L = 35.0                          # foreground: this much darker than the local wall (Lab L, 0..255)
D_C = 12.0                          # ... or this much more colourful (Lab chroma)

# --- background objects (dark opening, laptop, markers, pot, table front) -----------------------------------------
OBJ_L_MAX = 110                     # dark: Lab L below this, and not next to green
OBJ_OPEN = 15                       # opening that cuts the thin twigs linking the plant to dark objects
OBJ_MIN_FRAC = 0.012                # dark blobs larger than this share of the image are background objects
OBJ_GROW = 6                        # safety margin around them

# --- the plant ----------------------------------------------------------------------------------------------------
NEAR = 25                           # foreground counts as plant within this distance of the seed
