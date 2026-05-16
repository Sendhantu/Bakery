import json
from urllib.parse import quote_plus, urlencode
from urllib.request import Request, urlopen

from .formatters import parse_coordinate


def address_query(*parts):
    values = [str(part).strip() for part in parts if str(part or "").strip()]
    return ", ".join(values)


def map_link_url(query="", latitude=None, longitude=None):
    lat = parse_coordinate(latitude, -90, 90)
    lng = parse_coordinate(longitude, -180, 180)
    if lat is not None and lng is not None:
        return (
            "https://www.google.com/maps/search/?api=1&query="
            f"{quote_plus(f'{lat},{lng}')}"
        )

    query = (query or "").strip()
    if not query:
        return "#"
    return f"https://www.google.com/maps/search/?api=1&query={quote_plus(query)}"


def map_embed_url(query="", latitude=None, longitude=None):
    lat = parse_coordinate(latitude, -90, 90)
    lng = parse_coordinate(longitude, -180, 180)
    if lat is not None and lng is not None:
        return f"https://www.google.com/maps?q={lat},{lng}&z=17&output=embed"

    query = (query or "").strip()
    if not query:
        return ""
    return f"https://www.google.com/maps?q={quote_plus(query)}&output=embed"


def reverse_geocode(latitude, longitude, timeout=5):
    lat = parse_coordinate(latitude, -90, 90)
    lng = parse_coordinate(longitude, -180, 180)
    if lat is None or lng is None:
        raise ValueError("Please provide valid latitude and longitude coordinates.")

    params = urlencode(
        {
            "format": "jsonv2",
            "lat": lat,
            "lon": lng,
            "zoom": 18,
            "addressdetails": 1,
        }
    )
    request = Request(
        f"https://nominatim.openstreetmap.org/reverse?{params}",
        headers={
            "Accept": "application/json",
            "User-Agent": "SweetCrumbsBakery/1.0 (+https://sweetcrumbs.local)",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        payload = json.load(response)

    address = payload.get("address") or {}
    line1_parts = [
        address.get("house_number"),
        address.get("road") or address.get("pedestrian") or address.get("street"),
    ]
    line2_parts = [
        address.get("neighbourhood"),
        address.get("suburb"),
        address.get("city_district"),
    ]

    def join_parts(parts):
        return ", ".join(str(part).strip() for part in parts if str(part or "").strip())

    return {
        "latitude": lat,
        "longitude": lng,
        "address_line1": join_parts(line1_parts),
        "address_line2": join_parts(line2_parts),
        "city": (
            address.get("city")
            or address.get("town")
            or address.get("village")
            or address.get("municipality")
            or address.get("county")
            or ""
        ),
        "pincode": (address.get("postcode") or "").replace(" ", ""),
        "display_name": payload.get("display_name") or "",
    }
