# utils/textverified_client.py
from textverified import (
    TextVerified,
    reservations,
    wake_requests,
    sms,
    NumberType,
    ReservationCapability,
    RentalDuration,
)
import os
import logging

logger = logging.getLogger(__name__)

def get_textverified_client():
    """
    Creates and returns the official API client securely.
    Users will never see this logic or any errors it generates.
    """
    API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
    API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
    
    try:
        # Create the client
        client = TextVerified(api_key=API_KEY, api_username=API_USERNAME)
        return client, reservations, wake_requests, sms, NumberType, ReservationCapability, RentalDuration
    except Exception as e:
        # 🚨 WE BLOCK THE API ERROR HERE SO THE USER NEVER SEES IT 🚨
        logger.error(f"Backend Provider Connection Failed: {str(e)}")
        # We raise a generic, safe error that doesn't mention the provider name
        raise Exception("System is currently experiencing high load. Please try again later.")