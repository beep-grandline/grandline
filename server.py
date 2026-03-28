import asyncio, uvicorn, os, json
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from bot import bot

load_dotenv()

app = FastAPI()
app.mount("/static", StaticFiles(directory="static"), name="static")

@app.get("/")
async def root():
    return FileResponse("static/index.html")

@app.websocket("/ws")
async def ws_test(websocket: WebSocket):
    await websocket.accept()
    counter = 0
    try:
        while True:
            counter += 1
            await websocket.send_text(json.dumps({"status": "ok", "ping": counter}))
            await asyncio.sleep(2)
    except:
        pass

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    await asyncio.gather(
        server.serve(),
        bot.start(os.getenv("DISCORD_TOKEN"))
    )

if __name__ == "__main__":
    asyncio.run(main())
