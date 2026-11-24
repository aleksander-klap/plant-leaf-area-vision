# Results

Run on 2026-11-24: **270 photos of 15 plants**, kernel 144 px, cap 0.995, 1/4 resolution (23 s).

## How well the leaf area is predicted

`leaf area = c × optical mass`, tested with leave-one-out on the 13 plants with a measured leaf area (`data/real_leaf_area_mm2.csv`): every plant is predicted by c learned from the other 12.

| | |
|---|---|
| **typical error** (RMSE as % of the mean leaf area) | **3.59%** |
| R² | 0.955 |
| mean absolute error | 3.01% |
| worst plant | P8, 8.3% off |
| plants within 5% | 10 of 13 |
| c, learned on all plants | 1.31972 mm² per unit of optical mass |
| c in the leave-one-out rounds | 1.31417 – 1.32609 |
| shuffle test: typical error with the leaf areas shuffled between the plants | median 25.4%, best 13.3% of 1000 (p = 0.0010) |

## Per plant

Optical mass: the mean over the plant's photos, and how much single photos differ from it (standard deviation). Predicted: by the model learned without the plant.

| plant | photos | optical mass | spread over the photos | measured leaf area, mm² | predicted, mm² | error |
|---|---|---|---|---|---|---|
| P1 | 18 | 197,861 | ±7.0% | — | — | no measured leaf area |
| P2 | 18 | 186,271 | ±7.1% | 248,603 | 245,641 | -1.2% |
| P3 | 18 | 267,088 | ±6.0% | 351,253 | 352,661 | +0.4% |
| P4 | 18 | 168,873 | ±6.7% | 234,098 | 222,260 | **-5.1%** |
| P5 | 18 | 245,506 | ±7.3% | 316,107 | 324,956 | +2.8% |
| P6 | 18 | 218,121 | ±9.5% | 275,843 | 288,980 | +4.8% |
| P7 | 18 | 224,612 | ±6.1% | 301,997 | 295,870 | -2.0% |
| P8 | 18 | 187,020 | ±4.9% | 229,026 | 248,005 | **+8.3%** |
| P9 | 18 | 182,133 | ±3.6% | 244,749 | 240,087 | -1.9% |
| P10 | 18 | 185,856 | ±4.4% | 258,726 | 244,390 | **-5.5%** |
| P11 | 18 | 230,895 | ±4.4% | 300,609 | 305,151 | +1.5% |
| P12 | 18 | 241,593 | ±7.8% | 330,299 | 317,493 | -3.9% |
| P13 | 18 | 148,538 | ±11.5% | 195,339 | 196,057 | +0.4% |
| P14 | 18 | 132,608 | ±7.3% | — | — | no measured leaf area |
| P15 | 18 | 167,139 | ±9.2% | 217,768 | 220,724 | +1.4% |

Errors over 5% in bold. + = predicted too high.

## Files

| file | |
|---|---|
| `per_photo.csv` | optical mass, plant pixels and pot width of every photo |
| `per_plant.csv` | mean optical mass per plant, and its spread over the photos |
| `evaluation.csv` | per plant: measured and predicted leaf area, error %, c learned without the plant |
| `evaluation.json` | the scores, c, the shuffle test and the settings |
| `settings.json` | the settings of the run |
