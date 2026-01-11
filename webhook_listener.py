from fastapi import FastAPI, Request
import os
from textverified import TextVerified

# Initialize FastAPI app
app = FastAPI()

# Get the API Key and Username from environment variables
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")

# Initialize TextVerified client
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to check for OTP (polling)async def wait_for_otp(verification, timeout=300):
async def wait_for_otp(verification, timeout=300):
    start_time = time.time()
    otp = None

    # Poll for OTP within the specified timeout
    while time.time() - start_time < timeout:
        messages = provider.sms.incoming(verification, timeout=5)  # Polling every 5 seconds
        for message in messages:
            if message.sms_content:
                otp = message.sms_content
                return otp  # Return OTP once received
        await asyncio.sleep(5)  # Wait 5 seconds before checking again

    return None  # Return None if OTP is not received within the timeout period