import requests

class TextVerifiedProvider:
    def __init__(self, api_key):
        self.api_key = api_key
        self.number = None
        self.otp = None

    def reserve_number(self):
        # Example call to TextVerified API to reserve a number
        response = requests.post(
            'https://api.textverified.com/v1/requests',
            data={"api_key": self.api_key, "service": "gmail"}
        )
        # Example response format from TextVerified API
        data = response.json()
        self.number = data['number']
        print(f"Reserved number: {self.number}")
        return self.number

    def check_sms(self):
        # Call the TextVerified API to get the OTP
        response = requests.get(
            f'https://api.textverified.com/v1/requests/{self.number}',
            params={"api_key": self.api_key}
        )
        data = response.json()
        self.otp = data.get('otp')
        print(f"Received OTP: {self.otp}")
        return self.otp

    def cancel(self):
        # Call the API to cancel the number (if needed)
        self.number = None
        self.otp = None
        print("Number and OTP cancelled.")

    def get_number(self):
        return self.number

    def get_otp(self):
        return self.otp
