from textverified import TextVerified, NumberType, ReservationType, ReservationCapability
import os

# Get API credentials from environment variables
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")

# Initialize TextVerified client
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)

# Function to get available services
async def get_available_services(country="USA"):
    # List available services for the given country and number type
    services = provider.services.list(
        number_type=NumberType.MOBILE,  # You can change to other types like LANDLINE if needed
        reservation_type=ReservationType.VERIFICATION
    )

    # Return available services to be shown to the user
    return services

# Function to reserve a number for OTP
async def reserve_number_for_otp(service_name, country="USA"):
    # Create the verification request with the selected service
    verification = provider.verifications.create(
        service_name=service_name,  # Use the selected service name
        capability=ReservationCapability.SMS
    )
    return verification.number  # Return the reserved phone number
