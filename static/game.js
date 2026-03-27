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

const state = {
  x: window.innerWidth / 2,
  y: window.innerHeight / 2,
  scale: 0.65,
  dragging: false,
  lastX: 0,
  lastY: 0,
};

const landHexes = buildIsland();
const landSet = new Set(landHexes.map(keyFromHex));

buildScene();
applyTransform();
updateLayerVisibility();

window.addEventListener("resize", () => {
  if (!state.dragging) {
    state.x = window.innerWidth / 2;
    state.y = window.innerHeight / 2;
  }
  applyTransform();
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
  This creates the red island border.

  Idea:
  - Check all 6 sides of every land hex.
  - If that side does NOT touch another land hex,
    then that side is part of the outer coastline.
  - Draw only those outer edges in red.

  That gives you one outer outline without drawing red lines inside the island.
*/
function drawIslandOutline() {
  for (const hex of landHexes) {
    const center = axialToPixel(hex.q, hex.r);
    const corners = hexCornerPoints(center.x, center.y, HEX_SIZE);

    for (let side = 0; side < 6; side++) {
      const neighbor = axialNeighbor(hex.q, hex.r, side);
      if (landSet.has(keyFromHex(neighbor))) continue;

      const p1 = corners[side];
      const p2 = corners[(side + 1) % 6];
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
function buildIsland() {
  const hexes = [];
  const seen = new Set();

  const blobs = [
    { q: -6, r: -1, radius: 4 },
    { q: 3, r: -3, radius: 5 },
    { q: -1, r: 5, radius: 5 },
  ];

  for (let q = -20; q <= 20; q++) {
    for (let r = -20; r <= 20; r++) {
      const insideBlob = blobs.some((blob) => hexDistance(q, r, blob.q, blob.r) <= blob.radius);
      if (!insideBlob) continue;

      const key = `${q},${r}`;
      if (seen.has(key)) continue;
      seen.add(key);
      hexes.push({ q, r });
    }
  }

  const cutouts = [
    [0, 2], [1, 2], [2, 2], [3, 1], [3, 2], [4, 0], [5, -1],
    [-1, 0], [-2, 0], [-3, 1], [-4, 2], [-5, 2],
    [-8, 4], [-7, 5], [6, -5], [6, -4]
  ];

  const cutSet = new Set(cutouts.map(([q, r]) => `${q},${r}`));
  return hexes.filter((hex) => !cutSet.has(`${hex.q},${hex.r}`));
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
  state.scale *= zoomStep;
  state.scale = clamp(state.scale, 0.35, 4.5);

  applyTransform();
  updateLayerVisibility();
}, { passive: false });

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

function hexDistance(q1, r1, q2, r2) {
  const s1 = -q1 - r1;
  const s2 = -q2 - r2;
  return Math.max(
    Math.abs(q1 - q2),
    Math.abs(r1 - r2),
    Math.abs(s1 - s2)
  );
}

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
