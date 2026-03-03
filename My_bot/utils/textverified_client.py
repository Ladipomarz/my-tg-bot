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
import asyncio
import logging

logger = logging.getLogger(__name__)

def get_textverified_client():
    API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
    API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
    
    # Create the TextVerified client
    client = TextVerified(api_key=API_KEY, api_username=API_USERNAME)
    
    # Return both the client and other components for convenience
    return client, reservations, wake_requests, sms, NumberType, ReservationCapability, RentalDuration


