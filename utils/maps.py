from urllib.parse import quote_plus

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
