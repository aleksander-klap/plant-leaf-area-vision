# 00 Evaluation: the regression test every experiment goes through

**Results:** [the baseline's report](baseline/report.md) (`T_64_0.9`, the starting point every experiment is compared with)

`evaluate.py` tests the runs of an experiment with the model of the regression
(`Regression/docs/single_feature_model.md`) and writes a report. All experiments use it, so their results compare
directly.

```bash
.venv/bin/python 00_evaluation/evaluate.py EXPERIMENT/results/runs.csv [--detail RUN ...] [--perm 1000]
```

## Input: `runs.csv`

Every experiment script writes one, with one row per run and plant:

```
run, <settings of the experiment...>, plant, optical_mass
```

- **A run** is one way of computing the optical mass, e.g. one kernel size. `optical_mass` is its plant value, the
  mean over the plant's photos.
- **The run named `baseline`** is the current method, `T_64_0.9`. Every experiment includes it, computed on the same
  masks and photos, as the reference.
- **The leaf areas** come from `common/real_leaf_area_mm2.csv`. Plants without one are skipped.
- **Optional `settings.csv`** next to `runs.csv`, with the columns `setting, meaning[, values]`: what every setting
  of the experiment means. The report shows it as a table, so a reader knows what the run names stand for.

## The test

- **Model:** `leaf area = c × optical mass`, a line through zero with one number c learned from the plants.
- **Leave-one-out:** every plant in turn is left out, c is learned from the others, and the plant is predicted. Each
  prediction comes from a model that never saw the plant.
- **Typical error:** the RMSE of those predictions as a % of the mean leaf area, the number the regression reports.
  Also reported: R², mean absolute error in %, the worst plant, plants within 5%.
- **Nested (honest) score**, when an experiment has more than one run: the best run is chosen without the plant it
  predicts. This is the number to compare with the baseline, see
  [Best run against honest score](#best-run-against-honest-score).
- **Verdict:** a difference of less than 1 point to the baseline is reported as noise. With 14 plants, a single
  plant can move the typical error by about that much.

## Best run against honest score

A report with many runs gives two numbers, and they answer different questions:

- **Best run:** the lowest typical error of all the runs. It answers "which setting did best on these plants?"
- **Honest (nested) score:** the typical error of the whole procedure "try all the runs, keep the best, predict".
  It answers "how well would tuning do on a plant it has never seen?"

**Why the best run is too optimistic.** Leave-one-out keeps each plant out of learning c, but not out of
choosing the run: every run is scored on all the plants, and the winner is picked after seeing those scores. With
1080 runs and 13–14 plants, some settings fit these particular plants well by chance alone, and the winner is
mostly one of those. Its error is like the luckiest of 1080 coin-flippers: real for these plants, but it won't
repeat on new ones.

**How the nested score works** (`nested_runs` in `common/regression.py`). The whole search is repeated once per
plant, with that plant hidden:

```
for every plant i:
    hide plant i
    score every run by leave-one-out on the other plants only
    keep the run with the lowest error            <- plant i plays no part in this choice
    learn c on the other plants with that run
    predict plant i
honest score = typical error of these predictions
```

So there are two loops: the outer one holds out the plant to predict, the inner one (leave-one-out on the rest)
picks the run. Plant i is used neither to choose the setting nor to learn c, exactly as a new plant would be. The
chosen run can differ from plant to plant. If it is the same run almost every time, the choice is stable. If it
jumps between runs, the choice is mostly luck.

`nested_model` does the same for the choice between the model forms (`c × x`, `a + b × x`, `a × x^b`, average
plant) in the "Other models" table.

**Example, experiment 06 (density zones), on the current leaf areas:**

| | typical error |
|---|---|
| baseline, no tuning | 4.05% |
| best of 1080 runs | 3.86% |
| **honest (nested)** | **4.48%** |

The best run looks better than the baseline. Counted honestly, tuning makes things worse (4.48% against 4.05%): the
winning settings had fitted the noise of these plants.

**How to read the two:**

- **Compare the honest score with the baseline.** Use the best run only to see which settings won.
- **The gap between them shows how much luck is in the best run.** The more runs an experiment tries, the larger
  the gap tends to be.
- **The baseline needs no nested score**, because nothing is chosen for it: its leave-one-out error is already
  honest.
- **The 1-point noise rule still applies**, also to the honest score.

## Details per run

For the baseline and the best run (and any `--detail` run) the report also shows:

- **Other models**, tested the same way: `a + b × optical mass`, `a × optical mass^b`, the average plant, and the
  nested choice between them.
- **c in every round:** a stable c means no single plant decides the model.
- **Shuffle test:** the leaf areas are shuffled between the plants `--perm` times. p is the share of shuffles that
  did as well, so p < 0.05 means the optical mass really carries the leaf area.

## Output (next to `runs.csv`)

| File | |
|---|---|
| `report.md` | everything on one page: cards and verdict, all runs, effect of each setting, per-plant errors, the detailed runs |
| `summary.csv` | every run with c, typical error, mean error, R², plants within 5%, difference to the baseline. Best first |
| `best_10pct.csv` | sweeps of 20+ runs only: for every setting value, how often it appears among the best 10% of the runs, against its share of the grid |
| `*.png` | the charts of the page |
