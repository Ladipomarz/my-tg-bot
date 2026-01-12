import os

# Retrieve environment variables
API_KEY = os.getenv("TEXTVERIFIED_API_KEY")
API_USERNAME = os.getenv("TEXTVERIFIED_API_USERNAME")

# Print the values to check if they are correctly loaded
print(f"API Key: {API_KEY}")
print(f"API Username: {API_USERNAME}")
