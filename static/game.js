const canvas = document.getElementById('map')
const ctx = canvas.getContext('2d')
const SIZE = 34, SQRT3 = Math.sqrt(3)
let mode = 'view', paintTerritory = 'A', placePlayer = 0
let pan = {x:0,y:0}, dragging = false, dragStart = null, panStart = null
let selectedHex = null

const TERRAIN_COLORS = {sea:'#3b6fa0',island:'#c9943a',forest:'#1a6b4a',snow:'#7ab0c8',desert:'#c8a96b'}
const TERRITORY_COLORS = {A:'#8b2020',B:'#1a4a8b',C:'#6b1a8b'}
const PLAYER_COLORS = ['#f0d060','#f07060','#60f0a0','#f060c0']

// ── grid setup ──────────────────────────────────
const grid = {}
const RADIUS = 4
const ISLANDS = [
  {q:0,r:0,name:'Alabasta',terrain:'desert'},
  {q:2,r:-1,name:'Drum Island',terrain:'snow'},
  {q:-2,r:1,name:'Loguetown',terrain:'island'},
  {q:1,r:1,name:'Arlong Park',terrain:'forest'},
  {q:-1,r:-1,name:'Whiskey Peak',terrain:'island'},
  {q:3,r:-2,name:'Little Garden',terrain:'forest'},
  {q:-3,r:2,name:'Reverse Mtn',terrain:'island'},
  {q:0,r:2,name:'Baratie',terrain:'island'},
  {q:2,r:1,name:'Cocoyashi',terrain:'forest'},
  {q:-2,r:-1,name:'Twin Capes',terrain:'island'},
]
for (let q = -RADIUS; q <= RADIUS; q++) {
  for (let r = Math.max(-RADIUS,-q-RADIUS); r <= Math.min(RADIUS,-q+RADIUS); r++)
    grid[`${q},${r}`] = {q,r,terrain:'sea',name:null,territory:null,players:[]}
}
ISLANDS.forEach(({q,r,name,terrain}) => {
  if (grid[`${q},${r}`]) Object.assign(grid[`${q},${r}`], {terrain,name})
})

let players = [
  {id:'Luffy',q:0,r:0,color:PLAYER_COLORS[0]},
  {id:'Zoro', q:-2,r:1,color:PLAYER_COLORS[1]},
]

// ── coordinate math ──────────────────────────────
function hexToPixel(q,r) {
  return {x:SIZE*(SQRT3*q+SQRT3/2*r)+pan.x, y:SIZE*(3/2*r)+pan.y}
}
function pixelToHex(px,py) {
  const x=px-pan.x, y=py-pan.y
  const q=(SQRT3/3*x-1/3*y)/SIZE, r=(2/3*y)/SIZE
  const s=-q-r
  let rq=Math.round(q),rr=Math.round(r),rs=Math.round(s)
  const dq=Math.abs(rq-q),dr=Math.abs(rr-r),ds=Math.abs(rs-s)
  if (dq>dr&&dq>ds) rq=-rr-rs; else if (dr>ds) rr=-rq-rs
  return {q:rq,r:rr}
}
function hexCorners(cx,cy) {
  return Array.from({length:6},(_,i) => {
    const a=Math.PI/180*(60*i-30)
    return [cx+SIZE*Math.cos(a), cy+SIZE*Math.sin(a)]
  })
}

// ── draw ─────────────────────────────────────────
function draw() {
  const W = canvas.offsetWidth
  canvas.width = W; canvas.height = 420
  if (pan.x === 0) { pan.x = W/2; pan.y = 210 }
  const dark = matchMedia('(prefers-color-scheme:dark)').matches
  Object.values(grid).forEach(hex => {
    const {x,y} = hexToPixel(hex.q,hex.r)
    const corners = hexCorners(x,y)
    ctx.beginPath()
    ctx.moveTo(corners[0][0],corners[0][1])
    corners.forEach(([px,py]) => ctx.lineTo(px,py))
    ctx.closePath()
    ctx.fillStyle = TERRAIN_COLORS[hex.terrain] || TERRAIN_COLORS.sea
    ctx.fill()
    if (hex.territory) {
      ctx.beginPath()
      ctx.moveTo(corners[0][0],corners[0][1])
      corners.forEach(([px,py]) => ctx.lineTo(px,py))
      ctx.closePath()
      ctx.fillStyle = TERRITORY_COLORS[hex.territory] + '55'
      ctx.fill()
      ctx.strokeStyle = TERRITORY_COLORS[hex.territory]
      ctx.lineWidth = 2
    } else if (selectedHex&&selectedHex.q===hex.q&&selectedHex.r===hex.r) {
      ctx.strokeStyle = '#fff'; ctx.lineWidth = 2
    } else {
      ctx.strokeStyle = 'rgba(0,0,0,0.25)'; ctx.lineWidth = 0.8
    }
    ctx.stroke()
    if (hex.name) {
      ctx.font = 'bold 8px monospace'
      ctx.fillStyle = 'rgba(255,255,255,0.9)'
      ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
      ctx.fillText(hex.name.substring(0,8),x,y)
    }
  })
  players.forEach((p,i) => {
    const {x,y} = hexToPixel(p.q,p.r)
    const oy = i === 0 ? -8 : 8
    ctx.beginPath()
    ctx.arc(x,y+oy,9,0,Math.PI*2)
    ctx.fillStyle = p.color; ctx.fill()
    ctx.strokeStyle = 'rgba(0,0,0,0.5)'; ctx.lineWidth = 1.5; ctx.stroke()
    ctx.font = 'bold 7px monospace'
    ctx.fillStyle = '#000'; ctx.textAlign = 'center'; ctx.textBaseline = 'middle'
    ctx.fillText(p.id[0],x,y+oy)
  })
}

// ── mode / interaction ────────────────────────────
function setMode(m) {
  mode = m
  document.getElementById('info').textContent =
    m==='territory' ? 'Click hexes to paint. Press A/B/C to switch colour.' :
    m==='place'     ? 'Click a hex to move the next player there.' :
    'Click a hex to inspect.'
}
function handleClick(cx,cy) {
  const {q,r} = pixelToHex(cx,cy)
  const hex = grid[`${q},${r}`]
  if (!hex) return
  if (mode==='view') {
    selectedHex = hex
    const pl = players.filter(p=>p.q===q&&p.r===r).map(p=>p.id).join(', ')
    document.getElementById('info').textContent =
      `(${q},${r}) — ${hex.name||'Open sea'} · ${hex.terrain}${hex.territory?' · Territory '+hex.territory:''}${pl?' · '+pl:''}`
  } else if (mode==='territory') {
    hex.territory = hex.territory===paintTerritory ? null : paintTerritory
  } else if (mode==='place') {
    players[placePlayer].q=q; players[placePlayer].r=r
    placePlayer=(placePlayer+1)%players.length
  }
  draw()
}

canvas.addEventListener('mousedown',e=>{dragStart={x:e.offsetX,y:e.offsetY};panStart={...pan};dragging=false})
canvas.addEventListener('mousemove',e=>{
  if(!dragStart)return
  const dx=e.offsetX-dragStart.x,dy=e.offsetY-dragStart.y
  if(Math.abs(dx)>4||Math.abs(dy)>4){dragging=true;pan.x=panStart.x+dx;pan.y=panStart.y+dy;draw()}
})
canvas.addEventListener('mouseup',e=>{if(!dragging)handleClick(e.offsetX,e.offsetY);dragStart=null;dragging=false})
window.addEventListener('keydown',e=>{if(['a','b','c'].includes(e.key.toLowerCase())){paintTerritory=e.key.toUpperCase();draw()}})
window.addEventListener('resize',()=>{pan.x=0;pan.y=0;draw()})

// ── websocket — receives server state updates ─────
function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`)
  const el = document.getElementById('ws-status')
  ws.onopen  = () => { el.textContent = 'WebSocket: connected ✓'; el.className='' }
  ws.onclose = () => { el.textContent = 'WebSocket: reconnecting...'; setTimeout(connect,3000) }
  ws.onerror = () => { el.textContent = 'WebSocket: error'; el.className='error' }
  ws.onmessage = (e) => {
    const state = JSON.parse(e.data)
    // update player positions from server
    if (state.players) {
      state.players.forEach(sp => {
        const p = players.find(p => p.id === sp.id)
        if (p) { p.q = sp.q; p.r = sp.r }
      })
    }
    // update territory from server e.g. {"1,-1":"A","0,2":"B"}
    if (state.territory) {
      Object.entries(state.territory).forEach(([key,val]) => {
        if (grid[key]) grid[key].territory = val
      })
    }
    draw()
  }
}

draw()
connect()
