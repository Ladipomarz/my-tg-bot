from fastapi import FastAPI, Request

app = FastAPI()

@app.post("/webhooks/plisio")
async def plisio_webhook(request: Request):
    payload = await request.json()
    print("✅ PLISIO WEBHOOK RECEIVED:", payload)

    data = payload.get("data") or payload  # some gateways nest it
    order_number = data.get("order_number") or data.get("orderID") or data.get("order_id")
    status = data.get("status")

    telegram_user_id = None
    if isinstance(order_number, str) and order_number.startswith("PLISIO-"):
        parts = order_number.split("-")
        if len(parts) >= 3:
            telegram_user_id = parts[1]

    print("Parsed:", {"order_number": order_number, "status": status, "telegram_user_id": telegram_user_id})

    # TODO next: update Postgres + credit user when status in {"completed", "mismatch"} etc.
    return {"ok": True}

@app.get("/webhooks/plisio")
async def plisio_webhook_get():
    return {"ok": True}
