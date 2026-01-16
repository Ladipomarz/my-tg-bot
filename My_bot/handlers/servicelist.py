import textverified
from textverified import TextVerified, NumberType, ReservationType
import os
from telegram import Update
from telegram.ext import CallbackContext
from utils.db import has_services_been_fetched, store_services_in_db, save_service_fetch_status,get_connection
import requests



# Initialize TextVerified client
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)




def fetch_services():
    url = "https://api.textverified.com/v1/services"
    headers = {
        "Authorization": f"Bearer {API_KEY}",
        "Username": API_USERNAME,
    }
    response = requests.get(url, headers=headers)

    if response.status_code == 200:
        services = response.json()  # Parse the list of services
        return services
    else:
        print("Failed to fetch services:", response.text)
        return []

# Example usage
services = fetch_services()
print(services)


