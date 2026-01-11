import os
from handlers.textverified_provider import TextVerifiedProvider

def get_otp_provider(api_key=None):
    # Read OTP_PROVIDER_MODE directly from environment variables
    otp_provider_mode = os.getenv("OTP_PROVIDER_MODE")

    print(f"OTP_PROVIDER_MODE from environment: {otp_provider_mode}")  # Debugging line

    if otp_provider_mode == "textverified":
        print("Using TextVerifiedProvider for live mode.")  # Debugging line
        return TextVerifiedProvider(api_key)
    else:
        raise ValueError("Invalid OTP_PROVIDER_MODE setting.")
