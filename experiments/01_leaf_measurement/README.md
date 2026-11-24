# 01 Leaf measurement: measuring the picked leaves

**Results:** the leaf area of every plant: [`monday.csv`](results/monday.csv) (the current leaf areas) · [example measurements](results/examples/)

**Status:** window (`gui.py`) with ROI, plate and marker points and sliders; command line (`leafarea.py`). Run on
P08. The leaf mask works well; for the perspective use the plate corners (the marker alone is not reliable, see
below).

## Why

The real leaf areas (the labels of the regression) were measured by hand: threshold, then brush corrections where
shadows were taken or pale leaves missed. This measures them automatically, to check the hand values.

## Use: the window (`gui.py`)

```bash
cd experiments/01_leaf_measurement
uv venv .venv && uv pip install --python .venv/bin/python -r requirements.txt
.venv/bin/python gui.py                       # or: gui.py ~/studies/SOFA/bluberry_photo_set/picked_leaves/P08
```

1. **Open folder…** with the leaf photos of one plant; click a photo in the list.
2. A new photo starts with the marker found automatically (red), the ROI = the paper outline (green), and the
   plate = its box (cyan). On the photo:
   - **drag** any point; **wheel** = zoom; drag the background = move;
   - **ROI:** double-click near an edge to add a point, right-click a point to remove it. Draw it around the
     leaves only (leave out the marker sheet, the number, the table). The marker never counts anyway.
   - **plate:** put the 4 cyan points on the corners of the clear plate.
   - **marker:** the 4 red points on the outer corners of the black square (Find marker redoes it).
3. **Scale and perspective:** marker only; **plate corners + marker** (default: the plate gives the perspective
   over the whole sheet, the marker the aspect ratio and the scale); or plate corners + the plate size in mm
   (width = the top side in the photo).
4. **Leaf detection sliders** (hover for an explanation): colour threshold limits, sure-leaf factor, dark-leaf
   and shadow darkness, size of the local areas, paper model smoothing, smallest / thinnest piece, glare holes.
5. **Measure** (about 2 s): the result is drawn on the photo, where you edit the points: green = leaf, magenta =
   left out as shadow, blue = not counted (outside the paper area, the marker). The **Straightened result** tab shows
   the same from above. Under the area: the area with one scale for comparison, and how the marker and
   the plate come out after straightening (sides in mm, corner angles: a good straightening gives a 150 × 150 mm
   marker and 90° corners).
6. **Brush** (optional), for leaves the detection can't see, e.g. under a light reflex, or things it wrongly
   takes as leaf. Choose **Add leaf** or **Remove leaf**, set the size, and paint on the photo: left-drag paints,
   middle-drag moves the photo, the wheel zooms. Brushed leaf shows yellow, brushed not-leaf orange. Then
   **Measure** again: the brushed pixels are taken as leaf (or not), only inside the ROI (the marker never counts),
   and a later stroke paints over an earlier one. Under the area it shows how much the brush added and removed.
   **Undo stroke** (Ctrl+Z) and **Clear brush** take strokes back; **Off** returns to editing the points. After a
   stroke, Save stays off until you measure again, so the saved area always matches the strokes.
7. **Save:** `results/<folder>/<photo>.json` (all points, brush strokes, perspective and slider settings; loaded
   again when you open the photo), `<photo>_overlay.jpg`, and `areas.csv` (every saved photo of the folder and the total). Saved
   photos show their area in the list.
8. **Measured photos** (left, below; scroll down): every saved photo of every folder, with its **group** (the
   plant: P08 → P8 from the folder name). Double-click the group cell to change it (e.g. put a photo from another
   folder with P1); double-click a photo to open it again. Below it, the group totals.
9. **Start fresh…** (under the measured photos): moves everything in `results/` (all saved measurements and plant
   totals) to `archive/<date_time>/` and sets the settings back to their defaults, so every photo starts again from
   its automatic points. Nothing is deleted; remove the archive folder yourself when you no longer need it.
10. **Save plant totals:** type a file name and press the button: `results/<name>.csv` with
   `plant, real_leaf_area_mm2` (the sum of each group's photos) and `results/<name>_photos.csv` (which photos
   went into each plant).

## Use: the command line (automatic, no ROI)

```bash
.venv/bin/python leafarea.py ~/studies/SOFA/bluberry_photo_set/picked_leaves/P08 --name P08     # about 7 s
```

Marker only, automatic paper area. Writes `<photo>_overlay.jpg`, `<photo>_steps.jpg` (the intermediate maps) and
`areas.csv` to `results/P08/`.

## How it works

1. **Marker:** the outer corners of the 150 × 150 mm black square, found automatically.
2. **Straightening:** the photo is warped so that the marker is a 150 × 150 mm square at 4 px/mm (one pixel =
   0.0625 mm²).
3. **Paper:** the outline around the white sheets. Leaves and leaf piles on the paper count, even at its edge; the
   table, clothes and hands do not. The marker is cut out; near the marker, thin strokes (label, number, printing)
   are dropped, wide pieces (leaves) kept.
4. **Paper colour everywhere:** a smooth model of the paper colour, from the paper between the leaves. Glare,
   shading and reflections of the plate are taken into account locally.
5. **Leaf or not, per pixel:** colour difference from the local paper (dC, Lab a/b) and darkness (L / paper).
   A shadow is darker but has the paper's colour; a leaf has its own colour, or is very dark.
6. **Local thresholds ("kernel"):** the colour threshold is found per 80 mm tile (Otsu between paper/shadow and
   leaf, within 9–30) and smoothly interpolated, so pale leaves and dark leaves each get a fitting threshold.
7. **Clean-up:** sure leaf pixels grown into connected weaker ones; glare holes inside leaves filled; specks
   (< 6 mm²) and thin lines dropped.

## P08 result

| | P08_01 | P08_02 | total |
|---|---|---|---|
| by hand | 112,499 mm² | 127,956 mm² | **240,455 mm²** |
| automatic, one scale from the marker | 109,350 mm² | 124,973 mm² | **234,323 mm²** (−2.6%) |
| automatic, straightened with the marker | 117,198 mm² | 122,570 mm² | 239,768 mm² |

- **The mask agrees with the hand mask within about 3%.** Counted in the same photo pixels, the automatic mask has
  3.1% (P08_01) and 2.7% (P08_02) fewer leaf pixels than the hand mask. Shadows are left out (thin magenta
  crescents), pale and yellowish leaves are found, dark leaves at the top are kept. Check the overlays for the 3%:
  is the hand brush a bit generous at the edges, or does the automatic mask miss leaf edges?
- **The perspective correction from the marker alone is not reliable.** The clear plate is a rectangle and looks
  rectangular in the photos, so they were taken almost straight down. After straightening with the marker, the
  plate comes out skewed: its left and right sides differ by 50 mm (6%) and its bottom edge tilts by 5–8°. One side
  of the marker is 2% longer than the others in the photo (the printed sheet is not perfectly flat), and that error
  grows over the 1 m sheet. So the straightened values (+7% and −2% against one scale) are mostly this error, not
  real perspective. For now, **use the one-scale values**; for these two nearly top-down photos they are the better
  number.

With the plate corners (rough corners read off P08_01) and an ROI around the plate only: 107,881 mm², 0.9% from
the one-scale value; the marker comes out 149–153 mm with 89–91° corners.

## Next

- Enter the plate size when known (perspective "plate corners + plate size").
- ~~Measure all plants in the window.~~ Done: the current leaf areas, `results/monday.csv`, were measured with it.
