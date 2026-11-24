"""overlays/index.html: one page to browse the step pictures of every photo (plant -> angle -> step).

The page is static and self-contained: it loads the pictures from the folders next to it, so it can be opened
straight from disk. The table of photos (and their optical mass) is written into the page as JSON.
"""
import html
import json
from pathlib import Path

STEPS = [
    ("1_seed", "Seed", "green and red-brown pixels; the plant blob they form"),
    ("2_pot", "Pot", "pot axis, width, bottom, and the rim line measured from the bottom"),
    ("3_foreground", "Foreground", "everything darker or more colourful than the wall behind it"),
    ("4_objects", "Objects", "background objects (never plant), and the part freed above the rim"),
    ("5_plant", "Plant mask", "the final mask: the seed plus the foreground near it"),
    ("6_density", "Density", "plant share in the kernel window around every pixel"),
    ("7_layers", "Layers", "leaf layers per pixel (Beer-Lambert); their sum is the optical mass"),
]


def write(out_dir, photos, settings):
    """photos: [(plant, angle, photo folder name, optical mass, plant px, pot width)]."""
    res = "full" if settings.scale == 4 else "1/4"
    data = dict(
        steps=[dict(id=i, name=n, about=a) for i, n, a in STEPS],
        photos=[dict(plant=p, angle=a, dir=d, om=round(om), px=px, pot=None if pw != pw else round(pw, 1))
                for p, a, d, om, px, pw in photos],
        settings=dict(kernel=settings.kernel, cap=settings.cap, resolution=res),
    )
    page = PAGE.replace("__DATA__", json.dumps(data).replace("</", "<\\/"))
    page = page.replace("__SETTINGS__", html.escape(
        f"kernel {settings.kernel} px · cap {settings.cap} · {res} resolution"))
    path = Path(out_dir) / "index.html"
    path.write_text(page, encoding="utf-8")
    return path


PAGE = r"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Overlay viewer</title>
<style>
:root {
  --bg: #f6f7f9; --panel: #ffffff; --fg: #1f2937; --muted: #6b7280; --line: #e5e7eb;
  --chip: #eef0f3; --chip-hover: #e2e6eb; --accent: #2f855a; --accent-fg: #ffffff;
}
@media (prefers-color-scheme: dark) {
  :root { --bg: #0f1115; --panel: #171a21; --fg: #e5e7eb; --muted: #9ca3af; --line: #2a2f3a;
          --chip: #222733; --chip-hover: #2c3240; --accent: #48bb78; --accent-fg: #0f1115; }
}
* { box-sizing: border-box; }
body { margin: 0; background: var(--bg); color: var(--fg); font: 14px/1.45 system-ui, -apple-system, sans-serif; }
header { padding: 14px 20px 10px; border-bottom: 1px solid var(--line); background: var(--panel);
         position: sticky; top: 0; z-index: 2; }
h1 { font-size: 17px; margin: 0 0 2px; }
.sub { color: var(--muted); font-size: 12.5px; }
.row { display: flex; gap: 10px; align-items: baseline; margin-top: 10px; }
.label { width: 52px; flex: none; color: var(--muted); font-size: 12px; text-transform: uppercase; letter-spacing: .04em; }
.chips { display: flex; flex-wrap: wrap; gap: 5px; }
button.chip { border: 0; background: var(--chip); color: var(--fg); border-radius: 7px; padding: 4px 9px;
              font: inherit; font-size: 13px; cursor: pointer; font-variant-numeric: tabular-nums; }
button.chip:hover { background: var(--chip-hover); }
button.chip.on { background: var(--accent); color: var(--accent-fg); font-weight: 600; }
button.chip small { opacity: .7; font-size: 11px; margin-left: 4px; }
main { padding: 16px 20px 40px; }
.info { display: flex; flex-wrap: wrap; gap: 6px 22px; margin-bottom: 12px; }
.info b { font-variant-numeric: tabular-nums; }
.info span { color: var(--muted); }
.about { color: var(--muted); margin: -4px 0 12px; }
.big img { display: block; max-width: 100%; max-height: calc(100vh - 260px); margin: 0 auto;
           border-radius: 8px; border: 1px solid var(--line); cursor: zoom-in; }
.big.zoom img { max-height: none; cursor: zoom-out; }
.grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(380px, 1fr)); gap: 14px; }
.card { background: var(--panel); border: 1px solid var(--line); border-radius: 10px; overflow: hidden; cursor: pointer; }
.card:hover { border-color: var(--accent); }
.card img { display: block; width: 100%; height: auto; }
.card div { padding: 7px 10px; font-size: 13px; }
.card div span { color: var(--muted); }
.keys { color: var(--muted); font-size: 12px; margin-top: 8px; }
kbd { background: var(--chip); border-radius: 4px; padding: 0 5px; font: 11px ui-monospace, monospace; }
@media (max-width: 640px) {
  header, main { padding-left: 16px; padding-right: 16px; }
  .grid { grid-template-columns: 1fr; }
  .row { flex-direction: column; gap: 4px; }
}
</style>
</head>
<body>
<header>
  <h1>Overlay viewer</h1>
  <div class="sub">__SETTINGS__</div>
  <div class="row"><div class="label">Plant</div><div class="chips" id="plants"></div></div>
  <div class="row"><div class="label">Angle</div><div class="chips" id="angles"></div></div>
  <div class="row"><div class="label">Step</div><div class="chips" id="steps"></div></div>
</header>
<main>
  <div class="info" id="info"></div>
  <div id="view"></div>
  <div class="keys"><kbd>&larr;</kbd><kbd>&rarr;</kbd> angle &nbsp; <kbd>&uarr;</kbd><kbd>&darr;</kbd> plant &nbsp;
    <kbd>1</kbd>&ndash;<kbd>7</kbd> step &nbsp; <kbd>0</kbd> all steps &nbsp; <kbd>A</kbd> one step at all angles</div>
</main>
<script>
const D = __DATA__;
const plants = [...new Set(D.photos.map(p => p.plant))];
const byPlant = {};
for (const p of D.photos) (byPlant[p.plant] ||= []).push(p);
for (const k in byPlant) byPlant[k].sort((a, b) => a.angle - b.angle);
const mean = k => byPlant[k].reduce((s, p) => s + p.om, 0) / byPlant[k].length;
const fmt = n => Math.round(n).toLocaleString("en-US");

// state: plant, angle index, step ("all" = every step of one photo, "angles" = one step at every angle)
const S = { plant: plants[0], i: 0, step: "all", last: D.steps[4].id };
function readHash() {
  const h = new URLSearchParams(location.hash.slice(1));
  if (byPlant[h.get("plant")]) S.plant = h.get("plant");
  const a = byPlant[S.plant].findIndex(p => String(p.angle) === h.get("angle"));
  if (a >= 0) S.i = a;
  const st = h.get("step");
  if (st === "all" || st === "angles" || D.steps.some(s => s.id === st)) S.step = st;
  if (h.get("last") && D.steps.some(s => s.id === h.get("last"))) S.last = h.get("last");
}
function writeHash() {
  const p = byPlant[S.plant][S.i];
  history.replaceState(null, "", "#" + new URLSearchParams({ plant: S.plant, angle: p.angle, step: S.step, last: S.last }));
}
const src = (p, step) => encodeURIComponent(p.dir) + "/" + step + ".jpg";

function chip(text, on, click, small) {
  const b = document.createElement("button");
  b.className = "chip" + (on ? " on" : "");
  b.textContent = text;
  if (small) { const s = document.createElement("small"); s.textContent = small; b.append(s); }
  b.onclick = click;
  return b;
}

function render() {
  const list = byPlant[S.plant];
  S.i = Math.min(S.i, list.length - 1);
  const p = list[S.i];
  document.getElementById("plants").replaceChildren(...plants.map(k =>
    chip(k, k === S.plant, () => { S.plant = k; render(); })));
  document.getElementById("angles").replaceChildren(...list.map((q, j) =>
    chip(q.angle + "°", j === S.i, () => { S.i = j; if (S.step === "angles") S.step = S.last; render(); })));
  document.getElementById("steps").replaceChildren(
    chip("All steps", S.step === "all", () => { S.step = "all"; render(); }),
    ...D.steps.map((s, j) => chip((j + 1) + ". " + s.name, S.step === s.id, () => { S.step = s.id; S.last = s.id; render(); })),
    chip("All angles: " + D.steps.find(s => s.id === S.last).name, S.step === "angles", () => { S.step = "angles"; render(); }));

  const info = document.getElementById("info");
  const pm = mean(S.plant);
  if (S.step === "angles") {
    info.innerHTML = `<div>${S.plant} <span>· ${list.length} photos</span></div>
      <div><span>mean optical mass</span> <b>${fmt(pm)}</b></div>`;
  } else {
    info.innerHTML = `<div>${p.dir} <span>· ${S.plant} at ${p.angle}°</span></div>
      <div><span>optical mass</span> <b>${fmt(p.om)}</b> <span>(${((p.om / pm - 1) * 100).toFixed(1)}% vs plant mean ${fmt(pm)})</span></div>
      <div><span>plant</span> <b>${fmt(p.px)}</b> <span>px</span></div>
      <div><span>pot width</span> <b>${p.pot === null ? "not found" : p.pot}</b> <span>${p.pot === null ? "" : "px"}</span></div>`;
  }

  const view = document.getElementById("view");
  if (S.step === "all") {
    view.className = "grid";
    view.replaceChildren(...D.steps.map((s, j) => card(src(p, s.id), `${j + 1}. ${s.name}`, s.about,
      () => { S.step = s.id; S.last = s.id; render(); })));
  } else if (S.step === "angles") {
    view.className = "grid";
    const step = D.steps.find(s => s.id === S.last);
    view.replaceChildren(...list.map((q, j) => card(src(q, step.id), `${q.angle}°`, `optical mass ${fmt(q.om)}`,
      () => { S.i = j; S.step = S.last; render(); })));
  } else {
    const s = D.steps.find(s => s.id === S.step);
    view.className = "big";
    const about = document.createElement("div");
    about.className = "about";
    about.textContent = s.about;
    const img = document.createElement("img");
    img.src = src(p, s.id);
    img.alt = `${p.dir} ${s.name}`;
    img.onclick = () => view.classList.toggle("zoom");
    view.replaceChildren(about, img);
    // preload the neighbours, so arrow keys are instant
    for (const q of [list[S.i - 1], list[S.i + 1]]) if (q) new Image().src = src(q, s.id);
  }
  writeHash();
}

function card(url, title, sub, click) {
  const c = document.createElement("div");
  c.className = "card";
  const img = document.createElement("img");
  img.src = url; img.loading = "lazy"; img.alt = title;
  const t = document.createElement("div");
  t.innerHTML = `<b></b> <span></span>`;
  t.querySelector("b").textContent = title;
  t.querySelector("span").textContent = sub;
  c.append(img, t);
  c.onclick = click;
  return c;
}

document.addEventListener("keydown", e => {
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  const list = byPlant[S.plant], pi = plants.indexOf(S.plant);
  if (e.key === "ArrowRight") S.i = (S.i + 1) % list.length;
  else if (e.key === "ArrowLeft") S.i = (S.i - 1 + list.length) % list.length;
  else if (e.key === "ArrowDown") S.plant = plants[(pi + 1) % plants.length];
  else if (e.key === "ArrowUp") S.plant = plants[(pi - 1 + plants.length) % plants.length];
  else if (e.key === "0") S.step = "all";
  else if (e.key === "a" || e.key === "A") S.step = "angles";
  else if (e.key >= "1" && e.key <= String(D.steps.length)) { S.step = D.steps[+e.key - 1].id; S.last = S.step; }
  else return;
  e.preventDefault();
  render();
});

readHash();
render();
</script>
</body>
</html>
"""
