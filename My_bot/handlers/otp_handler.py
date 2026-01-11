from textverified import TextVerified
import os

# Get API credentials from environment variables
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")

# Initialize TextVerified client
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to reserve a number
async def reserve_number_for_otp(country="USA"):
    number = provider.reserve_number(country=country)  # Reserve the number for the specified country
    return number
