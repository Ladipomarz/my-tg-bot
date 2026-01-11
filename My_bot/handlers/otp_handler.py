from textverified import TextVerified
from config import API_KEY
import time
import asyncio

# Initialize the TextVerified provider
provider = TextVerified(api_key=API_KEY)

# Function to reserve a number for OTP
async def reserve_number_for_otp(country="USA"):
    number = provider.reserve_number(country=country)  # Reserve the number for the specified country
    return number

# Function to check for OTP (either via polling or webhook)
async def wait_for_otp(timeout=300):
    start_time = time.time()
    otp = None

    # Poll for OTP within the specified timeout
    while time.time() - start_time < timeout:
        otp = provider.check_sms()  # Fetch the OTP from the reserved number
        if otp:
            return otp
        await asyncio.sleep(5)  # Wait 5 seconds before checking again

    return None  # Return None if OTP is not received within the timeout period
