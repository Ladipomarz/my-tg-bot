from .mock_provider import MockProvider
from textverified_provider import TextVerifiedProvider
from config import OTP_PROVIDER_MODE

def get_otp_provider(api_key=None):
    if OTP_PROVIDER_MODE == "mock":
        print("Using MockProvider for testing.")
        return MockProvider()
    elif OTP_PROVIDER_MODE == "textverified":
        print("Using TextVerifiedProvider for live mode.")
        return TextVerifiedProvider(api_key)
    else:
        raise ValueError("Invalid OTP_PROVIDER_MODE setting.")
