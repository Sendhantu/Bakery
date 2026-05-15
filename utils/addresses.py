from .formatters import parse_coordinate


def save_address_for_customer(user_id, payload, make_default=False):
    from models import db, SavedAddress

    latitude = parse_coordinate(payload.get("latitude"), -90, 90)
    longitude = parse_coordinate(payload.get("longitude"), -180, 180)

    existing = SavedAddress.query.filter_by(
        user_id=user_id,
        address_line1=payload["address_line1"],
        address_line2=payload["address_line2"],
        city=payload["city"],
        pincode=payload["pincode"],
        phone=payload["phone"],
    ).first()

    if make_default or not SavedAddress.query.filter_by(user_id=user_id).first():
        SavedAddress.query.filter_by(user_id=user_id, is_default=True).update(
            {"is_default": False}
        )
        make_default = True

    if existing:
        existing.label = payload["label"]
        existing.is_default = make_default or existing.is_default
        existing.latitude = latitude
        existing.longitude = longitude
        return existing

    address = SavedAddress(
        user_id=user_id,
        label=payload["label"],
        address_line1=payload["address_line1"],
        address_line2=payload["address_line2"],
        city=payload["city"],
        pincode=payload["pincode"],
        phone=payload["phone"],
        latitude=latitude,
        longitude=longitude,
        is_default=make_default,
    )
    db.session.add(address)
    return address


def get_saved_addresses_for_user(user_id):
    from models import SavedAddress

    return (
        SavedAddress.query.filter_by(user_id=user_id)
        .order_by(
            SavedAddress.is_default.desc(),
            SavedAddress.updated_at.desc(),
            SavedAddress.id.desc(),
        )
        .all()
    )


def get_selected_saved_address(user_id, address_id):
    from models import SavedAddress

    if not address_id:
        return None
    return SavedAddress.query.filter_by(id=address_id, user_id=user_id).first()


def extract_address_payload(form, fallback_address=None, default_phone=""):
    form = form or {}
    payload = {
        "label": (form.get("address_label") or form.get("label") or "").strip()
        or "Saved Address",
        "address_line1": (form.get("address_line1") or "").strip(),
        "address_line2": (form.get("address_line2") or "").strip(),
        "city": (form.get("city") or "").strip(),
        "pincode": (form.get("pincode") or "").strip(),
        "phone": (form.get("phone") or default_phone or "").strip(),
        "latitude": parse_coordinate(form.get("latitude"), -90, 90),
        "longitude": parse_coordinate(form.get("longitude"), -180, 180),
    }

    if fallback_address:
        payload["address_line1"] = payload["address_line1"] or (
            fallback_address.address_line1 or ""
        )
        payload["address_line2"] = payload["address_line2"] or (
            fallback_address.address_line2 or ""
        )
        payload["city"] = payload["city"] or (fallback_address.city or "")
        payload["pincode"] = payload["pincode"] or (fallback_address.pincode or "")
        payload["phone"] = payload["phone"] or (fallback_address.phone or "")
        payload["label"] = payload["label"] or fallback_address.label or "Saved Address"
        payload["latitude"] = (
            payload["latitude"]
            if payload["latitude"] is not None
            else parse_coordinate(getattr(fallback_address, "latitude", None), -90, 90)
        )
        payload["longitude"] = (
            payload["longitude"]
            if payload["longitude"] is not None
            else parse_coordinate(
                getattr(fallback_address, "longitude", None), -180, 180
            )
        )

    return payload
