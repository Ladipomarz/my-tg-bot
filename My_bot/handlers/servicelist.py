from textverified import TextVerified, NumberType, ReservationType
import os

# Initialize TextVerified client
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to fetch available services and write them to a text file
async def fetch_and_save_services(country="USA"):
    # List available services for the given country and number type
    services = provider.services.list(
        number_type=NumberType.MOBILE,  # You can change to other types like LANDLINE if needed
        reservation_type=ReservationType.VERIFICATION
    )

    if not services:
        print("No services available.")
        return

    # Write services to a file (services.txt)
    with open("services.txt", "w") as file:
        file.write("Available Services for OTP Verification:\n\n")
        for i, service in enumerate(services[:5], 1):  # Limit to first 5 services
            file.write(f"{i}. {service.service_name}\n")
    
    print("Services saved to 'services.txt'.")
