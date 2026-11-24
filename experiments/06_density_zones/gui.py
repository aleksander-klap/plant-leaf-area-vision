"""A window to look at the density zones of one plant and compare them with the per-pixel method.

    .venv/bin/python 05_density_zones/gui.py [PLANT_FOLDER]

Open the folder of one plant (its side photos), move the sliders and see, photo by photo, the zones next to the
per-pixel method (the baseline, T_64_0.9) and the optical mass of both. A tool to play with, not part of the
experiment: the runs for the regression are made by density_zones.py.

The first time a plant is opened its photos are segmented (about 5 s, cached on disk in cache/). After that a new
setting takes about 2 s; changing only the cap is instant, because it doesn't change the zones.
"""
import sys
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import cv2
import numpy as np
from PySide6.QtCore import QSettings, Qt, QThread, QTimer, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (QAbstractItemView, QApplication, QCheckBox, QFileDialog, QGroupBox, QHBoxLayout,
                               QHeaderView, QLabel, QMainWindow, QProgressBar, QPushButton, QScrollArea, QSizePolicy,
                               QSlider, QSplitter, QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))
from common import data, zones  # noqa: E402

DEFAULT = dict(window=64, levels=3, min_zone=4000, edge=0.05, cap=0.90)       # as density_zones.py
GOOD = dict(window=64, levels=2, min_zone=8000, edge=0.02, cap=0.85)           # the best run of the sweep (current leaf areas)


# ----------------------------------------------------------------------------------------------
# work done in other processes
# ----------------------------------------------------------------------------------------------

def load_job(path):
    """Photo, leaf mask and the baseline optical mass of one photo."""
    leaf, _ = data.masks(path)
    return data.read_photo(path), leaf, data.optical_mass(leaf)


def zones_job(args):
    leaf, prm = args
    zid, zs = zones.make_zones(leaf, prm)
    return zid.astype(np.int16), zs


class Worker(QThread):
    """Loads the plant's photos if needed, then draws the zones of every photo if the zone settings changed."""
    progress = Signal(str, int, int)
    done = Signal(object, object)
    failed = Signal(str)

    def __init__(self, paths, loaded, prm):
        super().__init__()
        self.paths, self.loaded, self.prm = paths, loaded, prm

    def run(self):
        try:
            with ProcessPoolExecutor(max_workers=min(data.JOBS, len(self.paths))) as ex:
                loaded = self.loaded
                if loaded is None:
                    loaded = []
                    for i, r in enumerate(ex.map(load_job, self.paths)):
                        loaded.append(r)
                        self.progress.emit("Loading", i + 1, len(self.paths))
                zs = []
                for i, r in enumerate(ex.map(zones_job, [(leaf, self.prm) for _, leaf, _ in loaded])):
                    zs.append(r)
                    self.progress.emit("Zones", i + 1, len(loaded))
            self.done.emit(loaded, zs)
        except Exception as e:  # shown in the window
            self.failed.emit(f"{type(e).__name__}: {e}")


# ----------------------------------------------------------------------------------------------
# widgets
# ----------------------------------------------------------------------------------------------

class SliderRow(QWidget):
    """Label, slider and value. The slider works in integer steps; `scale` turns them into the real value."""
    released = Signal()

    def __init__(self, name, lo, hi, value, step: float = 1, scale=1.0, fmt="{:g}", tip=""):
        super().__init__()
        self.scale, self.fmt = scale, fmt
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(name)
        lab.setMinimumWidth(110)
        lab.setToolTip(tip)
        self.s = QSlider(Qt.Orientation.Horizontal)
        self.s.setRange(round(lo / scale), round(hi / scale))
        self.step = max(1, round(step / scale))
        self.s.setSingleStep(self.step)
        self.s.setPageStep(self.step)
        self.s.setToolTip(tip)
        self.v = QLabel()
        self.v.setMinimumWidth(52)
        self.v.setAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
        self.s.valueChanged.connect(self._snap)
        self.s.sliderReleased.connect(self.released)
        lay.addWidget(lab)
        lay.addWidget(self.s, 1)
        lay.addWidget(self.v)
        self.set(value)

    def _snap(self, i):
        lo = self.s.minimum()
        j = lo + round((i - lo) / self.step) * self.step
        if j != i:
            self.s.setValue(j)
            return
        self.v.setText(self.fmt.format(self.value()))

    def set(self, value):
        self.s.setValue(round(value / self.scale))
        self._snap(self.s.value())

    def value(self):
        return self.s.value() * self.scale


class ImageView(QLabel):
    """Shows a BGR image scaled to fit, keeping its proportions."""

    def __init__(self, text=""):
        super().__init__(text)
        self.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Ignored)
        self.setMinimumSize(150, 150)
        self._pm = None

    def set_bgr(self, bgr):
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        h, w = rgb.shape[:2]
        self._pm = QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format.Format_RGB888).copy())
        self._fit()

    def clear_image(self, text=""):
        self._pm = None
        self.clear()
        self.setText(text)

    def _fit(self):
        if self._pm is not None:
            self.setPixmap(self._pm.scaled(self.size(), Qt.AspectRatioMode.KeepAspectRatio,
                                           Qt.TransformationMode.SmoothTransformation))

    def resizeEvent(self, e):
        self._fit()
        super().resizeEvent(e)


def table(headers):
    t = QTableWidget(0, len(headers))
    t.setHorizontalHeaderLabels(headers)
    t.verticalHeader().setVisible(False)
    t.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
    t.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
    t.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
    t.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
    return t


def fill(t, rows):
    t.blockSignals(True)
    t.setRowCount(len(rows))
    for i, row in enumerate(rows):
        for j, v in enumerate(row):
            it = QTableWidgetItem(str(v))
            if j:
                it.setTextAlignment(Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter)
            t.setItem(i, j, it)
    t.blockSignals(False)


# ----------------------------------------------------------------------------------------------
# the window
# ----------------------------------------------------------------------------------------------

class Main(QMainWindow):
    def __init__(self, folder=None):
        super().__init__()
        self.setWindowTitle("Density zones vs per pixel")
        self.qs = QSettings("sofa-g08", "density_zones_gui")
        self.folder, self.photos = None, []      # photos: [(angle, path)]
        self.loaded = {}                         # folder -> [(img, leaf, baseline optical mass)]
        self.zs, self.zs_prm = None, None        # zones of every photo [(zid, zones)], and their zone settings
        self.worker, self.pending = None, False

        # ---- left: folder, sliders, plant result
        left = QWidget()
        L = QVBoxLayout(left)
        b = QPushButton("Open plant folder…")
        b.setToolTip("The folder of one plant, with its side photos (P05/P05_side00.JPG …).")
        b.clicked.connect(self.browse)
        L.addWidget(b)
        self.folder_lab = QLabel("no folder")
        self.folder_lab.setWordWrap(True)
        L.addWidget(self.folder_lab)

        g = QGroupBox("Zone settings")
        G = QVBoxLayout(g)
        self.sl = dict(
            window=SliderRow("Window (px)", 16, 256, DEFAULT["window"], step=8,
                             tip="Window of the density map that draws the zones. A leaf is ~35 px across."),
            levels=SliderRow("Density levels", 1, 6, DEFAULT["levels"],
                             tip="How many density levels (airy … dense) the plant is cut into."),
            min_zone=SliderRow("Min zone (px)", 500, 30000, DEFAULT["min_zone"], step=500,
                               tip="Smaller pieces are merged into the zone around them. A leaf is ~1000 px."),
            edge=SliderRow("Plant edge (f)", 0.01, 0.30, DEFAULT["edge"], step=0.01, scale=0.01, fmt="{:.2f}",
                           tip="Where the density drops below this, the plant area ends."),
            cap=SliderRow("Cap (f)", 0.80, 0.99, DEFAULT["cap"], step=0.01, scale=0.01, fmt="{:.2f}",
                          tip="A zone with more leaf share than this counts as this (2.30 layers at 0.90)."),
        )
        for w in self.sl.values():
            G.addWidget(w)
            w.released.connect(self.slider_released)
        row = QHBoxLayout()
        for text, preset in (("Default", DEFAULT), ("Best run", GOOD)):
            pb = QPushButton(text)
            pb.clicked.connect(lambda _=False, p=preset: self.set_preset(p))
            row.addWidget(pb)
        G.addLayout(row)
        self.auto = QCheckBox("Update when a slider is released")
        self.auto.setChecked(True)
        G.addWidget(self.auto)
        L.addWidget(g)

        self.run_btn = QPushButton("Run")
        self.run_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.run_btn.clicked.connect(self.start)
        L.addWidget(self.run_btn)
        self.bar = QProgressBar()
        self.bar.setFormat("")
        L.addWidget(self.bar)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        L.addWidget(self.status)

        pg = QGroupBox("Plant (mean over its photos)")
        P = QVBoxLayout(pg)
        self.plant_lab = QLabel("—")
        self.plant_lab.setTextFormat(Qt.TextFormat.RichText)
        self.plant_lab.setWordWrap(True)
        P.addWidget(self.plant_lab)
        L.addWidget(pg)
        L.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(380)
        scroll.setMaximumWidth(460)

        # ---- middle: photos and the zones of the selected photo
        mid = QSplitter(Qt.Orientation.Vertical)
        pw = QWidget()
        PW = QVBoxLayout(pw)
        PW.setContentsMargins(0, 0, 0, 0)
        PW.addWidget(QLabel("<b>Photos</b> (click one to see it)"))
        self.ptab = table(["photo", "angle", "leaf px", "per pixel", "zones", "zones vs per pixel", "zones n"])
        self.ptab.itemSelectionChanged.connect(self.photo_changed)
        PW.addWidget(self.ptab)
        zw = QWidget()
        ZW = QVBoxLayout(zw)
        ZW.setContentsMargins(0, 0, 0, 0)
        self.zones_title = QLabel("<b>Zones of the photo</b> (click one to outline it)")
        ZW.addWidget(self.zones_title)
        self.ztab = table(["zone", "level", "pixels", "leaf px", "f", "layers", "value"])
        self.ztab.setToolTip("value = pixels × layers; the optical mass of the photo is the sum of the values.\n"
                             "level 0 = a lone speck away from the plant, counted as plain leaf pixels")
        self.ztab.itemSelectionChanged.connect(self.show_pictures)
        ZW.addWidget(self.ztab)
        mid.addWidget(pw)
        mid.addWidget(zw)

        # ---- right: pictures of the selected photo
        right = QWidget()
        R = QVBoxLayout(right)
        nav = QHBoxLayout()
        for text, d in (("◀", -1), ("▶", 1)):
            nb = QPushButton(text)
            nb.setFixedWidth(40)
            nb.clicked.connect(lambda _=False, dd=d: self.step_photo(dd))
            nav.addWidget(nb)
            if d < 0:
                self.photo_title = QLabel("")
                self.photo_title.setStyleSheet("font-weight: bold;")
                nav.addWidget(self.photo_title, 1, Qt.AlignmentFlag.AlignCenter)
        R.addLayout(nav)
        self.tabs = QTabWidget()
        side = QWidget()
        S = QHBoxLayout(side)
        S.setContentsMargins(0, 0, 0, 0)
        self.v_side_z, self.v_side_p = ImageView("Open a plant folder."), ImageView()
        self.side_titles = []
        for title, v in (("zones", self.v_side_z), ("per pixel (baseline)", self.v_side_p)):
            box = QVBoxLayout()
            self.side_titles.append(QLabel(title))
            box.addWidget(self.side_titles[-1], 0, Qt.AlignmentFlag.AlignCenter)
            box.addWidget(v, 1)
            S.addLayout(box)
        self.tabs.addTab(side, "Zones vs per pixel")
        self.v_zones, self.v_pixel, self.v_mask = ImageView(), ImageView(), ImageView()
        self.tabs.addTab(self.v_zones, "Zones")
        self.tabs.addTab(self.v_pixel, "Per pixel (baseline)")
        self.tabs.addTab(self.v_mask, "Leaf mask")
        R.addWidget(self.tabs, 1)
        self.leaf_box = QCheckBox("Show the leaves through the zone colour")
        self.leaf_box.setChecked(True)
        self.leaf_box.toggled.connect(lambda _: self.show_pictures())
        R.addWidget(self.leaf_box)
        R.addWidget(self._legend())

        sp = QSplitter()
        sp.addWidget(scroll)
        sp.addWidget(mid)
        sp.addWidget(right)
        sp.setStretchFactor(2, 1)
        sp.setSizes([400, 560, 900])
        self.setCentralWidget(sp)
        self.resize(1800, 950)
        if folder:
            self.open_folder(Path(folder))

    def _legend(self):
        w = QWidget()
        H = QHBoxLayout(w)
        H.setContentsMargins(0, 0, 0, 0)
        bar = ImageView()
        bar.setMinimumSize(300, 18)
        bar.setFixedHeight(18)
        bar.set_bgr(zones.legend(600, 18))
        H.addWidget(QLabel("leaf layers  0"))
        H.addWidget(bar, 1)
        H.addWidget(QLabel(f"{zones.LAYER_MAX:g}   (leaf share 0.90 = 2.30 layers)"))
        return w

    # ---- settings
    def prm(self):
        v = {k: s.value() for k, s in self.sl.items()}
        return zones.Params(int(v["window"]), int(v["levels"]), int(v["min_zone"]), round(v["edge"], 2))

    def cap(self):
        return round(self.sl["cap"].value(), 2)

    def set_preset(self, p):
        for k, s in self.sl.items():
            s.set(p[k])
        self.start()

    def slider_released(self):
        if self.auto.isChecked():
            self.start()

    # ---- folder and run
    def browse(self):
        p = QFileDialog.getExistingDirectory(self, "Pick one plant folder (its side photos)",
                                             self.qs.value("last_dir", str(Path.home())))
        if p:
            self.open_folder(Path(p))

    def open_folder(self, p):
        photos = data.side_photos(p) if p.is_dir() else []
        if not photos:
            self.status.setText(f"<span style='color:#c00'>No side photos (…_side20.JPG) in {p}.</span>")
            return
        if self.worker is not None and self.worker.isRunning():
            return
        self.folder, self.photos = p, photos
        self.qs.setValue("last_dir", str(p.parent))
        self.folder_lab.setText(f"<b>{data.plant_name(p)}</b>: {len(photos)} side photos<br><small>{p}</small>")
        self.zs = self.zs_prm = None
        fill(self.ptab, [])
        fill(self.ztab, [])
        self.plant_lab.setText("—")
        for v in (self.v_side_z, self.v_side_p, self.v_zones, self.v_pixel, self.v_mask):
            v.clear_image()
        self.start()

    def start(self):
        if self.folder is None:
            self.status.setText("Open a plant folder first.")
            return
        if self.worker is not None and self.worker.isRunning():
            self.pending = True            # run again with the new settings when this one is done
            return
        if self.zs is not None and self.zs_prm == self.prm():
            self.show_results()            # only the cap changed: the zones stay the same
            return
        loaded = self.loaded.get(self.folder)
        self.status.setText("" if loaded else "First time for this plant: loading and segmenting its photos.")
        self.run_btn.setEnabled(False)
        self.worker = Worker([p for _, p in self.photos], loaded, self.prm())
        self.worker.progress.connect(self.on_progress)
        self.worker.done.connect(self.finished)
        self.worker.failed.connect(self.error)
        self.worker.start()

    def on_progress(self, stage, i, n):
        self.bar.setRange(0, n)
        self.bar.setValue(i)
        self.bar.setFormat(f"{stage} %v / %m")

    def error(self, msg):
        self.run_btn.setEnabled(True)
        self.status.setText(f"<span style='color:#c00'>{msg}</span>")

    def finished(self, loaded, zs):
        self.loaded[self.folder] = loaded
        self.zs, self.zs_prm = zs, self.worker.prm
        self.run_btn.setEnabled(True)
        self.bar.setFormat("Done")
        self.status.setText("")
        self.show_results()
        if self.pending:
            self.pending = False
            QTimer.singleShot(0, self.start)

    # ---- results
    def photo_values(self):
        """[(leaf px, per pixel, zones)] for every photo, with the current cap."""
        cap = self.cap()
        return [(int(leaf.sum()), om, zones.optical_mass_zones(zs, cap))
                for (_, leaf, om), (_, zs) in zip(self.loaded[self.folder], self.zs)]

    def show_results(self):
        vals = self.photo_values()
        keep = self.ptab.currentRow()
        fill(self.ptab, [(p.name, f"{a}°", f"{s:,}", f"{pp:,.0f}", f"{zz:,.0f}", f"{(zz / pp - 1) * 100:+.1f}%",
                          len(zs)) for (a, p), (s, pp, zz), (_, zs) in zip(self.photos, vals, self.zs)])
        S, Pp, Zz = (float(np.mean([v[k] for v in vals])) for k in range(3))
        prm = self.zs_prm
        self.plant_lab.setText(
            f"<table cellspacing=4>"
            f"<tr><td>leaf pixels</td><td align=right>{S:,.0f}</td></tr>"
            f"<tr><td>optical mass, per pixel</td><td align=right>{Pp:,.0f}</td><td></td></tr>"
            f"<tr><td><b>optical mass, zones</b></td><td align=right><b>{Zz:,.0f}</b></td>"
            f"<td>{(Zz / Pp - 1) * 100:+.1f}%</td></tr></table>"
            f"<small>zones: window {prm.window}, {prm.levels} levels, min zone {prm.min_zone}, edge {prm.edge:.2f}, "
            f"cap {self.cap():.2f}<br>per pixel: the baseline, window 64, cap 0.90<br>"
            "A constant difference doesn't matter: c absorbs it. What matters is whether the difference changes "
            "from plant to plant.</small>")
        self.ptab.selectRow(keep if 0 <= keep < len(vals) else 0)
        self.photo_changed()

    def step_photo(self, d):
        if self.zs is not None:
            self.ptab.selectRow((max(self.ptab.currentRow(), 0) + d) % len(self.photos))

    def current(self):
        rows = self.ptab.selectionModel().selectedRows()
        return rows[0].row() if rows and self.zs is not None else None

    def photo_changed(self):
        i = self.current()
        if i is None:
            return
        a, p = self.photos[i]
        _, zs = self.zs[i]
        cap = self.cap()
        self.photo_title.setText(f"{p.name}   ({a}°)")
        self.zones_title.setText(f"<b>Zones of {p.name}</b> (click one to outline it)")
        fill(self.ztab, [(z["zone"], z["level"], f"{z['pixels']:,}", f"{z['leaf']:,}", f"{z['f']:.3f}",
                          f"{zones.zone_layers(z, cap):.2f}", f"{z['pixels'] * zones.zone_layers(z, cap):,.0f}")
                         for z in zs])
        self.show_pictures()

    def show_pictures(self):
        i = self.current()
        if i is None:
            return
        img, leaf, om = self.loaded[self.folder][i]
        zid, zs = self.zs[i]
        zid = zid.astype(np.int32)
        cap = self.cap()
        rows = self.ztab.selectionModel().selectedRows()
        hl = zs[rows[0].row()]["zone"] if rows else None
        box = zones.crop_box(leaf, zid)
        zpic = zones.zones_picture(img, leaf, zid, zs, cap, box=box, highlight=hl, numbers=True,
                                   show_leaves=self.leaf_box.isChecked())
        ppic = zones.pixel_picture(img, leaf, box=box)
        self.side_titles[0].setText(f"zones: optical mass {zones.optical_mass_zones(zs, cap):,.0f}")
        self.side_titles[1].setText(f"per pixel (baseline): optical mass {om:,.0f}")
        self.v_side_z.set_bgr(zpic)
        self.v_side_p.set_bgr(ppic)
        self.v_zones.set_bgr(zpic)
        self.v_pixel.set_bgr(ppic)
        self.v_mask.set_bgr(zones.mask_picture(img, leaf, box=box))

    def closeEvent(self, e):
        if self.worker is not None:
            self.worker.wait()
        super().closeEvent(e)


def main():
    app = QApplication(sys.argv)
    w = Main(sys.argv[1] if len(sys.argv) > 1 else None)
    w.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
