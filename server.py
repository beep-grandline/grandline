import asyncio, uvicorn, os, json
from fastapi import FastAPI, WebSocket
import discord

from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

app = FastAPI()           # web server
bot = discord.Client(intents=discord.Intents.default())  # discord bot

# makes static/ available at http://YOUR_IP:8000/static/
app.mount("/static", StaticFiles(directory="static"), name="static")

# serves index.html when someone visits http://YOUR_IP:8000/
@app.get("/")
async def root():
    return FileResponse("static/index.html")

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    await asyncio.gather(
        server.serve(),                          # starts web server
        bot.start(os.getenv("DISCORD_TOKEN"))   # starts discord bot
    )

asyncio.run(main())

@app.websocket("/ws")           # browser connects to ws://YOUR_IP:8000/ws
async def ws_endpoint(websocket: WebSocket):
    await websocket.accept()    # accept the connection
    try:
        while True:              # loop forever while connected
            state = get_game_state()
            await websocket.send_text(json.dumps(state))
            await asyncio.sleep(2)   # push every 2 seconds
    except:
        pass                     # browser disconnected — exit cleanly
