"""Window for test 07: measure the picked leaves with a hand-drawn region of interest, plate and marker corners.

    .venv/bin/python gui.py [FOLDER]

- Open folder: a folder with the leaf photos of one plant (e.g. picked_leaves/P08). Click a photo in the list.
- On the photo (wheel = zoom, drag the background = move):
    green polygon   the region of interest (ROI): only leaves inside it count. Drag its points;
                    double-click near an edge to add a point; right-click a point to remove it.
    cyan  4 points  the corners of the clear plate (for the perspective)
    red   4 points  the corners of the black 150 mm marker (found automatically; drag to correct)
- Perspective: marker only, plate corners + marker (the marker gives aspect and scale), or plate corners + the
  plate's size in mm.
- Sliders: the settings of the leaf / shadow decision (leafarea.Params).
- Measure, check the result (on the photo, and straightened), Save: results/<folder>/<photo>.json (all points and
  settings, loaded again next time), <photo>_overlay.jpg, and areas.csv (all saved photos, with the total).
- Brush: paint leaves the detection misses (Add leaf) or wrongly takes (Remove leaf), e.g. under a light reflex.
  The strokes are saved with the photo and applied at every Measure.
- Measured photos: every saved photo of every folder, with its group (the plant; edit the cell to regroup).
  Save plant totals: results/<name>.csv with plant, real_leaf_area_mm2 (the sum of the group's photos).
"""
import csv
import json
import shutil
from datetime import datetime
import os
import re
import sys
from dataclasses import asdict, fields
from pathlib import Path

if os.environ.get("WAYLAND_DISPLAY") and os.environ.get("DISPLAY"):
    os.environ.setdefault("QT_QPA_PLATFORM", "xcb")

import cv2
import numpy as np
from PySide6.QtCore import QPointF, QSettings, Qt, QThread, Signal
from PySide6.QtGui import QBrush, QColor, QImage, QKeySequence, QPainter, QPainterPath, QPen, QPixmap, QShortcut
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox, QDoubleSpinBox, QFileDialog, QGraphicsEllipseItem,
                               QGraphicsItem, QGraphicsPathItem, QGraphicsPixmapItem, QGraphicsScene,
                               QGraphicsSimpleTextItem, QGraphicsView, QGroupBox, QHBoxLayout, QLabel, QListWidget,
                               QListWidgetItem, QMainWindow, QMessageBox, QPushButton, QScrollArea, QSizePolicy, QSlider,
                               QTableWidget, QTableWidgetItem, QHeaderView, QAbstractItemView, QLineEdit,
                               QSplitter, QTabWidget, QVBoxLayout, QWidget)

import leafarea as la

DISPLAY_MAX = 2400          # the photo is shown at most this many px on its long side


def default_group(photo):
    """The plant of a photo: P08 (folder) or P08_01.jpg -> P8."""
    for part in (Path(photo).parent.name, Path(photo).stem):
        m = re.search(r"P(\d+)", part, re.IGNORECASE)
        if m:
            return f"P{int(m.group(1))}"
    return Path(photo).parent.name or "?"


def natural(s):
    """Sort P2 before P10."""
    return [int(t) if t.isdigit() else t.lower() for t in re.split(r"(\d+)", str(s))]


# ----------------------------------------------------------------------------------------------
# small widgets
# ----------------------------------------------------------------------------------------------

class SliderRow(QWidget):
    """Label, slider and value; `scale` turns the slider's integer steps into the real value."""
    changed = Signal()

    def __init__(self, name, lo, hi, value, step=1.0, fmt="{:g}", tip=""):
        super().__init__()
        self.scale, self.fmt = step, fmt
        lay = QHBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lab = QLabel(name)
        lab.setMinimumWidth(150)
        lab.setToolTip(tip)
        self.s = QSlider(Qt.Horizontal)
        self.s.setRange(round(lo / step), round(hi / step))
        self.s.setToolTip(tip)
        self.v = QLabel()
        self.v.setMinimumWidth(48)
        self.v.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        self.s.valueChanged.connect(self._show)
        lay.addWidget(lab)
        lay.addWidget(self.s, 1)
        lay.addWidget(self.v)
        self.set(value)

    def _show(self, _=None):
        self.v.setText(self.fmt.format(self.value()))
        self.changed.emit()

    def value(self):
        return round(self.s.value() * self.scale, 6)

    def set(self, v):
        self.s.setValue(round(v / self.scale))
        self._show()


class ImageView(QLabel):
    def __init__(self, text=""):
        super().__init__(text)
        self.setAlignment(Qt.AlignCenter)
        self.setSizePolicy(QSizePolicy.Ignored, QSizePolicy.Ignored)
        self._pm = None

    def set_bgr(self, bgr):
        rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
        h, w = rgb.shape[:2]
        self._pm = QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())
        self._fit()

    def _fit(self):
        if self._pm is not None:
            self.setPixmap(self._pm.scaled(self.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation))

    def resizeEvent(self, e):
        self._fit()
        super().resizeEvent(e)


def bgr_pixmap(bgr):
    rgb = np.ascontiguousarray(cv2.cvtColor(bgr, cv2.COLOR_BGR2RGB))
    h, w = rgb.shape[:2]
    return QPixmap.fromImage(QImage(rgb.data, w, h, 3 * w, QImage.Format_RGB888).copy())


def rgba_pixmap(rgba):
    rgba = np.ascontiguousarray(rgba)
    h, w = rgba.shape[:2]
    return QPixmap.fromImage(QImage(rgba.data, w, h, 4 * w, QImage.Format_RGBA8888).copy())


# ----------------------------------------------------------------------------------------------
# editable shapes on the photo
# ----------------------------------------------------------------------------------------------

class Handle(QGraphicsEllipseItem):
    R = 7

    def __init__(self, shape, colour):
        super().__init__(-self.R, -self.R, 2 * self.R, 2 * self.R)
        self.owner = shape
        self.setBrush(QBrush(colour))
        self.setPen(QPen(Qt.black, 1.5))
        self.setFlags(QGraphicsItem.ItemIsMovable | QGraphicsItem.ItemSendsGeometryChanges
                      | QGraphicsItem.ItemIgnoresTransformations)
        self.setCursor(Qt.SizeAllCursor)
        self.setZValue(20)

    def itemChange(self, change, value):
        if change == QGraphicsItem.ItemPositionHasChanged:
            self.owner.redraw()
        return super().itemChange(change, value)


class Shape:
    """A closed polygon with draggable points. editable=True: points can be added and removed (ROI)."""

    def __init__(self, scene, colour, label, editable=False, fill_alpha=0):
        self.scene, self.colour, self.label, self.editable = scene, QColor(colour), label, editable
        self.handles = []
        self.path = QGraphicsPathItem()
        pen = QPen(self.colour, 2)
        pen.setCosmetic(True)
        self.path.setPen(pen)
        if fill_alpha:
            c = QColor(self.colour)
            c.setAlpha(fill_alpha)
            self.path.setBrush(QBrush(c))
        self.path.setZValue(10)
        scene.addItem(self.path)
        self.text = QGraphicsSimpleTextItem(label)
        self.text.setBrush(QBrush(self.colour))
        self.text.setFlag(QGraphicsItem.ItemIgnoresTransformations)
        self.text.setZValue(21)
        scene.addItem(self.text)

    def set_points(self, pts):
        for h in self.handles:
            self.scene.removeItem(h)
        self.handles = []
        for x, y in pts:
            self._add_handle(len(self.handles), QPointF(float(x), float(y)))
        self.redraw()

    def _add_handle(self, i, pos):
        h = Handle(self, self.colour)
        h.setPos(pos)
        self.scene.addItem(h)
        self.handles.insert(i, h)
        h.setVisible(self.path.isVisible())
        return h

    def points(self):
        return np.array([[h.pos().x(), h.pos().y()] for h in self.handles], np.float32)

    def redraw(self):
        p = QPainterPath()
        if self.handles:
            p.moveTo(self.handles[0].pos())
            for h in self.handles[1:]:
                p.lineTo(h.pos())
            p.closeSubpath()
            top = min(self.handles, key=lambda h: h.pos().y())
            self.text.setPos(top.pos() + QPointF(10, -24))
        self.path.setPath(p)

    def set_visible(self, v):
        for it in [self.path, self.text, *self.handles]:
            it.setVisible(v)

    def insert_near(self, pos):
        """Add a point on the edge closest to pos."""
        if not self.editable or len(self.handles) < 2:
            return False
        pts = self.points()
        best, bi = None, 0
        for i in range(len(pts)):
            a, b = pts[i], pts[(i + 1) % len(pts)]
            ab = b - a
            t = np.clip(((np.array([pos.x(), pos.y()]) - a) @ ab) / max(ab @ ab, 1e-9), 0, 1)
            d = np.linalg.norm(a + t * ab - np.array([pos.x(), pos.y()]))
            if best is None or d < best:
                best, bi = d, i
        self._add_handle(bi + 1, pos)
        self.redraw()
        return True

    def remove(self, handle):
        if self.editable and len(self.handles) > 3 and handle in self.handles:
            self.handles.remove(handle)
            self.scene.removeItem(handle)
            self.redraw()


BRUSH_COLOUR = {"add": "#facc15", "remove": "#f97316"}      # yellow: painted leaf, orange: painted not-leaf


class PhotoView(QGraphicsView):
    stroke_done = Signal()

    def __init__(self):
        super().__init__()
        self.setScene(QGraphicsScene(self))
        self.setRenderHints(QPainter.Antialiasing | QPainter.SmoothPixmapTransform)
        self.setDragMode(QGraphicsView.ScrollHandDrag)
        self.setTransformationAnchor(QGraphicsView.AnchorUnderMouse)
        self.setBackgroundBrush(QBrush(QColor(40, 40, 40)))
        self.photo = QGraphicsPixmapItem()
        self.result = QGraphicsPixmapItem()
        self.result.setZValue(5)
        self.scene().addItem(self.photo)
        self.scene().addItem(self.result)
        self.roi = Shape(self.scene(), "#22c55e", "ROI", editable=True, fill_alpha=25)
        self.plate = Shape(self.scene(), "#06b6d4", "plate")
        self.marker = Shape(self.scene(), "#ef4444", "marker")
        # brush: hand corrections, in scene (= displayed photo) pixels
        self.brush_mode = None                  # None, "add" or "remove"
        self.brush_r = 20.0
        self.strokes = []                       # [{"mode", "radius", "points", "item"}]
        self._stroke = None
        self._pan = None
        self.brush_shown = True
        self.cursor_ring = QGraphicsEllipseItem()
        pen = QPen(Qt.white, 1.5, Qt.DashLine)
        pen.setCosmetic(True)
        self.cursor_ring.setPen(pen)
        self.cursor_ring.setZValue(30)
        self.cursor_ring.setVisible(False)
        self.scene().addItem(self.cursor_ring)
        self.viewport().setMouseTracking(True)

    # ---- brush
    def set_brush(self, mode, radius):
        self.brush_mode, self.brush_r = mode, float(radius)
        self.setDragMode(QGraphicsView.NoDrag if mode else QGraphicsView.ScrollHandDrag)
        self.viewport().setCursor(Qt.CrossCursor if mode else Qt.ArrowCursor)
        if not mode:
            self.cursor_ring.setVisible(False)

    def _stroke_item(self, st):
        c = QColor(BRUSH_COLOUR[st["mode"]])
        c.setAlpha(120)
        pen = QPen(c, 2 * st["radius"], Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin)
        it = QGraphicsPathItem()
        it.setPen(pen)
        it.setZValue(15)
        it.setVisible(self.brush_shown)
        self.scene().addItem(it)
        st["item"] = it
        self._redraw_stroke(st)

    @staticmethod
    def _redraw_stroke(st):
        pts = st["points"]
        p = QPainterPath(QPointF(*pts[0]))
        for x, y in pts[1:]:
            p.lineTo(x, y)
        if len(pts) == 1:                       # a single click: a dot
            p.lineTo(pts[0][0] + 0.01, pts[0][1])
        st["item"].setPath(p)

    def set_strokes(self, strokes, ds):
        """Strokes in photo pixels (as saved) -> shown on the displayed photo."""
        self.clear_strokes()
        for st in strokes or []:
            if st.get("points"):
                s2 = dict(mode=st["mode"], radius=st["radius"] * ds, points=[[x * ds, y * ds] for x, y in st["points"]])
                self.strokes.append(s2)
                self._stroke_item(s2)

    def strokes_photo(self, ds):
        """The strokes in photo pixels, for measuring and saving."""
        return [dict(mode=st["mode"], radius=round(st["radius"] / ds, 1),
                     points=[[round(x / ds, 1), round(y / ds, 1)] for x, y in st["points"]]) for st in self.strokes]

    def clear_strokes(self):
        for st in self.strokes:
            self.scene().removeItem(st["item"])
        self.strokes = []

    def undo_stroke(self):
        if self.strokes:
            self.scene().removeItem(self.strokes.pop()["item"])
            return True
        return False

    def set_brush_visible(self, v):
        self.brush_shown = v
        for st in self.strokes:
            st["item"].setVisible(v)

    def _ring(self, pos):
        r = self.brush_r
        self.cursor_ring.setRect(pos.x() - r, pos.y() - r, 2 * r, 2 * r)
        self.cursor_ring.setVisible(True)

    def leaveEvent(self, e):
        self.cursor_ring.setVisible(False)
        super().leaveEvent(e)

    def wheelEvent(self, e):
        f = 1.2 if e.angleDelta().y() > 0 else 1 / 1.2
        self.scale(f, f)

    def fit(self):
        self.fitInView(self.photo, Qt.KeepAspectRatio)

    def mouseDoubleClickEvent(self, e):
        if self.roi.path.isVisible() and self.roi.insert_near(self.mapToScene(e.position().toPoint())):
            return
        super().mouseDoubleClickEvent(e)

    def mousePressEvent(self, e):
        if self.brush_mode and e.button() == Qt.MiddleButton:        # move the photo while brushing
            self._pan = e.position()
            return
        if self.brush_mode and e.button() == Qt.LeftButton:
            pos = self.mapToScene(e.position().toPoint())
            self._stroke = dict(mode=self.brush_mode, radius=self.brush_r, points=[[pos.x(), pos.y()]])
            self.strokes.append(self._stroke)
            self._stroke_item(self._stroke)
            if not self.brush_shown:
                self._stroke["item"].setVisible(True)
            return
        if e.button() == Qt.RightButton:
            it = self.itemAt(e.position().toPoint())
            if isinstance(it, Handle):
                it.owner.remove(it)
                return
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._pan is not None:
            d = e.position() - self._pan
            self._pan = e.position()
            self.horizontalScrollBar().setValue(self.horizontalScrollBar().value() - int(d.x()))
            self.verticalScrollBar().setValue(self.verticalScrollBar().value() - int(d.y()))
            return
        if self.brush_mode:
            pos = self.mapToScene(e.position().toPoint())
            self._ring(pos)
            if self._stroke is not None:
                x0, y0 = self._stroke["points"][-1]
                if (pos.x() - x0) ** 2 + (pos.y() - y0) ** 2 >= (0.25 * self._stroke["radius"]) ** 2:
                    self._stroke["points"].append([pos.x(), pos.y()])
                    self._redraw_stroke(self._stroke)
            return
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._pan is not None and e.button() == Qt.MiddleButton:
            self._pan = None
            return
        if self._stroke is not None and e.button() == Qt.LeftButton:
            self._stroke["item"].setVisible(self.brush_shown)
            self._stroke = None
            self.stroke_done.emit()
            return
        super().mouseReleaseEvent(e)


# ----------------------------------------------------------------------------------------------
# background work
# ----------------------------------------------------------------------------------------------

class Worker(QThread):
    done = Signal(object)
    failed = Signal(str)

    def __init__(self, fn, *args):
        super().__init__()
        self.fn, self.args = fn, args

    def run(self):
        try:
            self.done.emit(self.fn(*self.args))
        except Exception as e:  # shown in the window
            self.failed.emit(f"{type(e).__name__}: {e}")


def auto_shapes(img):
    """Starting points for a new photo: marker found automatically, ROI = the paper outline, plate = its box."""
    marker = la.order_corners(la.find_marker(img))
    prm = la.Params(ppm=2.0)
    H = la.homography(marker, prm.ppm)
    warped, valid, H2 = la.rectify(img, H)
    lab = cv2.cvtColor(warped, cv2.COLOR_BGR2LAB).astype(np.float32)
    marker_r = cv2.perspectiveTransform(marker.reshape(1, 4, 2), H2)[0]
    paper = la.paper_area(lab, valid, marker_r, prm.ppm).astype(np.uint8)
    cnts, _ = cv2.findContours(paper, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    h, w = img.shape[:2]
    if cnts:
        c = max(cnts, key=cv2.contourArea)
        poly = cv2.perspectiveTransform(c.reshape(1, -1, 2).astype(np.float32), np.linalg.inv(H2))[0]
        hull = cv2.convexHull(poly.reshape(-1, 1, 2))
        roi = cv2.approxPolyDP(hull, 0.01 * cv2.arcLength(hull, True), True).reshape(-1, 2)
        box = la.order_corners(cv2.boxPoints(cv2.minAreaRect(roi.reshape(-1, 1, 2))))
    else:
        roi = np.array([[0.1 * w, 0.2 * h], [0.9 * w, 0.2 * h], [0.9 * w, 0.95 * h], [0.1 * w, 0.95 * h]])
        box = roi
    return dict(marker=marker, roi=np.asarray(roi, np.float32), plate=np.asarray(box, np.float32))


def run_measure(img, prm, marker, plate, plate_mm, roi, ds, brush=None):
    m = la.measure(img, prm, marker=marker, plate=plate, plate_mm=plate_mm, roi=roi, brush=brush)
    # result layer on the displayed photo: leaf green, shadow magenta
    h, w = img.shape[:2]
    size = (int(round(w * ds)), int(round(h * ds)))
    M = np.diag([ds, ds, 1.0]) @ np.linalg.inv(m["H2"])
    leaf = cv2.warpPerspective(m["leaf"].astype(np.uint8), M, size, flags=cv2.INTER_NEAREST) > 0
    shadow = cv2.warpPerspective(m["shadow"].astype(np.uint8), M, size, flags=cv2.INTER_NEAREST) > 0
    area = cv2.warpPerspective(m["area"].astype(np.uint8), M, size, flags=cv2.INTER_NEAREST) > 0
    layer = np.zeros((size[1], size[0], 4), np.uint8)
    layer[~area] = (0, 60, 150, 110)                  # not counted (outside the paper area, the marker): blue
    layer[shadow] = (255, 0, 255, 120)
    layer[leaf] = (0, 230, 0, 110)
    m["layer"] = layer
    m["overlay"] = la.overlay(m)
    return m


# ----------------------------------------------------------------------------------------------
# main window
# ----------------------------------------------------------------------------------------------

SLIDERS = [  # field, label, lo, hi, step, format, tip
    ("ppm", "Resolution (px/mm)", 2, 6, 0.5, "{:g}", "Straightened image: 4 px/mm = 0.0625 mm² per pixel."),
    ("dc_min", "Colour threshold min", 3, 20, 0.5, "{:g}",
     "Lowest allowed local colour threshold. Lower: paler leaves found, but more shadow / glare."),
    ("dc_max", "Colour threshold max", 15, 50, 1, "{:g}", "Highest allowed local colour threshold."),
    ("dc_sure", "Sure leaf (× threshold)", 1.0, 3.0, 0.1, "{:.1f}",
     "A pixel this many times above the local threshold starts a leaf; weaker pixels join only if connected."),
    ("r_dark", "Dark leaf (L / paper)", 0.2, 0.7, 0.01, "{:.2f}",
     "Darker than this share of the paper is leaf whatever its colour (dark leaves). Higher: more dark shadow."),
    ("r_shadow", "Weak leaf darker than", 0.8, 1.0, 0.01, "{:.2f}",
     "Weak leaf pixels must be at least this much darker than the paper."),
    ("tile_mm", "Local area (mm)", 30, 200, 10, "{:g}", "Tile size for the local thresholds (the 'kernel')."),
    ("bg_mm", "Paper model smoothing (mm)", 4, 40, 1, "{:g}", "How smooth the model of the paper colour is."),
    ("min_leaf_mm2", "Smallest piece (mm²)", 1, 50, 1, "{:g}", "Smaller pieces are dropped as specks."),
    ("core_mm", "Thinnest piece (mm)", 0.4, 4, 0.1, "{:.1f}", "Pieces nowhere this wide are dropped (lines)."),
    ("hole_mm2", "Fill holes up to (mm²)", 0, 2000, 50, "{:g}", "Glare holes inside a leaf up to this are filled."),
]
MODES = ["Marker only", "Plate corners + marker", "Plate corners + plate size"]


class Main(QMainWindow):
    def __init__(self, folder=None):
        super().__init__()
        self.setWindowTitle("Test 07: picked leaf area")
        self.settings = QSettings("sofa-g08", "leafarea07")
        self.folder = None
        self.photo = None
        self.img = None
        self.ds = 1.0
        self.result = None
        self.worker = None
        self.pending = None

        left = QWidget()
        L = QVBoxLayout(left)
        b = QPushButton("Open folder…")
        b.clicked.connect(self.browse)
        L.addWidget(b)
        self.folder_lab = QLabel("no folder")
        self.folder_lab.setWordWrap(True)
        L.addWidget(self.folder_lab)
        self.list = QListWidget()
        self.list.setMaximumHeight(140)
        self.list.currentItemChanged.connect(self.photo_clicked)
        L.addWidget(self.list)

        g = QGroupBox("Shapes")
        G = QVBoxLayout(g)
        self.show_boxes = {}
        row = QHBoxLayout()
        for key, text in (("roi", "ROI"), ("plate", "Plate"), ("marker", "Marker"), ("brush", "Brush"),
                          ("result", "Result")):
            cb = QCheckBox(text)
            cb.setChecked(True)
            cb.toggled.connect(self.update_visibility)
            self.show_boxes[key] = cb
            row.addWidget(cb)
        G.addLayout(row)
        row = QHBoxLayout()
        for text, fn in (("Find marker", self.find_marker), ("Auto ROI + plate", self.auto_shapes),
                         ("Plate = ROI box", self.plate_from_roi)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            row.addWidget(bb)
        G.addLayout(row)
        tip = QLabel("<small>Drag points. ROI: double-click near an edge to add a point, right-click a point to "
                     "remove it. Wheel: zoom; drag the background: move.</small>")
        tip.setWordWrap(True)
        G.addWidget(tip)
        L.addWidget(g)

        g = QGroupBox("Scale and perspective")
        G = QVBoxLayout(g)
        self.mode = QComboBox()
        self.mode.addItems(MODES)
        self.mode.setCurrentIndex(1)
        G.addWidget(self.mode)
        row = QHBoxLayout()
        row.addWidget(QLabel("Plate size (mm)"))
        self.plate_w = QDoubleSpinBox()
        self.plate_h = QDoubleSpinBox()
        for sp in (self.plate_w, self.plate_h):
            sp.setRange(0, 3000)
            sp.setDecimals(1)
            sp.setSpecialValueText("?")
            row.addWidget(sp)
        G.addLayout(row)
        L.addWidget(g)

        g = QGroupBox("Brush: correct the leaves by hand")
        G = QVBoxLayout(g)
        self.brush_mode = QComboBox()
        self.brush_mode.addItems(["Off (edit points)", "Add leaf", "Remove leaf"])
        self.brush_mode.setToolTip("Add leaf: paint leaves the detection misses (e.g. under a light reflex). "
                                   "Remove leaf: paint what is wrongly taken as leaf.")
        self.brush_mode.currentIndexChanged.connect(self.brush_changed)
        G.addWidget(self.brush_mode)
        self.brush_size = SliderRow("Brush size (px)", 2, 200, 20, 1, "{:g}",
                                    "Radius of the brush on the shown photo. Zoom in for fine work.")
        self.brush_size.changed.connect(self.brush_changed)
        G.addWidget(self.brush_size)
        row = QHBoxLayout()
        for text, fn in (("Undo stroke (Ctrl+Z)", self.undo_stroke), ("Clear brush", self.clear_brush)):
            bb = QPushButton(text)
            bb.clicked.connect(fn)
            row.addWidget(bb)
        G.addLayout(row)
        self.brush_lab = QLabel("<small>Left-drag: paint; middle-drag: move; wheel: zoom. Only counts inside the "
                                "ROI. Measure again after painting.</small>")
        self.brush_lab.setWordWrap(True)
        G.addWidget(self.brush_lab)
        L.addWidget(g)
        QShortcut(QKeySequence.Undo, self, activated=self.undo_stroke)

        g = QGroupBox("Leaf detection")
        G = QVBoxLayout(g)
        d = la.Params()
        self.sliders = {}
        for f, lab, lo, hi, st, fmt, tip_ in SLIDERS:
            s = SliderRow(lab, lo, hi, getattr(d, f), st, fmt, tip_)
            self.sliders[f] = s
            G.addWidget(s)
        bd = QPushButton("Default settings")
        bd.clicked.connect(self.default_params)
        G.addWidget(bd)
        L.addWidget(g)

        row = QHBoxLayout()
        self.measure_btn = QPushButton("Measure")
        self.measure_btn.setStyleSheet("font-weight: bold; padding: 6px;")
        self.measure_btn.clicked.connect(self.measure)
        self.save_btn = QPushButton("Save")
        self.save_btn.setStyleSheet("padding: 6px;")
        self.save_btn.clicked.connect(self.save)
        self.save_btn.setEnabled(False)
        row.addWidget(self.measure_btn)
        row.addWidget(self.save_btn)
        L.addLayout(row)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        L.addWidget(self.status)
        self.result_lab = QLabel("")
        self.result_lab.setTextFormat(Qt.RichText)
        self.result_lab.setWordWrap(True)
        L.addWidget(self.result_lab)

        g = QGroupBox("Measured photos")
        G = QVBoxLayout(g)
        hint = QLabel("<small>Every saved photo. Edit <b>group</b> to put photos together (P1 with P1 …); "
                      "double-click a photo to open it again.</small>")
        hint.setWordWrap(True)
        G.addWidget(hint)
        self.measured_tab = QTableWidget(0, 4)
        self.measured_tab.setHorizontalHeaderLabels(["group", "photo", "area mm²", "perspective"])
        self.measured_tab.verticalHeader().setVisible(False)
        self.measured_tab.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.measured_tab.horizontalHeader().setStretchLastSection(True)
        self.measured_tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.measured_tab.setEditTriggers(QAbstractItemView.DoubleClicked | QAbstractItemView.EditKeyPressed
                                          | QAbstractItemView.AnyKeyPressed)
        self.measured_tab.setMinimumHeight(200)
        self.measured_tab.itemChanged.connect(self.group_edited)
        self.measured_tab.cellDoubleClicked.connect(self.open_measured)
        G.addWidget(self.measured_tab)
        self.groups_tab = QTableWidget(0, 3)
        self.groups_tab.setHorizontalHeaderLabels(["plant", "photos", "real_leaf_area_mm2"])
        self.groups_tab.verticalHeader().setVisible(False)
        self.groups_tab.horizontalHeader().setSectionResizeMode(QHeaderView.Stretch)
        self.groups_tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.groups_tab.setMinimumHeight(140)
        G.addWidget(self.groups_tab)
        row = QHBoxLayout()
        row.addWidget(QLabel("File"))
        self.totals_name = QLineEdit("real_leaf_area_mm2")
        row.addWidget(self.totals_name, 1)
        row.addWidget(QLabel(".csv"))
        G.addLayout(row)
        bt = QPushButton("Save plant totals")
        bt.clicked.connect(self.save_totals)
        G.addWidget(bt)
        bf = QPushButton("Start fresh…")
        bf.setToolTip("Move every saved measurement to archive/ and start measuring from nothing.")
        bf.clicked.connect(self.start_fresh)
        G.addWidget(bf)
        self.totals_lab = QLabel("")
        self.totals_lab.setWordWrap(True)
        self.totals_lab.setTextInteractionFlags(Qt.TextSelectableByMouse)
        G.addWidget(self.totals_lab)
        L.addWidget(g)
        L.addStretch(1)
        scroll = QScrollArea()
        scroll.setWidget(left)
        scroll.setWidgetResizable(True)
        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)
        scroll.setMinimumWidth(430)
        scroll.setMaximumWidth(520)

        self.view = PhotoView()
        self.view.stroke_done.connect(self.strokes_changed)
        self.straight = ImageView("Measure to see the straightened photo.")
        self.tabs = QTabWidget()
        self.tabs.addTab(self.view, "Photo (edit here)")
        self.tabs.addTab(self.straight, "Straightened result")
        legend = QLabel("<span style='color:#16a34a'>■</span> leaf &nbsp; <span style='color:#d946ef'>■</span> "
                        "left out as shadow &nbsp; <span style='color:#1e40af'>■</span> not counted &nbsp; "
                        "<span style='color:#facc15'>■</span> brushed leaf &nbsp; "
                        "<span style='color:#f97316'>■</span> brushed not leaf &nbsp; "
                        "<span style='color:#22c55e'>▢</span> ROI &nbsp; "
                        "<span style='color:#06b6d4'>▢</span> plate &nbsp; <span style='color:#ef4444'>▢</span> "
                        "marker")
        right = QWidget()
        R = QVBoxLayout(right)
        R.addWidget(self.tabs, 1)
        R.addWidget(legend)

        sp = QSplitter()
        sp.addWidget(scroll)
        sp.addWidget(right)
        sp.setStretchFactor(1, 1)
        self.setCentralWidget(sp)
        self.resize(1600, 1000)
        self.refresh_measured()
        if folder:
            self.set_folder(Path(folder))

    # ---- folder and photos
    def browse(self):
        start = self.settings.value("last_dir", str(Path.home()))
        p = QFileDialog.getExistingDirectory(self, "Folder with the leaf photos of one plant", start)
        if p:
            self.set_folder(Path(p))

    def set_folder(self, p):
        photos = sorted(q for q in p.iterdir() if q.suffix.lower() in la.IMG_EXT)
        if not photos:
            self.status.setText(f"<span style='color:#c00'>No photos in {p}</span>")
            return
        self.folder = p
        self.settings.setValue("last_dir", str(p.parent))
        self.folder_lab.setText(f"<b>{p.name}</b> · results in results/{p.name}/<br><small>{p}</small>")
        self.list.clear()
        for q in photos:
            it = QListWidgetItem(q.name)
            it.setData(Qt.UserRole, str(q))
            self.list.addItem(it)
        self.refresh_list()
        self.list.setCurrentRow(0)

    def out_dir(self):
        return la.RESULTS / self.folder.name

    def refresh_list(self):
        total = 0.0
        for i in range(self.list.count()):
            it = self.list.item(i)
            q = Path(it.data(Qt.UserRole))
            js = self.out_dir() / f"{q.stem}.json"
            if js.exists():
                a = json.loads(js.read_text()).get("area_mm2")
                total += a or 0
                it.setText(f"{q.name}   ✓ {a:,.0f} mm²" if a else q.name)
            else:
                it.setText(q.name)
        self.folder_lab.setToolTip(f"saved total {total:,.0f} mm²")

    def photo_clicked(self, cur, _prev=None):
        if cur is None:
            return
        if self.busy():                         # opened as soon as the running job is done
            self.pending = Path(cur.data(Qt.UserRole))
            return
        self.load_photo(Path(cur.data(Qt.UserRole)))

    def job_done(self):
        self.measure_btn.setEnabled(True)
        if self.pending is not None:
            p, self.pending = self.pending, None
            self.load_photo(p)

    def load_photo(self, p):
        self.photo = p
        self.img = cv2.imread(str(p))                      # EXIF orientation applied
        h, w = self.img.shape[:2]
        self.ds = min(1.0, DISPLAY_MAX / max(h, w))
        small = cv2.resize(self.img, None, fx=self.ds, fy=self.ds, interpolation=cv2.INTER_AREA)
        self.view.photo.setPixmap(bgr_pixmap(small))
        self.view.result.setPixmap(QPixmap())
        self.view.scene().setSceneRect(0, 0, small.shape[1], small.shape[0])
        self.result = None
        self.save_btn.setEnabled(False)
        self.result_lab.setText("")
        self.straight._pm = None
        self.straight.clear()
        self.straight.setText("Measure to see the straightened photo.")
        self.view.clear_strokes()
        js = self.out_dir() / f"{p.stem}.json"
        if js.exists():
            d = json.loads(js.read_text())
            self.set_shapes(d)
            self.view.set_strokes(d.get("brush"), self.ds)
            for k, v in d.get("params", {}).items():
                if k in self.sliders:
                    self.sliders[k].set(v)
            if d.get("mode") in MODES:
                self.mode.setCurrentText(d["mode"])
            pm = d.get("plate_mm") or [0, 0]
            self.plate_w.setValue(pm[0])
            self.plate_h.setValue(pm[1])
            self.status.setText(f"Loaded the saved points and settings of {p.name}.")
        else:
            self.status.setText("Finding the marker and the paper…")
            self.start(auto_shapes, self.shapes_found, self.img)
        self.view.fit()

    # ---- shapes
    def set_shapes(self, d):
        for key, shape in (("roi", self.view.roi), ("plate", self.view.plate), ("marker", self.view.marker)):
            if d.get(key) is not None:
                shape.set_points(np.asarray(d[key], np.float32) * self.ds)
        self.update_visibility()

    def shapes_found(self, d):
        self.set_shapes(d)
        self.status.setText("Marker found; the ROI is the paper outline, the plate its box. Adjust them, then "
                            "Measure.")

    def get_shape(self, shape):
        p = shape.points()
        return None if len(p) == 0 else p / self.ds

    def find_marker(self):
        if self.img is None:
            return
        try:
            self.view.marker.set_points(la.order_corners(la.find_marker(self.img)) * self.ds)
            self.status.setText("Marker found.")
        except RuntimeError as e:
            self.status.setText(f"<span style='color:#c00'>{e}: place the 4 red points by hand.</span>")
            h, w = self.img.shape[:2]
            c = np.array([w / 2, h / 2])
            self.view.marker.set_points((c + np.array([[-200, -200], [200, -200], [200, 200], [-200, 200]]))
                                        * self.ds)

    def auto_shapes(self):
        if self.img is not None and not self.busy():
            self.status.setText("Finding the marker and the paper…")
            self.start(auto_shapes, self.shapes_found, self.img)

    def plate_from_roi(self):
        roi = self.view.roi.points()
        if len(roi) >= 3:
            box = la.order_corners(cv2.boxPoints(cv2.minAreaRect(roi.reshape(-1, 1, 2))))
            self.view.plate.set_points(box)

    def update_visibility(self, _=None):
        self.view.roi.set_visible(self.show_boxes["roi"].isChecked())
        self.view.plate.set_visible(self.show_boxes["plate"].isChecked())
        self.view.marker.set_visible(self.show_boxes["marker"].isChecked())
        self.view.result.setVisible(self.show_boxes["result"].isChecked())
        self.view.set_brush_visible(self.show_boxes["brush"].isChecked())

    # ---- brush
    def brush_changed(self, _=None):
        mode = [None, "add", "remove"][self.brush_mode.currentIndex()]
        self.view.set_brush(mode, self.brush_size.value())
        if mode:
            self.show_boxes["brush"].setChecked(True)

    def strokes_changed(self):
        n = len(self.view.strokes)
        self.brush_lab.setText(f"<small>{n} stroke{'' if n == 1 else 's'}. Left-drag: paint; middle-drag: move; "
                               "wheel: zoom. Only counts inside the ROI.</small>")
        if self.result is not None:                     # the shown result no longer matches the strokes
            self.save_btn.setEnabled(False)
            self.status.setText("Brush changed: <b>Measure</b> again, then Save.")

    def undo_stroke(self):
        if self.view.undo_stroke():
            self.strokes_changed()

    def clear_brush(self):
        if self.view.strokes:
            self.view.clear_strokes()
            self.strokes_changed()
    # ---- measuring
    def params(self):
        return la.Params(**{f.name: (self.sliders[f.name].value() if f.name in self.sliders else getattr(la.Params(),
                                                                                                      f.name))
                            for f in fields(la.Params)})

    def default_params(self):
        d = la.Params()
        for k, s in self.sliders.items():
            s.set(getattr(d, k))

    def busy(self):
        return self.worker is not None and self.worker.isRunning()

    def start(self, fn, on_done, *args):
        if self.busy():
            return
        self.measure_btn.setEnabled(False)
        self.worker = Worker(fn, *args)
        self.worker.done.connect(lambda r: (on_done(r), self.job_done()))
        self.worker.failed.connect(lambda msg: (self.error(msg), self.job_done()))
        self.worker.start()

    def error(self, msg):
        self.measure_btn.setEnabled(True)
        self.status.setText(f"<span style='color:#c00'>{msg}</span>")

    def measure(self):
        if self.img is None:
            return
        marker = self.get_shape(self.view.marker)
        if marker is None or len(marker) != 4:
            self.status.setText("<span style='color:#c00'>The marker needs its 4 points (Find marker).</span>")
            return
        mode = self.mode.currentIndex()
        plate = self.get_shape(self.view.plate) if mode > 0 else None
        plate_mm = None
        if mode == 2:
            if self.plate_w.value() <= 0 or self.plate_h.value() <= 0:
                self.status.setText("<span style='color:#c00'>Enter the plate size, or choose another "
                                    "perspective.</span>")
                return
            # width = the plate side closer to horizontal in the photo
            plate_mm = (self.plate_w.value(), self.plate_h.value())
        roi = self.get_shape(self.view.roi)
        self.status.setText("Measuring… (a few seconds)")
        self.start(run_measure, self.measured, self.img, self.params(), marker, plate, plate_mm, roi, self.ds,
                   self.view.strokes_photo(self.ds))

    def measured(self, m):
        self.result = m
        self.save_btn.setEnabled(True)
        self.view.result.setPixmap(rgba_pixmap(m["layer"]))
        self.show_boxes["result"].setChecked(True)
        self.update_visibility()
        self.view.viewport().update()
        self.tabs.setCurrentIndex(0)                    # the result is shown where the points are edited
        self.straight.set_bgr(m["overlay"])
        ck = m["check"]
        lines = [f"<div style='font-size:15pt'><b>{m['area_mm2']:,.0f} mm²</b></div>",
                 f"{m['n_leaves']} pieces · perspective: {m['mode']}",
                 f"<small>one scale from the marker, no perspective: {m['area_one_scale_mm2']:,.0f} mm² "
                 f"({(m['area_one_scale_mm2'] / max(m['area_mm2'], 1) - 1) * 100:+.1f}%)</small>"]
        if m["brush_added_mm2"] or m["brush_removed_mm2"]:
            lines.append(f"<small>brush: +{m['brush_added_mm2']:,.0f} mm² leaf added, "
                         f"−{m['brush_removed_mm2']:,.0f} mm² removed</small>")
        for k, v in ck.items():
            s = " × ".join(f"{x:.1f}" for x in v["sides_mm"])
            a = ", ".join(f"{x:.1f}°" for x in v["angles"])
            lines.append(f"<small>{k} after straightening: sides {s} mm; corners {a}</small>")
        self.result_lab.setText("<br>".join(lines))
        self.status.setText("Measured. Check on the photo: green = leaf, magenta = left out as shadow, blue = "
                            "not counted (outside the paper area). Then Save.")

    def save(self):
        if self.result is None or self.photo is None:
            return
        out = self.out_dir()
        out.mkdir(parents=True, exist_ok=True)
        m = self.result
        pts = lambda s: None if len(s.points()) == 0 else (s.points() / self.ds).round(2).tolist()
        js = out / f"{self.photo.stem}.json"
        old = json.loads(js.read_text()) if js.exists() else {}
        d = dict(photo=self.photo.name, source=str(self.photo), group=old.get("group") or default_group(self.photo),
                 area_mm2=round(m["area_mm2"], 1),
                 area_one_scale_mm2=round(m["area_one_scale_mm2"], 1), pieces=m["n_leaves"],
                 mode=self.mode.currentText(), plate_mm=[self.plate_w.value(), self.plate_h.value()],
                 roi=pts(self.view.roi), plate=pts(self.view.plate), marker=pts(self.view.marker),
                 params=asdict(self.params()), check=m["check"], brush=self.view.strokes_photo(self.ds),
                 brush_added_mm2=round(m["brush_added_mm2"], 1), brush_removed_mm2=round(m["brush_removed_mm2"], 1))
        js.write_text(json.dumps(d, indent=1))
        cv2.imwrite(str(out / f"{self.photo.stem}_overlay.jpg"), la.overlay(m, self.photo.name),
                    [cv2.IMWRITE_JPEG_QUALITY, 88])
        self.write_areas()
        self.refresh_list()
        self.refresh_measured()
        self.status.setText(f"Saved to results/{self.folder.name}/ ({self.photo.stem}.json, _overlay.jpg, "
                            "areas.csv).")

    def write_areas(self):
        out = self.out_dir()
        rows = []
        for js in sorted(out.glob("*.json")):
            d = json.loads(js.read_text())
            rows.append([d["photo"], d["area_mm2"], d["area_one_scale_mm2"], d["pieces"], d["mode"]])
        with open(out / "areas.csv", "w") as fh:
            fh.write("photo,leaf_area_mm2,leaf_area_mm2_one_scale,pieces,perspective\n")
            for r in rows:
                fh.write(",".join(str(x) for x in r) + "\n")
            fh.write(f"TOTAL,{sum(r[1] for r in rows):.1f},{sum(r[2] for r in rows):.1f},"
                     f"{sum(r[3] for r in rows)},\n")

    # ---- measured photos and plant totals
    def measured_files(self):
        out = []
        for js in sorted(la.RESULTS.glob("*/*.json")):
            try:
                d = json.loads(js.read_text())
            except (OSError, ValueError):
                continue
            if "area_mm2" in d:
                d.setdefault("group", default_group(Path(d.get("source", js.parent.name + "/" + d["photo"]))))
                out.append((js, d))
        out.sort(key=lambda t: (natural(t[1]["group"]), natural(t[1]["photo"])))
        return out

    def refresh_measured(self):
        rows = self.measured_files()
        self.measured_tab.blockSignals(True)
        self.measured_tab.setRowCount(len(rows))
        for i, (js, d) in enumerate(rows):
            g = QTableWidgetItem(d["group"])
            g.setData(Qt.UserRole, str(js))
            self.measured_tab.setItem(i, 0, g)
            for j, v in ((1, d["photo"]), (2, f"{d['area_mm2']:,.0f}"), (3, d.get("mode", ""))):
                it = QTableWidgetItem(v)
                it.setFlags(it.flags() & ~Qt.ItemIsEditable)
                if j == 2:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                it.setData(Qt.UserRole, str(js))
                self.measured_tab.setItem(i, j, it)
        self.measured_tab.blockSignals(False)
        groups = {}
        for _, d in rows:
            groups.setdefault(d["group"], []).append(d["area_mm2"])
        self.groups_tab.setRowCount(len(groups))
        for i, (g, a) in enumerate(sorted(groups.items(), key=lambda t: natural(t[0]))):
            for j, v in enumerate((g, str(len(a)), f"{sum(a):,.1f}")):
                it = QTableWidgetItem(v)
                if j:
                    it.setTextAlignment(Qt.AlignRight | Qt.AlignVCenter)
                self.groups_tab.setItem(i, j, it)

    def group_edited(self, item):
        if item.column() != 0:
            return
        js = Path(item.data(Qt.UserRole))
        g = item.text().strip()
        if not g:
            self.refresh_measured()
            return
        d = json.loads(js.read_text())
        d["group"] = g
        js.write_text(json.dumps(d, indent=1))
        self.refresh_measured()

    def open_measured(self, row, col):
        if col == 0:
            return                                      # the group cell is edited, not opened
        js = Path(self.measured_tab.item(row, 0).data(Qt.UserRole))
        d = json.loads(js.read_text())
        src = Path(d["source"]) if d.get("source") else None
        if src is None or not src.exists():
            # saved before the photo's place was recorded: look next to the open / last folder
            bases = ([self.folder.parent] if self.folder else []) + [Path(self.settings.value("last_dir", "."))]
            found = [b / js.parent.name / d["photo"] for b in bases if (b / js.parent.name / d["photo"]).exists()]
            if not found:
                self.status.setText(f"<span style='color:#c00'>Photo {d['photo']} not found: open its folder "
                                    "once with Open folder….</span>")
                return
            src = found[0]
            d["source"] = str(src)
            js.write_text(json.dumps(d, indent=1))
        if self.folder != src.parent:
            self.set_folder(src.parent)
        for i in range(self.list.count()):
            if Path(self.list.item(i).data(Qt.UserRole)) == src:
                self.list.setCurrentRow(i)
                break

    def save_totals(self):
        rows = self.measured_files()
        if not rows:
            self.totals_lab.setText("Nothing measured yet.")
            return
        name = re.sub(r"[^\w.\-]+", "_", self.totals_name.text().strip()).removesuffix(".csv") or "real_leaf_area_mm2"
        groups = {}
        for _, d in rows:
            groups.setdefault(d["group"], []).append(d)
        la.RESULTS.mkdir(exist_ok=True)
        p1, p2 = la.RESULTS / f"{name}.csv", la.RESULTS / f"{name}_photos.csv"
        with open(p1, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["plant", "real_leaf_area_mm2"])
            for g, ds in sorted(groups.items(), key=lambda t: natural(t[0])):
                w.writerow([g, round(sum(d["area_mm2"] for d in ds), 1)])
        with open(p2, "w", newline="") as fh:
            w = csv.writer(fh)
            w.writerow(["plant", "photo", "leaf_area_mm2", "perspective", "source"])
            for g, ds in sorted(groups.items(), key=lambda t: natural(t[0])):
                for d in ds:
                    w.writerow([g, d["photo"], d["area_mm2"], d.get("mode", ""), d.get("source", "")])
        self.totals_lab.setText(f"<small>Saved {len(groups)} plants: results/{p1.name} (plant, "
                                f"real_leaf_area_mm2) and results/{p2.name} (the photos of each).</small>")

    def start_fresh(self):
        """Move everything in results/ (saved points, areas, plant totals) to archive/<date_time>/, so every photo
        starts from its automatic points again. Nothing is deleted."""
        if self.busy():
            return
        items = [p for p in la.RESULTS.iterdir()] if la.RESULTS.exists() else []
        if not items:
            self.status.setText("Nothing saved yet: already fresh.")
            return
        n = len(self.measured_files())
        stamp = datetime.now().strftime("%Y-%m-%d_%H%M%S")
        target = la.HERE / "archive" / stamp
        ans = QMessageBox.question(
            self, "Start fresh",
            f"Move all saved results ({n} measured photo(s) and the plant totals) to archive/{stamp}/ and start "
            "measuring from nothing?\n\nNothing is deleted: the old results stay in the archive folder.")
        if ans != QMessageBox.Yes:
            return
        target.mkdir(parents=True)
        for p in items:
            shutil.move(str(p), str(target / p.name))
        self.refresh_measured()
        self.totals_lab.setText("")
        self.default_params()                           # settings back to their defaults too
        self.mode.setCurrentIndex(1)
        self.plate_w.setValue(0)
        self.plate_h.setValue(0)
        if self.folder is not None:
            self.refresh_list()
        if self.photo is not None:
            self.load_photo(self.photo)                 # its saved points are gone: found automatically again
        self.status.setText(f"Started fresh. The old results are in archive/{stamp}/.")

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
