from fastapi import FastAPI, Request
import os
from textverified import TextVerified

app = FastAPI()

# Get the API Key from environment variables
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")

# Initialize TextVerified client
provider = TextVerified(api_key=API_KEY)

@app.post("/webhook")
async def webhook_listener(request: Request):
    # Receive the webhook data from TextVerified
    payload = await request.json()
    
    # Extract OTP and other relevant information from the payload
    otp = payload.get("otp")
    number = payload.get("number")
    
    if otp:
        # OTP received, handle accordingly
        print(f"OTP received for number {number}: {otp}")
        # Here you can update the user or take any further action you need

    return {"status": "success"}
