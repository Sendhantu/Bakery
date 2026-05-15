def validate_password(password, min_length=8):
    password = password or ""
    errors = []
    if len(password) < min_length:
        errors.append(f"Password must be at least {min_length} characters.")
    if not any(ch.isalpha() for ch in password):
        errors.append("Password must include at least one letter.")
    if not any(ch.isdigit() for ch in password):
        errors.append("Password must include at least one number.")
    return errors


def validate_address_payload(payload):
    errors = []
    required_fields = {
        "address_line1": "Address line 1 is required.",
        "city": "City is required.",
        "pincode": "PIN code is required.",
        "phone": "Phone number is required.",
    }
    for field, message in required_fields.items():
        if not (payload.get(field) or "").strip():
            errors.append(message)

    pincode = (payload.get("pincode") or "").strip()
    if pincode and (not pincode.isdigit() or len(pincode) != 6):
        errors.append("PIN code must be a valid 6-digit number.")

    phone = "".join(ch for ch in (payload.get("phone") or "") if ch.isdigit())
    if phone and len(phone) < 10:
        errors.append("Phone number must be at least 10 digits.")

    latitude = payload.get("latitude")
    longitude = payload.get("longitude")
    if (latitude is None) != (longitude is None):
        errors.append("Exact location must include both latitude and longitude.")

    return errors
