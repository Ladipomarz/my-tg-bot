from handlers.textverified_provider import TextVerifiedProvider
from config import OTP_PROVIDER_MODE, API_KEY

def get_otp_provider(api_key=None):
    print(f"OTP_PROVIDER_MODE: {OTP_PROVIDER_MODE}")  # Debugging line
    if OTP_PROVIDER_MODE == "textverified":
        print("Using TextVerifiedProvider for live mode.")  # Debugging line
        return TextVerifiedProvider(api_key)
    else:
        raise ValueError("Invalid OTP_PROVIDER_MODE setting.")
