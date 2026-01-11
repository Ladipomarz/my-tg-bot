import random
import time
from datetime import datetime
from telegram import InlineKeyboardButton, InlineKeyboardMarkup

class MockProvider:
    def __init__(self):
        self.number = None
        self.otp = None

    def reserve_number(self):
        # Simulating reserving a US number
        self.number = "+1 555 123 4567"
        print(f"Reserved number: {self.number}")
        return self.number

    def check_sms(self):
        # Simulating waiting for OTP
        if not self.number:
            raise ValueError("No number reserved yet!")

        # Simulate a 15-second delay (or randomize it)
        time.sleep(random.randint(10, 30))  # Random delay for simulation

        # Generate a fake OTP (you can make it more complex later)
        self.otp = random.randint(100000, 999999)
        print(f"Generated OTP: {self.otp}")
        return self.otp

    def cancel(self):
        # Simulating cancellation of the number
        self.number = None
        self.otp = None
        print("Number and OTP cancelled.")

    def get_number(self):
        # Return the current reserved number
        return self.number

    def get_otp(self):
        # Return the current OTP
        return self.otp

    def simulate_error(self):
        # Simulating a failure case (for testing refunds)
        if random.choice([True, False]):
            print("Simulated failure: no OTP received!")
            return None
        return self.otp
