"""Experiment 04, leaf mask only (the first version): the baseline with the window (kernel) size as a variable.
The main run of experiment 04 is kernel_cap.py; this one writes results_leaf_only/.

    python 04_kernel_cap/kernel_size.py PHOTO_SET [--kernels 32 256 8] [--plants P1 P12] [--jobs 16]
    python 00_evaluation/evaluate.py 04_kernel_cap/results_leaf_only/runs.csv

The same method as the baseline (T_64_0.9), with only the kernel changed:

    per photo:  f = leaf share in a kernel x kernel window around every pixel
                optical mass = sum over all pixels of -ln(1 - min(f, 0.9))
    per plant:  mean over its side photos

Kernels from 32 to 256 px in steps of 8: 29 runs, about 20 s. The 64 px run is the baseline itself.

Output (results_leaf_only/):
    runs.csv        every run, plus the baseline, for 00_evaluation
    settings.csv    what the setting means and its values, shown in the report
    method.html     the method in a few lines, shown in the report
"""
import argparse
import csv
import sys
from functools import partial
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data  # noqa: E402

CAP = 0.9
KERNELS = [32, 256, 8]          # first, last, step

METHOD_HTML = """
<p><b>Question:</b> is 64 px the right window for the optical mass?</p>
<p>A blueberry leaf is about 35 px across at 1/4 resolution, and many leaves are bigger. A 64 px window holds only a
few leaves, so one big leaf facing the camera can look like a dense spot. A bigger window sees more of the plant
around each pixel.</p>
<p><b>The method</b> is the baseline with only the window (kernel) size changed:</p>
<ol>
<li><b>Per pixel:</b> f = the leaf share in the kernel × kernel window around it.</li>
<li><b>Per photo:</b> optical mass = the sum over all pixels of −ln(1 − min(f, 0.9)).</li>
<li><b>Per plant:</b> the mean over its side photos.</li>
</ol>
<p class="small muted">A run's name is its kernel: <code>k144</code> is a 144 px window. <code>k064</code> is the
baseline itself.</p>
"""


def write_report_notes(folder, kernels):
    """results/settings.csv and results/method.html, shown in the report."""
    (folder / "method.html").write_text(METHOD_HTML.strip() + "\n", encoding="utf-8")
    with open(folder / "settings.csv", "w", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["setting", "meaning", "values"])
        w.writerow(["kernel", "k: side of the square window, in px at 1/4 photo resolution (a leaf is ~35 px "
                    "across), in which the leaf share around every pixel is measured. A small window sees a few "
                    "leaves, a large one a whole part of the plant.",
                    f"{kernels[0]} to {kernels[-1]} px in steps of {kernels[1] - kernels[0]} (baseline 64)"])


def photo_job(kernels, path):
    """{kernel: optical mass of this photo}."""
    leaf, _ = data.masks(path)
    return {k: data.optical_mass(leaf, k, CAP) for k in kernels}


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("photo_set", type=Path, help="folder with the plant folders (P01, P02, ...)")
    ap.add_argument("--kernels", nargs=3, type=int, default=KERNELS, metavar=("FIRST", "LAST", "STEP"))
    ap.add_argument("--plants", nargs="*", default=None)
    ap.add_argument("--jobs", type=int, default=data.JOBS)
    a = ap.parse_args()
    kernels = sorted(set(range(a.kernels[0], a.kernels[1] + 1, a.kernels[2])) | {64})

    photos = data.for_each_photo(a.photo_set, partial(photo_job, kernels), a.plants, a.jobs)
    runs = [(data.BASELINE, {}, data.plant_means(photos, lambda r: r[64]))]
    runs += [(f"k{k:03d}", {"kernel": k}, data.plant_means(photos, lambda r, k=k: r[k])) for k in kernels]
    print(data.write_runs(HERE / "results_leaf_only" / "runs.csv", runs))
    write_report_notes(HERE / "results_leaf_only", kernels)


if __name__ == "__main__":
    main()
