import requests
import os
from textverified import TextVerified

# Get the API key and username from environment variables
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")

# Initialize the TextVerified client
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to fetch available services from TextVerified
def fetch_available_services():
    url = "https://www.textverified.com/api/pub/v2/services"
    headers = {
        "Authorization": f"Bearer {API_KEY}"
    }

    response = requests.get(url, headers=headers)
    if response.status_code == 200:
        services = response.json()  # Get the list of services
        return services
    else:
        print("Failed to fetch services:", response.status_code)
        return []
