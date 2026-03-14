# utils/textverified_client.py
import os
import logging
from utils.helper import notify_admin_sync
from config import MOCK_MODE

logger = logging.getLogger(__name__)

def get_textverified_client():
    """
    Creates and returns the official API client securely.
    OR returns the Mock Client if testing.
    """
    if MOCK_MODE:
        from utils.mock_client import MockTextVerified, MockReservations, MockWakeRequests, MockSMSIncoming, NumberType, ReservationCapability, RentalDuration
        logger.debug("🧪 MOCK MODE ACTIVE: Returning Fake TextVerified Client. You will not be charged.")
        return MockTextVerified(), MockReservations(), MockWakeRequests(), MockSMSIncoming(), NumberType, ReservationCapability, RentalDuration

    try:
        from textverified import TextVerified, reservations, wake_requests, sms, NumberType, ReservationCapability, RentalDuration
        API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
        API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
        
        # Create the real client
        client = TextVerified(api_key=API_KEY, api_username=API_USERNAME)
        return client, reservations, wake_requests, sms, NumberType, ReservationCapability, RentalDuration
    except Exception as e:
        # 🚨 WE BLOCK THE API ERROR HERE SO THE USER NEVER SEES IT 🚨
        logger.error(f"Backend Provider Connection Failed: {str(e)}")
        notify_admin_sync(f"Backend failed {str(e)}")
        raise Exception("System is currently experiencing high load. Please try again later.")

def get_provider():
    """Returns just the base client needed for otp_handler.py"""
    if MOCK_MODE:
        from utils.mock_client import MockTextVerified
        return MockTextVerified()
        
    from textverified import TextVerified
    API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
    API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
    return TextVerified(api_key=API_KEY, api_username=API_USERNAME)