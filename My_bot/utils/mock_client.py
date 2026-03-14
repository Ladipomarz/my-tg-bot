# utils/mock_client.py
import logging

logger = logging.getLogger(__name__)

class MockObj:
    """A flexible mock object that allows dot notation access."""
    def __init__(self, **kwargs):
        for k, v in kwargs.items():
            setattr(self, k, v)

class MockVerifications:
    def create(self, **kwargs):
        logger.debug("🧪 MOCK API: Generating Fake OTP Reservation")
        return MockObj(id="mock_otp_999", number="+12025550199", phone_number="12025550199", to_value="+12025550199")
    
    def details(self, v_id):
        return MockObj(id=v_id, status="Pending")
        
    def cancel(self, v_id):
        logger.debug(f"🧪 MOCK API: Cancelled {v_id} with no charge.")
        
    def report(self, v_id):
        logger.debug(f"🧪 MOCK API: Reported {v_id} for refund.")

class MockSMSIncoming:
    def incoming(self, ver_obj, **kwargs):
        logger.debug("🧪 MOCK API: Waiting for SMS...")
        def generator():
            yield MockObj(parsed_code="882910", sms_content="Your verification code is 882910", from_value="MockService")
        return generator()
        
    def list(self):
        logger.debug("🧪 MOCK API: Fetching Global Inbox")
        return MockObj(data=[MockObj(parsed_code="123456", sms_content="Code is 123456", created_at="2026-03-14T12:00:00Z")])

class MockServices:
    def area_codes(self):
        return [MockObj(state="california", area_code="213"), MockObj(state="new york", area_code="212")]

class MockReservations:
    def create(self, **kwargs):
        logger.debug("🧪 MOCK API: Generating Fake Rental")
        return MockObj(reservations=[MockObj(id="mock_rent_999")])
        
    def details(self, r_id):
        return MockObj(id=r_id, phone_number="13024079919", status="Active")
        
    def extend_nonrenewable(self, **kwargs):
        logger.debug("🧪 MOCK API: Extending Rental (No Charge)")

class MockWakeRequests:
    def create(self, obj):
        logger.debug("🧪 MOCK API: Fake Wake Request Sent")

class MockTextVerified:
    def __init__(self, *args, **kwargs):
        self.verifications = MockVerifications()
        self.sms = MockSMSIncoming()
        self.services = MockServices()

# Fake Enums to prevent import crashes
class NumberType:
    MOBILE = "mobile"
class ReservationCapability:
    SMS = "sms"
class RentalDuration:
    ONE_DAY = "1_day"
    THIRTY_DAY = "30_days"