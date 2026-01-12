import requests
import os

API_KEY = os.getenv("TEXTVERIFIED_API_KEY")  # Ensure API_KEY is set in environment variables
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")  # Ensure API_USERNAME is set in environment variables

# Request to fetch available services
url = "https://www.textverified.com/api/pub/v2/services"
headers = {
    "Authorization": f"Bearer {API_KEY}"
}

response = requests.get(url, headers=headers)

if response.status_code == 200:
    services = response.json()  # This will contain the list of services
    with open("services.txt", "w") as file:
        file.write("Available Services for OTP Verification:\n\n")
        for i, service in enumerate(services, 1):
            file.write(f"{i}. {service['service_name']}\n")
    print("Services saved to 'services.txt'.")
else:
    print("Failed to fetch services. Status code:", response.status_code)
