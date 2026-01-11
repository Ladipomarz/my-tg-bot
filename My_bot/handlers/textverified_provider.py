import requests

class TextVerifiedProvider:
    def __init__(self, api_key):
        self.api_key = api_key
        self.number = None
        self.otp = None

    def reserve_number(self, country="USA"):
        """Reserve a number through TextVerified's API."""
        response = requests.post(
            "https://api.textverified.com/v1/requests",
            data={"api_key": self.api_key, "service": "gmail", "country": country}
        )

        if response.status_code != 200:
            raise ValueError(f"Failed to reserve number: {response.text}")

        data = response.json()
        self.number = data['number']  # Extracting the reserved number
        print(f"Reserved number: {self.number}")
        return self.number

    def check_sms(self):
        """Check for the OTP sent to the reserved number."""
        if not self.number:
            raise ValueError("No number reserved yet!")

        response = requests.get(
            f'https://api.textverified.com/v1/requests/{self.number}',
            params={"api_key": self.api_key}
        )

        if response.status_code != 200:
            raise ValueError(f"Failed to retrieve OTP: {response.text}")

        data = response.json()
        self.otp = data.get('otp')  # Extract OTP from the response
        if self.otp:
            print(f"Received OTP: {self.otp}")
            return self.otp
        else:
            print("OTP not yet received.")
            return None

    def cancel(self):
        """Cancel the reserved number if needed."""
        self.number = None
        self.otp = None
        print("Reservation cancelled.")
