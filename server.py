import asyncio, uvicorn, os, json
from fastapi import FastAPI, WebSocket
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from dotenv import load_dotenv

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
            await websocket.send_text(json.dumps({
                "status": "ok",
                "ping": counter
            }))
            await asyncio.sleep(2)
    except:
        pass

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
