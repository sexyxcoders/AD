import random

def generate_otp(phone_number):
    otp = random.randint(1000, 9999)  # Generate a 4-digit OTP
    # Here, you would integrate with an actual OTP service (e.g., Twilio) to send the OTP.
    print(f"OTP for {phone_number}: {otp}")  # For demo purposes, log it
    return otp

def verify_otp(phone_number, entered_otp):
    # In a real-world scenario, you'd validate the OTP against a database or a secure service
    print(f"Verifying OTP {entered_otp} for {phone_number}")
    return True  # Assume OTP is correct for this demo