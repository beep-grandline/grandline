import asyncio, uvicorn, os, json
from fastapi import FastAPI, WebSocket, UploadFile, File
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv
from bot import bot
import cairosvg

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

@app.post("/snapshot")
async def snapshot(image: UploadFile = File(...)):
    svg_data = await image.read()
    print("received svg:", svg_data[:500])  # print first 500 chars
    png_data = cairosvg.svg2png(bytestring=svg_data)
    print("successfully updated map")
    with open("snapshot.png", "wb") as f:
        f.write(png_data)
    return {"ok": True}

async def main():
    config = uvicorn.Config(app, host="0.0.0.0", port=8000)
    server = uvicorn.Server(config)
    try:
        await asyncio.gather(
            server.serve(),
            bot.start(os.getenv("DISCORD_TOKEN"))
        )
    except asyncio.CancelledError:
        pass
    finally:
        await bot.close()

if __name__ == "__main__":
    asyncio.run(main())
