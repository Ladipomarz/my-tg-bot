from fastapi import FastAPI, Request

app = FastAPI()

@app.get("/")
async def root():
    return {"status": "ok"}

@app.post("/webhooks/plisio")
async def plisio_webhook(request: Request):
    payload = await request.json()
    print("✅ PLISIO WEBHOOK RECEIVED:", payload)
    return {"ok": True}

@app.get("/webhooks/plisio")
async def plisio_webhook_get():
    return {"ok": True}
