# Experiments: the way to the final method

The program in [`src/`](../src/) is the end point. This folder is how it got there: twelve experiments, each asking
one question about the method, with the answer and what was decided from it. Each folder has its own README
(question, method, result, conclusion) and, where something was scored, a full report in `results/report.md`.

This page is the story in short. The experiments are numbered in the order they build on each other.

## Where it started

The starting point is the work of **Mosa, a team member**. Mosa tested the team's first image-processing version
against the measured leaf areas with a regression model. Of all the photo measurements, one predicted the leaf area
best on its own: the **optical mass**. It is computed from the leaf mask of each side photo: the leaf share in a
64 × 64 px window around every pixel, turned into leaf layers with Beer-Lambert (`−ln(1 − f)`, f capped at 0.9),
summed over the photo and averaged over the 18 photos. The model is a line through zero,
`leaf area = c × optical mass`.

That method, `T_64_0.9`, is the **baseline**: on the current leaf areas its typical error is **4.05%**. Every
experiment below changes one thing and is compared with it.

## How everything is judged ([00](00_evaluation/))

Every experiment writes its optical masses to a `runs.csv`, and [`00_evaluation/evaluate.py`](00_evaluation/) runs
the same test on them:

- **Leave-one-out:** every plant in turn is left out, c is learned from the other 12, and the plant is predicted.
- **Typical error:** the RMSE of those predictions as a % of the mean leaf area.
- **Honest (nested) score:** an experiment that tries many settings finds one that suits these 13 plants partly by
  luck. The honest score chooses the setting without the plant it predicts, so the choice itself is tested too.
- **Noise:** with 13 plants, one plant more or less moves the error by about a point. Differences below ~1 point
  aren't a result.
- **Shuffle test:** the leaf areas shuffled between the plants 1000 times. If the optical mass really carries the
  leaf area, shuffling makes the error much worse.

## The ground truth ([01](01_leaf_measurement/))

A model can only be as good as the leaf areas it learns from. The leaves of each plant were picked, laid on a sheet
under a clear plate next to a marker of known size, and photographed. The first leaf areas were measured by hand
(threshold, then brush corrections). **Experiment 01** is a tool that measures them automatically, to check the
hand values: it finds the leaves on the sheet, corrects the perspective with the plate corners and the marker,
and has a brush for what the detection can't see. On P9 a light reflex hid some leaves on one photo; the brush fixed
that one case instead of tuning the detection for it.

The current leaf areas (`01_leaf_measurement/results/monday.csv`) come from this tool. Compared with the hand
measurement, every plant came out about 3% lower (a constant offset that c absorbs), except P3 (8% lower). **P1 is
left out** of everything: its leaf photos turned out to be the wrong ones.

## A. What does the mask count?

**[02 Mask check](02_mask_check/)**: before changing any number, look at what the leaf mask really contains. Every
photo was drawn with its masks. **Found:** the leaf mask leaves out **12–20% of the plant**: twigs, stems and red-brown
leaf parts. The plants were late in the season and turning red, so a lot of real leaf was
missing. The segmentation calls all of that the "stem" mask: plant, but not leaf.

**[03 Stems as leaf](03_stems_as_leaf/)**: so count the stem mask too. **Found:** no gain (4.16% against 4.05%).
Most of the worst plants improved, but **P8**, with the most red twigs, went from +3% to +10%. Counting everything
also counts twigs that are not leaf. *This plant, P8, comes back in almost every experiment after this one.*

## B. How is the optical mass computed?

**[04 Cap](04_cap/)**: the leaf + stem mask is denser, and with the cap at 0.9 dense windows stop counting. The cap
was tried from 0.85 to 0.999 on both masks. **Found:** for the leaf mask 0.9 is already right; leaf + stem is best at
0.94 (3.88%), but counted honestly no setting beats the baseline (4.95%). A high cap fails at a 64 px window: a
single leaf clump fills the window and counts as many layers.

**[05 Kernel and cap](05_kernel_cap/)**: if a small window is the problem, make it larger. 165 combinations of
window (32–256 px) and cap on leaf + stem. **Found:** one smooth valley around **kernel 128–160 with a high cap**,
best **3.70%** at kernel 144, cap ≥ 0.97 (honest 4.32%). A large window looks past a single leaf to the depth of the
bush. 12 of 13 plants within 5%, but P8 is still +9%. With the leaf mask alone the window size doesn't matter: the
gain comes from the two together. *Kernel 144 and cap 0.995 are the settings of the final program.*

**[06 Density zones](06_density_zones/)**: a different idea for the same question, run earlier: instead of every
pixel's own window, cut the plant into zones (airy edge, dense core) and give each zone one density. 1080 settings.
**Found:** no gain (honest 4.48%). Zones can only approach the per-pixel baseline, which is the limit of the same
idea: the error isn't in how the density is averaged.

**[07 Photo selection](07_photo_selection/)**: would one or two well-chosen photos (the most even or the most
clumped view) be better than the mean of all 18? **Found:** much worse (9.4–11.3% against 5.7% on that leaf-area
set), even worse than random photos. **Use the mean of all photos**; every added photo lowers the error.

## C. Why do the worst plants fail?

**[08 Problem plants](08_problem_plants/)**: instead of another sweep, look closely at the plants with the largest
errors, for the baseline and for the best run of 05. **Found:** the baseline's errors come from local clumps at a
64 px window; 05's almost all from **P8's twigs**. And a segmentation bug: on **P12**, a dense mass of shaded leaves
right above the pot was merged with the dark pot into one "background object" and never counted as plant.

**[09 Pot fix](09_pot_fix/)**: fix that bug. The pot's rim is now measured from its bottom (all pots are the same
model, and the bottom is never hidden by leaves), and nothing above the rim counts as pot. Also tested: scaling every
plant by the size of its pot in the photo. **Found:** the fix helps both models: baseline 4.05 → **3.74%**, the best
of 05 3.70 → **3.59%**, with P12 gaining most. It wasn't tuned on the errors, so the gain is honest. Pot scaling
made it slightly worse: the pots are the same size in every photo within ±0.6%, so it only adds noise. *Keep the fix,
don't scale.*

## D. Can twigs be told apart from leaves?

After 08, the main error left is P8: twigs counted as leaf. Three ways to separate them were tried.

**[10 Stem classes](10_stem_classes/)** (run earlier, on older data): split the stem pixels by rules into leaf
edges, missed leaf (wide, compact pieces) and twigs (thin); count twigs only as blocking the view. **Found:** the
right direction (3.54% against 4.19% on that set), but counted honestly no clear gain.

**[11 Twig tracing](11_twig_tracing/)**: trace twigs by their shape: straight lines growing from the pot or from
other twigs, followed across gaps where leaves hide them. **Found:** visible twigs are traced well, but twigs broken
up by the leaves in front of them aren't reached, and the result varies a lot between photos of the same plant.
**Dropped** after looking at the overlays; never scored.

**[12 Leaf edges](12_leaf_edges/)**: simpler: count stem pixels close to a leaf as that leaf's own edge, weight the
rest, and segment at full resolution. **Found:** the leaf mask cuts the rim off **every** leaf (13–23% of the optical
mass). Counting the edges and leaving the rest out gives the best number of all: **2.93%, honest 2.99%**, picked the
same way in 12 of 13 rounds.

## The final method, and why it isn't the best number

The program counts **every plant pixel**, leaves and twigs alike, with the **pot fix** (09), **kernel 144** and
**cap 0.995** (05): **3.59%** on the 13 plants. Experiment 12 scored better (2.93%) and still wasn't chosen:

- It relies on the segmentation's leaf/stem split, and that split is made **by colour**: every green pixel is leaf,
  whatever its shape; only non-green pixels get a shape test. These were late-season plants with red-brown twigs. In
  summer the twigs are green, and the split would count them as leaf anyway: the method would behave differently
  depending on the season.
- Telling twigs apart by shape instead didn't work (10, 11).
- Counting everything is simple and the same in every season, and it doesn't need a leaf/stem split at all: colour
  is used only to find where the plant is, not to decide what counts. If the share of twigs is similar between
  plants, c absorbs it; P8 shows it isn't always, and that is the method's known weak spot.

What would come next: a twig/leaf split that doesn't depend on colour, more plants (13 is too few to trust any of
these differences fully), and a test on green summer plants.

## Summary

| # | Experiment | Question | Result | Decision |
|---|---|---|---|---|
| | baseline | Mosa's optical mass: leaf mask, kernel 64, cap 0.9 | **4.05%** | the starting point |
| [00](00_evaluation/) | evaluation | how is every experiment scored? | leave-one-out, honest score, shuffle test | used by all |
| [01](01_leaf_measurement/) | leaf measurement | can the ground truth be trusted? | tool for the picked leaves; P1 left out | the current leaf areas |
| [02](02_mask_check/) | mask check | what does the leaf mask contain? | misses 12–20% of the plant | count more of the plant |
| [03](03_stems_as_leaf/) | stems as leaf | count the stem mask too? | 4.16%; P8 +10% | not at kernel 64 |
| [04](04_cap/) | cap | which cap? | 3.88%, honest 4.95% | a small window is the problem |
| [05](05_kernel_cap/) | kernel and cap | which window, with stems? | **3.70%** (k144, cap ≥ 0.97), honest 4.32% | **kernel 144, cap 0.995** |
| [06](06_density_zones/) | density zones | density per zone instead of per pixel? | honest 4.48% | rejected |
| [07](07_photo_selection/) | photo selection | 1–2 chosen photos instead of 18? | 9.4–11.3% (vs 5.7%) | **use all photos** |
| [08](08_problem_plants/) | problem plants | why do the worst plants fail? | P8's twigs; leaves lost to the pot (P12) | → 09, D |
| [09](09_pot_fix/) | pot fix | stop losing leaves to the pot? | 3.74% / **3.59%** | **keep the fix**, no pot scaling |
| [10](10_stem_classes/) | stem classes | split stems into edges, missed leaf, twigs? | 3.54% (vs 4.19%), honest no gain | right direction |
| [11](11_twig_tracing/) | twig tracing | trace twigs by shape? | not accurate | dropped |
| [12](12_leaf_edges/) | leaf edges | count leaf edges, leave twigs out? | **2.93%**, honest 2.99% | best number; not used (colour-dependent) |
| | **final program** | every plant pixel, pot fix, kernel 144, cap 0.995 | **3.59%** | [`src/`](../src/) |

## Reading the experiments

- **Not all numbers compare.** The leaf areas changed during the project (first hand measurement → Sunday → the
  current set), and the pot fix (09) changed the masks. 02–05 and 08 are on the current leaf areas with the masks
  before the fix; 06 was re-evaluated on the current leaf areas; 07 and 10 are on older leaf areas. Each README says
  which, and its numbers compare only with its own baseline.
- **Order.** The numbering follows the story. 06, 07 and 10 were actually run before 02–05, on an earlier version of
  the code, and their place here is where they fit in the reasoning.
- **Earlier numbers.** The experiments were renumbered for this repository. The reports and run names inside them
  (e.g. `04_best_new_masks` in 09, the best run of 05) still use the numbers they had when they were run:

  | here | earlier | | here | earlier |
  |---|---|---|---|---|
  | 01 leaf measurement | 07 | | 07 photo selection | 06 (first 03) |
  | 02 mask check | 01 | | 08 problem plants | part of 00 |
  | 03 stems as leaf | 02 | | 09 pot fix | 09 |
  | 04 cap | 03 | | 10 stem classes | 08 |
  | 05 kernel and cap | 04 (leaf only: first 02) | | 11 twig tracing | 10 |
  | 06 density zones | 05 (first 01) | | 12 leaf edges | 11 |

- **The team repository.** Paths like `image_processing/masks.py` or `Regression/docs/...` point to the team's
  project repository, which isn't part of this one. `common/masks.py` is this folder's own copy of that segmentation,
  with the leaf/stem split the experiments test.

## Running them

The experiments have their own code (`common/`), separate from the program in `src/`, and their own requirements:

```bash
cd experiments
python -m venv .venv && .venv/bin/pip install -r requirements.txt

PHOTOS=path/to/photo_set          # the full photo set: see the main README
.venv/bin/python 03_stems_as_leaf/stems_as_leaf.py $PHOTOS                      # writes results/runs.csv
.venv/bin/python 00_evaluation/evaluate.py 03_stems_as_leaf/results/runs.csv     # writes results/report.md
```

The commands of each experiment are in its README. The first run segments every photo and caches the masks in
`experiments/cache/`.
