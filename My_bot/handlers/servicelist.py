from textverified import TextVerified, NumberType, ReservationType
import os
from telegram import Update
from telegram.ext import CallbackContext
from utils.db import has_services_been_fetched, store_services_in_db, save_service_fetch_status

import logging
logging.basicConfig(level=logging.DEBUG)

# Initialize TextVerified client
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")
provider = TextVerified(api_key=API_KEY, api_username=API_USERNAME)


async def fetch_and_save_services():
    logging.debug("Checking if services have been fetched already...")
    if has_services_been_fetched():
        logging.debug("Service list has already been fetched. Skipping fetch.")
        return  # Skip fetching if services are already saved in DB

    logging.debug("Provider services object members: %s", dir(provider.services))

    try:
        services = provider.services.list(
            number_type=NumberType.MOBILE,
            reservation_type=ReservationType.VERIFICATION
        )
        logging.debug(f"Total services fetched: {len(services)}")
    except Exception as e:
        logging.error(f"Error fetching services: {str(e)}")
        return

    if services:
        for i, service in enumerate(services[:5]):  # Limit to first 5
            logging.debug(f"Processing service {i + 1}: {service.service_name}")

    await store_services_in_db(services)

    save_service_fetch_status()

    logging.debug("Services have been successfully fetched and stored in the database.")
