const canvas = document.getElementById('map')
const ctx    = canvas.getContext('2d')
const SQRT3  = Math.sqrt(3)

const COLS = 20   // hexes across — fits viewport width
const ROWS = 50   // hexes tall — controls scroll length

// Grand Line = vertical column band through the middle
const GL_COL_START = 8
const GL_COL_END   = 11

// Red Line = horizontal row band separating Paradise / New World
const RL_ROW = 24

// SIZE is computed from window width so no horizontal scroll ever
let SIZE = 1
function computeSize() {
  // flat-top hex: total width = SIZE * (1.5*(COLS-1) + 2)
  SIZE = Math.floor(window.innerWidth / (1.5 * (COLS - 1) + 2))
}

// ── flat-top hex math ────────────────────────────
// q = column, r = row
// odd columns are offset down by half a hex height
function hexToPixel(q, r) {
  return {
    x: SIZE * (1 + 1.5 * q),
    y: SIZE * SQRT3 * (r + (q % 2 === 1 ? 0.5 : 0)) + SIZE * SQRT3 / 2
  }
}

// flat-top corners: angles 0, 60, 120, 180, 240, 300
function hexCorners(cx, cy) {
  return Array.from({length:6}, (_, i) => {
    const a = (Math.PI / 3) * i
    return [cx + SIZE * Math.cos(a), cy + SIZE * Math.sin(a)]
  })
}

// ── terrain colours ──────────────────────────────
const TERRAIN = {
  sea:       '#1a3f6b',
  deep:      '#0d1f3c',
  grandline: '#162a52',
  island:    '#c9943a',
  forest:    '#2a6b3a',
  snow:      '#8ab8cc',
  desert:    '#c8a44a',
  volcano:   '#8b2a10',
  redline:   '#3a0808',
}
const PLAYER_COLORS = ['#f0d060','#f07060','#60f0a0','#f060c0','#60c0f0']

// ── island definitions (q=col, r=row) ────────────
const ISLANDS = [
  // East Blue (left of GL)
  {q:3,  r:3,  name:'Foosha',      terrain:'island'},
  {q:1,  r:9,  name:'Shells Town', terrain:'island'},
  {q:5,  r:14, name:'Baratie',     terrain:'island'},
  {q:3,  r:19, name:'Arlong Park', terrain:'forest'},
  // West Blue (right of GL)
  {q:15, r:5,  name:'Syrup Village',terrain:'island'},
  {q:17, r:12, name:'Orange Town', terrain:'forest'},
  {q:14, r:18, name:'Loguetown',   terrain:'island'},
  // Grand Line — Paradise (above Red Line)
  {q:9,  r:1,  name:'Reverse Mtn', terrain:'island'},
  {q:8,  r:5,  name:'Whiskey Peak',terrain:'desert'},
  {q:10, r:8,  name:'Little Garden',terrain:'forest'},
  {q:9,  r:12, name:'Drum Island', terrain:'snow'},
  {q:8,  r:16, name:'Alabasta',    terrain:'desert'},
  {q:10, r:20, name:'Jaya',         terrain:'forest'},
  {q:9,  r:23, name:'Skypiea',      terrain:'island'},
  // Grand Line — New World (below Red Line)
  {q:9,  r:27, name:'Fishman Island',terrain:'island'},
  {q:8,  r:31, name:'Punk Hazard', terrain:'volcano'},
  {q:10, r:34, name:'Dressrosa',   terrain:'island'},
  {q:9,  r:37, name:'Zou',          terrain:'forest'},
  {q:8,  r:40, name:'Whole Cake',  terrain:'island'},
  {q:10, r:44, name:'Wano',         terrain:'island'},
  {q:9,  r:48, name:'Laugh Tale',  terrain:'island'},
]

// ── build grid ───────────────────────────────────
const grid = {}
for (let q = 0; q < COLS; q++) {
  for (let r = 0; r < ROWS; r++) {
    let terrain = 'sea'
    if (q < 2 || q > COLS - 3) terrain = 'deep'
    if (q >= GL_COL_START && q <= GL_COL_END) terrain = 'grandline'
    if (r >= RL_ROW && r <= RL_ROW + 1) terrain = 'redline'
    grid[`${q},${r}`] = {q, r, terrain, name:null, territory:null}
  }
}
ISLANDS.forEach(({q,r,name,terrain}) => {
  if (grid[`${q},${r}`]) Object.assign(grid[`${q},${r}`], {name, terrain})
})

let players = []

// ── draw ─────────────────────────────────────────
function draw() {
  computeSize()

  // canvas width = exactly viewport width
  // canvas height = bottom of last hex row
  canvas.width  = window.innerWidth
  const lastEven = hexToPixel(0, ROWS - 1)
  const lastOdd  = hexToPixel(1, ROWS - 1)
  canvas.height = Math.max(lastEven.y, lastOdd.y) + SIZE * SQRT3 / 2

  ctx.fillStyle = '#020a14'
  ctx.fillRect(0, 0, canvas.width, canvas.height)

  Object.values(grid).forEach(hex => {
    const {x, y} = hexToPixel(hex.q, hex.r)
    const corners = hexCorners(x, y)

    ctx.beginPath()
    ctx.moveTo(corners[0][0], corners[0][1])
    corners.forEach(([px, py]) => ctx.lineTo(px, py))
    ctx.closePath()

    if (hex.territory) {
      const tc = {A:'#8b2020',B:'#1a4a8b',C:'#6b1a8b'}[hex.territory]
      ctx.fillStyle = tc
      ctx.fill()
      ctx.beginPath()
      ctx.moveTo(corners[0][0], corners[0][1])
      corners.forEach(([px, py]) => ctx.lineTo(px, py))
      ctx.closePath()
      ctx.fillStyle = (TERRAIN[hex.terrain] || TERRAIN.sea) + 'bb'
    } else {
      ctx.fillStyle = TERRAIN[hex.terrain] || TERRAIN.sea
    }
    ctx.fill()

    ctx.strokeStyle = 'rgba(255,255,255,0.05)'
    ctx.lineWidth   = 0.8
    ctx.stroke()

    if (hex.name) {
      const fs = Math.max(8, Math.round(SIZE * 0.24))
      ctx.font         = `bold ${fs}px monospace`
      ctx.fillStyle    = 'rgba(255,255,255,0.9)'
      ctx.textAlign    = 'center'
      ctx.textBaseline = 'middle'
      const words = hex.name.split(' ')
      if (words.length > 1) {
        const mid = Math.ceil(words.length / 2)
        ctx.fillText(words.slice(0, mid).join(' '), x, y - fs * 0.65)
        ctx.fillText(words.slice(mid).join(' '),    x, y + fs * 0.65)
      } else {
        ctx.fillText(hex.name, x, y)
      }
    }
  })

  // player tokens
  players.forEach((p, i) => {
    const {x, y} = hexToPixel(p.q, p.r)
    ctx.beginPath()
    ctx.arc(x, y, SIZE * 0.3, 0, Math.PI * 2)
    ctx.fillStyle   = PLAYER_COLORS[i % PLAYER_COLORS.length]
    ctx.fill()
    ctx.strokeStyle = 'rgba(0,0,0,0.6)'
    ctx.lineWidth   = 2
    ctx.stroke()
    const fs = Math.max(8, Math.round(SIZE * 0.22))
    ctx.font         = `bold ${fs}px monospace`
    ctx.fillStyle    = '#000'
    ctx.textAlign    = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(p.id[0], x, y)
  })
}

// ── websocket ────────────────────────────────────
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`)
  ws.onmessage = (e) => {
    const state = JSON.parse(e.data)
    if (state.players) players = state.players
    if (state.territory) {
      Object.entries(state.territory).forEach(([key, val]) => {
        if (grid[key]) grid[key].territory = val
      })
    }
    draw()
  }
  ws.onclose = () => setTimeout(connect, 3000)
}

window.addEventListener('resize', draw)
draw()
connect()
