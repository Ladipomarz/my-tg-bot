from fastapi import FastAPI, Request
import os
from textverified import TextVerified

app = FastAPI()

# Get the API Key from environment variables
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")


# Initialize TextVerified client
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to reserve a number
async def reserve_number_for_otp(country="USA"):
    number = provider.reserve_number(country=country)
    return number

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
