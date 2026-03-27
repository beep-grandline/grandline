const canvas = document.getElementById('map')
const ctx = canvas.getContext('2d')
const infoBox = document.getElementById('tile-info')

const SQRT3 = Math.sqrt(3)

const COLS = 20
const ROWS = 50

const GL_COL_START = 8
const GL_COL_END = 11
const RL_ROW = 24

const PAD_COLS = 3
const PAD_ROWS = 3
const HEX_SCALE = 0.94

const DRAW_Q_MIN = -PAD_COLS
const DRAW_Q_MAX = COLS + PAD_COLS - 1
const DRAW_R_MIN = -PAD_ROWS
const DRAW_R_MAX = ROWS + PAD_ROWS - 1

const TERRAIN = {
  sea: '#1a3f6b',
  deep: '#0d1f3c',
  grandline: '#162a52',
  island: '#c9943a',
  forest: '#2a6b3a',
  snow: '#8ab8cc',
  desert: '#c8a44a',
  volcano: '#8b2a10',
  redline: '#3a0808',
}

const TERRITORY_COLORS = {
  A: '#8b2020',
  B: '#1a4a8b',
  C: '#6b1a8b',
}

const PLAYER_COLORS = ['#f0d060', '#f07060', '#60f0a0', '#f060c0', '#60c0f0']

const ISLANDS = [
  { q: 3, r: 3, name: 'Foosha', terrain: 'island' },
  { q: 1, r: 9, name: 'Shells Town', terrain: 'island' },
  { q: 5, r: 14, name: 'Baratie', terrain: 'island' },
  { q: 3, r: 19, name: 'Arlong Park', terrain: 'forest' },

  { q: 15, r: 5, name: 'Syrup Village', terrain: 'island' },
  { q: 17, r: 12, name: 'Orange Town', terrain: 'forest' },
  { q: 14, r: 18, name: 'Loguetown', terrain: 'island' },

  { q: 9, r: 1, name: 'Reverse MOUNT', terrain: 'island' },
  { q: 8, r: 5, name: 'Whiskey Peak', terrain: 'desert' },
  { q: 10, r: 8, name: 'Little Garden', terrain: 'forest' },
  { q: 9, r: 12, name: 'Drum Island', terrain: 'snow' },
  { q: 8, r: 16, name: 'Alabasta', terrain: 'desert' },
  { q: 10, r: 20, name: 'Jaya', terrain: 'forest' },
  { q: 9, r: 23, name: 'Skypiea', terrain: 'island' },

  { q: 9, r: 27, name: 'Fishman Island', terrain: 'island' },
  { q: 8, r: 31, name: 'Punk Hazard', terrain: 'volcano' },
  { q: 10, r: 34, name: 'Dressrosa', terrain: 'island' },
  { q: 9, r: 37, name: 'Zou', terrain: 'forest' },
  { q: 8, r: 40, name: 'Whole Cake', terrain: 'island' },
  { q: 10, r: 44, name: 'Wano', terrain: 'island' },
  { q: 9, r: 48, name: 'Laugh Tale', terrain: 'island' },
]

let SIZE = 1
let players = []
let hoveredTile = null
let selectedTile = null

const tiles = []
const playableTiles = {}

function key(q, r) {
  return `${q},${r}`
}

function isPlayable(q, r) {
  return q >= 0 && q < COLS && r >= 0 && r < ROWS
}

function baseTerrain(q, r) {
  if (!isPlayable(q, r)) return 'deep'

  let terrain = 'sea'
  if (q < 2 || q > COLS - 3) terrain = 'deep'
  if (q >= GL_COL_START && q <= GL_COL_END) terrain = 'grandline'
  if (r >= RL_ROW && r <= RL_ROW + 1) terrain = 'redline'
  return terrain
}

function buildGrid() {
  for (let q = DRAW_Q_MIN; q <= DRAW_Q_MAX; q++) {
    for (let r = DRAW_R_MIN; r <= DRAW_R_MAX; r++) {
      const tile = {
        q,
        r,
        terrain: baseTerrain(q, r),
        name: null,
        territory: null,
      }

      tiles.push(tile)

      if (isPlayable(q, r)) {
        playableTiles[key(q, r)] = tile
      }
    }
  }

  for (const island of ISLANDS) {
    const tile = playableTiles[key(island.q, island.r)]
    if (tile) {
      tile.name = island.name
      tile.terrain = island.terrain
    }
  }
}

function computeSize() {
  const viewportWidth = document.documentElement.clientWidth
  const totalCols = COLS + PAD_COLS * 2
  SIZE = Math.floor(viewportWidth / (1.5 * (totalCols - 1) + 2))
}

function toCanvas(q, r) {
  const rq = q - DRAW_Q_MIN
  const rr = r - DRAW_R_MIN

  return {
    x: SIZE * (1 + 1.5 * rq),
    y: SIZE * SQRT3 * (rr + (rq % 2 === 1 ? 0.5 : 0)) + SIZE * SQRT3 / 2,
  }
}

function hexPath(cx, cy, scale = HEX_SCALE) {
  const path = new Path2D()
  const radius = SIZE * scale

  for (let i = 0; i < 6; i++) {
    const a = (Math.PI / 3) * i
    const x = cx + radius * Math.cos(a)
    const y = cy + radius * Math.sin(a)
    if (i === 0) path.moveTo(x, y)
    else path.lineTo(x, y)
  }

  path.closePath()
  return path
}

function resizeCanvas() {
  computeSize()

  canvas.width = document.documentElement.clientWidth

  let maxY = 0
  for (let q = DRAW_Q_MIN; q <= DRAW_Q_MAX; q++) {
    const { y } = toCanvas(q, DRAW_R_MAX)
    if (y > maxY) maxY = y
  }
  canvas.height = maxY + SIZE * SQRT3 / 2
}

function drawLabel(tile, x, y) {
  if (!tile.name) return

  const fs = Math.max(8, Math.round(SIZE * 0.24))
  ctx.font = `bold ${fs}px monospace`
  ctx.fillStyle = 'rgba(255,255,255,0.92)'
  ctx.textAlign = 'center'
  ctx.textBaseline = 'middle'

  const words = tile.name.split(' ')
  if (words.length > 1) {
    const mid = Math.ceil(words.length / 2)
    ctx.fillText(words.slice(0, mid).join(' '), x, y - fs * 0.65)
    ctx.fillText(words.slice(mid).join(' '), x, y + fs * 0.65)
  } else {
    ctx.fillText(tile.name, x, y)
  }
}

function drawTile(tile) {
  const { x, y } = toCanvas(tile.q, tile.r)
  const path = hexPath(x, y)

  ctx.fillStyle = TERRAIN[tile.terrain] || TERRAIN.sea
  ctx.fill(path)

  if (tile.territory && TERRITORY_COLORS[tile.territory]) {
    ctx.save()
    ctx.globalAlpha = 0.35
    ctx.fillStyle = TERRITORY_COLORS[tile.territory]
    ctx.fill(path)
    ctx.restore()
  }

  ctx.strokeStyle = 'rgba(255,255,255,0.06)'
  ctx.lineWidth = 0.8
  ctx.stroke(path)

  if (hoveredTile === tile) {
    ctx.strokeStyle = 'rgba(255,255,255,0.85)'
    ctx.lineWidth = 2
    ctx.stroke(path)
  }

  if (selectedTile === tile) {
    ctx.strokeStyle = '#ffd54a'
    ctx.lineWidth = 3
    ctx.stroke(path)
  }

  drawLabel(tile, x, y)
}

function drawPlayers() {
  players.forEach((p, i) => {
    const { x, y } = toCanvas(p.q, p.r)

    ctx.beginPath()
    ctx.arc(x, y, SIZE * 0.28, 0, Math.PI * 2)
    ctx.fillStyle = PLAYER_COLORS[i % PLAYER_COLORS.length]
    ctx.fill()

    ctx.strokeStyle = 'rgba(0,0,0,0.65)'
    ctx.lineWidth = 2
    ctx.stroke()

    const fs = Math.max(8, Math.round(SIZE * 0.22))
    ctx.font = `bold ${fs}px monospace`
    ctx.fillStyle = '#000'
    ctx.textAlign = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText((p.id || '?')[0], x, y)
  })
}

function render() {
  resizeCanvas()

  ctx.fillStyle = '#081626'
  ctx.fillRect(0, 0, canvas.width, canvas.height)

  for (const tile of tiles) drawTile(tile)
  drawPlayers()
}

function findTileAt(mx, my) {
  for (const tile of tiles) {
    const { x, y } = toCanvas(tile.q, tile.r)
    const path = hexPath(x, y)
    if (ctx.isPointInPath(path, mx, my)) return tile
  }
  return null
}

function updateInfoBox(tile) {
  if (!tile) {
    infoBox.hidden = true
    return
  }

  infoBox.hidden = false
  infoBox.innerHTML = `
    <div><strong>${tile.name || 'Open Sea'}</strong></div>
    <div>Terrain: ${tile.terrain}</div>
    <div>Coord: ${tile.q}, ${tile.r}</div>
    <div>Territory: ${tile.territory || '-'}</div>
  `
}

function handlePointerMove(e) {
  const rect = canvas.getBoundingClientRect()
  const mx = e.clientX - rect.left
  const my = e.clientY - rect.top

  const nextHovered = findTileAt(mx, my)
  if (nextHovered !== hoveredTile) {
    hoveredTile = nextHovered
    render()
  }
}

function handleClick() {
  selectedTile = hoveredTile
  updateInfoBox(selectedTile)
  render()
}

function applyState(state) {
  if (Array.isArray(state.players)) {
    players = state.players
  }

  if (state.territory) {
    for (const tile of Object.values(playableTiles)) {
      tile.territory = null
    }

    for (const [k, v] of Object.entries(state.territory)) {
      if (playableTiles[k]) playableTiles[k].territory = v
    }
  }

  render()
}

function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws'
  const ws = new WebSocket(`${proto}://${location.host}/ws`)

  ws.onmessage = (e) => {
    applyState(JSON.parse(e.data))
  }

  ws.onclose = () => {
    setTimeout(connect, 3000)
  }
}

buildGrid()
window.addEventListener('resize', render)
canvas.addEventListener('mousemove', handlePointerMove)
canvas.addEventListener('click', handleClick)

render()
connect()
