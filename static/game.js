function connect() {
  const ws = new WebSocket(`ws://${location.host}/ws`)
  const dot    = document.getElementById('dot')
  const status = document.getElementById('status')
  const ping   = document.getElementById('ping')

  ws.onopen = () => {
    dot.className = 'dot connected'
    status.textContent = 'WebSocket connected ✓'
  }

  ws.onmessage = (e) => {
    const data = JSON.parse(e.data)
    ping.textContent = `ping #${data.ping}`
  }

  ws.onerror = () => {
    dot.className = 'dot error'
    status.textContent = 'WebSocket error — check port 8000 is open'
  }

  ws.onclose = () => {
    dot.className = 'dot'
    status.textContent = 'Disconnected — retrying...'
    setTimeout(connect, 3000)
  }
}

connect()
