const canvas = document.getElementById('map')
const ctx    = canvas.getContext('2d')

const SIZE  = 38          // hex radius in px — increase to zoom in
const COLS  = 28          // hexes across
const ROWS  = 36          // hexes tall — controls scroll length
const GL_ROW = 17         // row where Grand Line runs through
const SQRT3 = Math.sqrt(3)
const PAD   = SIZE * 2    // canvas padding so edge hexes don't clip

// ── colour palette ───────────────────────────────
const TERRAIN = {
  sea:        '#1a3f6b',
  deep:       '#0f2545',
  grandline:  '#1a2f5a',   // the GL band — slightly different tint
  island:     '#c9943a',
  forest:     '#2a6b3a',
  snow:       '#8ab8cc',
  desert:     '#c8a44a',
  volcano:    '#8b2a10',
  redline:    '#5a0a0a',   // the Red Line barrier
}
const PLAYER_COLORS = ['#f0d060','#f07060','#60f0a0','#f060c0','#60c0f0']

// ── island definitions ───────────────────────────
// q = column (0..COLS-1), r = row (0..ROWS-1)
const ISLAND_DATA = [
  // East Blue / before Grand Line
  {q:3, r:6,  name:'Foosha Village', terrain:'island'},
  {q:8, r:4,  name:'Shells Town',    terrain:'island'},
  {q:14,r:7,  name:'Orange Town',    terrain:'forest'},
  {q:20,r:5,  name:'Syrup Village',  terrain:'island'},
  {q:5, r:12, name:'Baratie',        terrain:'sea'},
  {q:11,r:10, name:'Arlong Park',    terrain:'forest'},
  {q:24,r:9,  name:'Loguetown',      terrain:'island'},
  // Grand Line
  {q:2, r:17, name:'Reverse Mtn',    terrain:'island'},
  {q:6, r:16, name:'Whiskey Peak',   terrain:'desert'},
  {q:9, r:18, name:'Little Garden',  terrain:'forest'},
  {q:13,r:16, name:'Drum Island',    terrain:'snow'},
  {q:17,r:17, name:'Alabasta',       terrain:'desert'},
  {q:21,r:16, name:'Jaya',           terrain:'forest'},
  {q:25,r:17, name:'Skypiea',        terrain:'island'},
  // New World
  {q:3, r:25, name:'Fishman Island', terrain:'island'},
  {q:7, r:27, name:'Punk Hazard',    terrain:'volcano'},
  {q:12,r:25, name:'Dressrosa',      terrain:'island'},
  {q:16,r:28, name:'Zou',            terrain:'forest'},
  {q:20,r:26, name:'Whole Cake',     terrain:'island'},
  {q:24,r:29, name:'Wano',           terrain:'island'},
  {q:14,r:33, name:'Laugh Tale',     terrain:'island'},
]

// ── build grid ───────────────────────────────────
const grid = {}
for (let r = 0; r < ROWS; r++) {
  for (let q = 0; q < COLS; q++) {
    let terrain = 'sea'
    if (r < 5 || r > ROWS-5) terrain = 'deep'
    if (r >= GL_ROW-1 && r <= GL_ROW+1) terrain = 'grandline'
    grid[`${q},${r}`] = {q, r, terrain, name:null, territory:null, players:[]}
  }
}
// Red Line — vertical barrier near col 14
for (let r = 0; r < ROWS; r++) {
  [13,14].forEach(q => { if(grid[`${q},${r}`]) grid[`${q},${r}`].terrain = 'redline' })
}
ISLAND_DATA.forEach(({q,r,name,terrain}) => {
  if (grid[`${q},${r}`]) Object.assign(grid[`${q},${r}`], {name, terrain})
})

let players = []   // populated by WebSocket

// ── coordinate math ──────────────────────────────
function hexToPixel(q, r) {
  return {
    x: PAD + SIZE * (SQRT3 * q + SQRT3/2 * r),
    y: PAD + SIZE * (3/2 * r)
  }
}
function hexCorners(cx, cy) {
  return Array.from({length:6}, (_, i) => {
    const a = Math.PI / 180 * (60 * i - 30)
    return [cx + SIZE * Math.cos(a), cy + SIZE * Math.sin(a)]
  })
}

// ── draw ─────────────────────────────────────────
function draw() {
  // size canvas to fit full grid
  const lastPx = hexToPixel(COLS-1, ROWS-1)
  canvas.width  = lastPx.x + PAD + SIZE
  canvas.height = lastPx.y + PAD + SIZE

  ctx.fillStyle = '#020a14'
  ctx.fillRect(0,0,canvas.width,canvas.height)

  Object.values(grid).forEach(hex => {
    const {x, y} = hexToPixel(hex.q, hex.r)
    const corners = hexCorners(x, y)
    ctx.beginPath()
    ctx.moveTo(corners[0][0], corners[0][1])
    corners.forEach(([px,py]) => ctx.lineTo(px,py))
    ctx.closePath()

    // territory tint underneath terrain
    if (hex.territory) {
      const tColors = {A:'#8b2020',B:'#1a4a8b',C:'#6b1a8b'}
      ctx.fillStyle = tColors[hex.territory] || '#333'
      ctx.fill()
      ctx.beginPath()
      ctx.moveTo(corners[0][0], corners[0][1])
      corners.forEach(([px,py]) => ctx.lineTo(px,py))
      ctx.closePath()
      ctx.fillStyle = (TERRAIN[hex.terrain] || TERRAIN.sea) + 'cc'
    } else {
      ctx.fillStyle = TERRAIN[hex.terrain] || TERRAIN.sea
    }
    ctx.fill()

    ctx.strokeStyle = 'rgba(255,255,255,0.06)'
    ctx.lineWidth   = 0.8
    ctx.stroke()

    // island name label
    if (hex.name) {
      ctx.font        = `bold ${Math.round(SIZE*0.22)}px monospace`
      ctx.fillStyle   = 'rgba(255,255,255,0.85)'
      ctx.textAlign   = 'center'
      ctx.textBaseline = 'middle'
      // split long names onto two lines
      const words = hex.name.split(' ')
      if (words.length > 1) {
        ctx.fillText(words.slice(0,Math.ceil(words.length/2)).join(' '), x, y-SIZE*0.14)
        ctx.fillText(words.slice(Math.ceil(words.length/2)).join(' '), x, y+SIZE*0.16)
      } else {
        ctx.fillText(hex.name, x, y)
      }
    }
  })

  // player tokens
  players.forEach((p, i) => {
    const {x, y} = hexToPixel(p.q, p.r)
    ctx.beginPath()
    ctx.arc(x, y, SIZE * 0.28, 0, Math.PI*2)
    ctx.fillStyle   = PLAYER_COLORS[i % PLAYER_COLORS.length]
    ctx.fill()
    ctx.strokeStyle = 'rgba(0,0,0,0.6)'
    ctx.lineWidth   = 2
    ctx.stroke()
    ctx.font        = `bold ${Math.round(SIZE*0.22)}px monospace`
    ctx.fillStyle   = '#000'
    ctx.textAlign   = 'center'
    ctx.textBaseline = 'middle'
    ctx.fillText(p.id[0], x, y)
  })
}

// ── websocket — receives updates from server ──────
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`)
  ws.onmessage = (e) => {
    const state = JSON.parse(e.data)
    if (state.players) players = state.players
    if (state.territory) {
      Object.entries(state.territory).forEach(([key,val]) => {
        if (grid[key]) grid[key].territory = val
      })
    }
    draw()
  }
  ws.onclose = () => setTimeout(connect, 3000)
}

draw()
connect()
