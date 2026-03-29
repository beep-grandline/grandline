const svg = document.getElementById("map");
const viewport = document.getElementById("viewport");
const backgroundLayer = document.getElementById("background-layer");
const oceanGridLayer = document.getElementById("ocean-grid-layer");
const landFillLayer = document.getElementById("land-fill-layer");
const landGridLayer = document.getElementById("land-grid-layer");
const outlineLayer = document.getElementById("outline-layer");

const SVG_NS = "http://www.w3.org/2000/svg";
const HEX_SIZE = 26;
const SQRT3 = Math.sqrt(3);

// Rectangle you want to stay on-screen at all times.
const WORLD_BOUNDS = {
  minX: -2400,
  maxX:  2400,
  minY: -1800,
  maxY:  1800,
};

function getMinScale() {
  const worldWidth  = WORLD_BOUNDS.maxX - WORLD_BOUNDS.minX;
  const worldHeight = WORLD_BOUNDS.maxY - WORLD_BOUNDS.minY;

  return Math.max(
    window.innerWidth / worldWidth,
    window.innerHeight / worldHeight
  );
}

const state = {
  x: window.innerWidth / 2,
  y: window.innerHeight / 2,
  scale: 0.65,
  dragging: false,
  lastX: 0,
  lastY: 0,
};

const islands = buildIslands();
const landHexes = Object.values(islands).flat();
const landSet = new Set(landHexes.map(keyFromHex));

buildScene();
applyTransform();
updateLayerVisibility();

window.addEventListener("resize", () => {
  state.scale = Math.max(state.scale, getMinScale());
  clampPan();
  applyTransform();
  updateLayerVisibility();
});

function buildScene() {
  drawBackground();
  drawOceanGrid();
  drawLand();
  drawIslandOutline();
}

function drawBackground() {
  const rect = makeSvg("rect", {
    x: -2400,
    y: -1800,
    width: 4800,
    height: 3600,
    class: "bg-rect",
  });
  backgroundLayer.appendChild(rect);
}

function drawOceanGrid() {
  for (let q = -26; q <= 26; q++) {
    for (let r = -22; r <= 22; r++) {
      if (landSet.has(`${q},${r}`)) continue;

      const { x, y } = axialToPixel(q, r);
      const hex = makePolygon(hexPoints(x, y, HEX_SIZE), "ocean-hex");
      oceanGridLayer.appendChild(hex);
    }
  }
}

function drawLand() {
  for (const hex of landHexes) {
    const { x, y } = axialToPixel(hex.q, hex.r);

    const fill = makePolygon(hexPoints(x, y, HEX_SIZE), "land-hex");
    landFillLayer.appendChild(fill);

    const grid = makePolygon(hexPoints(x, y, HEX_SIZE), "land-grid");
    landGridLayer.appendChild(grid);
  }
}

/*
  Outline fix:

  The neighbor direction order and the polygon edge order are different.

  Neighbor order:
  0 east, 1 northeast, 2 northwest, 3 west, 4 southwest, 5 southeast

  Polygon edge order from hexCornerPoints():
  0 east, 1 southeast, 2 southwest, 3 west, 4 northwest, 5 northeast

  So we remap neighbor-direction index -> polygon-edge index.
*/
function drawIslandOutline() {
  const dirToEdge = [0, 5, 4, 3, 2, 1];

  for (const hex of landHexes) {
    const center = axialToPixel(hex.q, hex.r);
    const corners = hexCornerPoints(center.x, center.y, HEX_SIZE);

    for (let dir = 0; dir < 6; dir++) {
      const neighbor = axialNeighbor(hex.q, hex.r, dir);
      if (landSet.has(keyFromHex(neighbor))) continue;

      const edge = dirToEdge[dir];
      const p1 = corners[edge];
      const p2 = corners[(edge + 1) % 6];

      const line = makeSvg("line", {
        x1: p1.x,
        y1: p1.y,
        x2: p2.x,
        y2: p2.y,
        class: "island-outline",
      });

      outlineLayer.appendChild(line);
    }
  }
}

/*
  This builds a simple hard-coded island shape.

  For now it stays in JS so the project stays easy to read.
  Later, this is the part you'd move into a shared JSON file.
*/
function buildIslands() {
  const islandA = rowsToHexes([
    { r: -3, qs: [0, 1, 2] },
    { r: -2, qs: [-1, 0, 1, 2, 3] },
    { r: -1, qs: [-2, -1, 0, 1, 2, 3] },
    { r:  0, qs: [-2, -1, 0, 1, 2] },
    { r:  1, qs: [-2, -1, 0, 1] },
    { r:  2, qs: [-1, 0, 1] },
  ]);

  const islandB = shiftHexes(rowsToHexes([
    { r: -2, qs: [0, 1] },
    { r: -1, qs: [-1, 0, 1, 2] },
    { r:  0, qs: [-2, -1, 0, 1, 2] },
    { r:  1, qs: [-2, -1, 0, 1] },
    { r:  2, qs: [-1, 0] },
  ]), 11, -4);

  const islandC = shiftHexes(rowsToHexes([
    { r: -2, qs: [0, 1, 2] },
    { r: -1, qs: [-1, 0, 1, 2] },
    { r:  0, qs: [-2, -1, 0, 1, 2] },
    { r:  1, qs: [-2, -1, 0, 1] },
    { r:  2, qs: [-1, 0, 1] },
    { r:  3, qs: [0] },
  ]), -10, 7);

  return {
    islandA,
    islandB,
    islandC,
  };
}

/*
  Turns row-based coordinate input into:
  [{q, r}, {q, r}, ...]
*/
function rowsToHexes(rows) {
  const hexes = [];

  for (const row of rows) {
    for (const q of row.qs) {
      hexes.push({ q, r: row.r });
    }
  }

  return hexes;
}

/*
  Moves an island somewhere else on the map.
  Useful so you can define the shape near (0,0),
  then place it wherever you want.
*/
function shiftHexes(hexes, dq, dr) {
  return hexes.map((hex) => ({
    q: hex.q + dq,
    r: hex.r + dr,
  }));
}

/*
  Very simple pan:
  - hold mouse down
  - move mouse
  - shift the whole SVG group
*/
svg.addEventListener("mousedown", (event) => {
  state.dragging = true;
  state.lastX = event.clientX;
  state.lastY = event.clientY;
  svg.classList.add("dragging");
});

window.addEventListener("mousemove", (event) => {
  if (!state.dragging) return;

  const dx = event.clientX - state.lastX;
  const dy = event.clientY - state.lastY;

  state.x += dx;
  state.y += dy;
  state.lastX = event.clientX;
  state.lastY = event.clientY;
  clampPan();
  applyTransform();
});

window.addEventListener("mouseup", () => {
  state.dragging = false;
  svg.classList.remove("dragging");
});

/*
  Very simple zoom:
  - mouse wheel changes scale
  - we keep it clamped so it can't get too tiny or too huge

  Right now this zooms toward the center of the screen.
  Later, if you want, you can upgrade this to zoom toward the mouse position.
*/
svg.addEventListener("wheel", (event) => {
  event.preventDefault();

  const zoomStep = event.deltaY < 0 ? 1.12 : 0.89;
  const minScale = getMinScale();

  state.scale *= zoomStep;
  state.scale = clamp(state.scale, minScale, 4.5);

  clampPan();
  applyTransform();
  updateLayerVisibility();
}, { passive: false });

function clampPan() {
  const w = window.innerWidth;
  const h = window.innerHeight;
  const s = state.scale;

  state.x = clamp(
    state.x,
    w - WORLD_BOUNDS.maxX * s,
    -WORLD_BOUNDS.minX * s
  );

  state.y = clamp(
    state.y,
    h - WORLD_BOUNDS.maxY * s,
    -WORLD_BOUNDS.minY * s
  );
}

/*
  This is the "layer reveal" part.

  At far zoom:
  - mostly plain ocean
  - plain green island
  - red island border

  At closer zoom:
  - hex grid fades in
*/
function updateLayerVisibility() {
  const gridOpacity = clamp((state.scale - 0.9) / 1.1, 0, 1);
  const oceanOpacity = clamp((state.scale - 1.05) / 1.15, 0, 0.9);

  landGridLayer.style.opacity = gridOpacity;
  oceanGridLayer.style.opacity = oceanOpacity;
}

function applyTransform() {
  viewport.setAttribute("transform", `translate(${state.x} ${state.y}) scale(${state.scale})`);
}

function axialToPixel(q, r) {
  return {
    x: HEX_SIZE * SQRT3 * (q + r / 2),
    y: HEX_SIZE * 1.5 * r,
  };
}

function hexCornerPoints(cx, cy, size) {
  const corners = [];
  for (let i = 0; i < 6; i++) {
    const angle = ((60 * i) - 30) * Math.PI / 180;
    corners.push({
      x: cx + size * Math.cos(angle),
      y: cy + size * Math.sin(angle),
    });
  }
  return corners;
}

function hexPoints(cx, cy, size) {
  return hexCornerPoints(cx, cy, size)
    .map((point) => `${point.x},${point.y}`)
    .join(" ");
}

function axialNeighbor(q, r, side) {
  const directions = [
    { q: 1, r: 0 },
    { q: 1, r: -1 },
    { q: 0, r: -1 },
    { q: -1, r: 0 },
    { q: -1, r: 1 },
    { q: 0, r: 1 },
  ];

  return {
    q: q + directions[side].q,
    r: r + directions[side].r,
  };
}

// function hexDistance(q1, r1, q2, r2) {
//   const s1 = -q1 - r1;
//   const s2 = -q2 - r2;
//   return Math.max(
//     Math.abs(q1 - q2),
//     Math.abs(r1 - r2),
//     Math.abs(s1 - s2)
//   );
// }

function keyFromHex(hex) {
  return `${hex.q},${hex.r}`;
}

function makePolygon(points, className) {
  return makeSvg("polygon", {
    points,
    class: className,
  });
}

function makeSvg(tag, attrs) {
  const el = document.createElementNS(SVG_NS, tag);
  for (const [key, value] of Object.entries(attrs)) {
    el.setAttribute(key, value);
  }
  return el;
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}


async function sendMapSnapshot() {
  const svgEl = document.getElementById("map")
  const rect = svgEl.getBoundingClientRect()
  const w = Math.round(rect.width)
  const h = Math.round(rect.height)

  // fetch your stylesheet and inject it into the SVG
  const cssRes = await fetch("/static/style.css")
  const css = await cssRes.text()

  const svgStr = new XMLSerializer().serializeToString(svgEl)
  // inject a <style> block right after the opening <svg> tag
  const svgWithStyles = svgStr.replace(
    /(<svg[^>]*>)/,
    `$1<style>${css}</style>`
  )

  const encoded = btoa(unescape(encodeURIComponent(svgWithStyles)))
  const dataUrl = `data:image/svg+xml;base64,${encoded}`

  const canvas = document.createElement("canvas")
  canvas.width = w
  canvas.height = h
  const ctx = canvas.getContext("2d")

  const img = new Image()
  img.onload = async () => {
    ctx.fillStyle = "#020a14"
    ctx.fillRect(0, 0, w, h)
    ctx.drawImage(img, 0, 0, w, h)

    canvas.toBlob(async (pngBlob) => {
      const formData = new FormData()
      formData.append("image", pngBlob, "map.png")
      await fetch("/snapshot", { method: "POST", body: formData })
      console.log("snapshot sent")
    }, "image/png")
  }
  img.src = dataUrl
}


setInterval(sendMapSnapshot, 30000);
