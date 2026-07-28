from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from statistics import mean
from typing import Any, Dict, Iterable, List

import requests
from flask import current_app
from sqlalchemy.exc import SQLAlchemyError

from clock import utcnow
from models import WeatherSnapshot, cache, db


FORECAST_CACHE_KEY = "weather:openweather:forecast"


def _decimal_or_none(value: Any):
    if value is None:
        return None
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return None


class WeatherService:
    """Fetch and cache weather context without making admin page loads API-heavy."""

    def __init__(self, config=None):
        self.config = config or current_app.config

    def get_forecast(self, force_refresh: bool = False) -> Dict[str, Any]:
        if not force_refresh:
            cached = cache.get(FORECAST_CACHE_KEY)
            if cached:
                return cached
        return self.refresh_forecast()

    def refresh_forecast(self) -> Dict[str, Any]:
        api_key = (self.config.get("OPENWEATHER_API_KEY") or "").strip()
        ttl = int(self.config.get("WEATHER_FORECAST_TTL_SECONDS", 21600))
        if not api_key:
            payload = {
                "status": "not_configured",
                "message": "Set OPENWEATHER_API_KEY to enable forecast-based demand insights.",
                "daily": [],
                "location_label": self._location_label(),
                "fetched_at": utcnow().isoformat(),
            }
            cache.set(FORECAST_CACHE_KEY, payload, timeout=ttl)
            return payload

        try:
            response = requests.get(
                self.config.get("WEATHER_API_URL"),
                params=self._request_params(api_key),
                timeout=int(self.config.get("WEATHER_REQUEST_TIMEOUT_SECONDS", 5)),
            )
            response.raise_for_status()
            payload = self._normalize_response(response.json())
            cache.set(FORECAST_CACHE_KEY, payload, timeout=ttl)
            self._store_daily_snapshots(payload.get("daily", []), payload["location_label"])
            return payload
        except Exception as exc:
            current_app.logger.warning("Weather forecast refresh failed: %s", exc)
            cached = cache.get(FORECAST_CACHE_KEY)
            if cached:
                stale_payload = dict(cached)
                stale_payload["status"] = "stale"
                stale_payload["message"] = "Using cached forecast because the weather service is temporarily unavailable."
                return stale_payload
            payload = {
                "status": "unavailable",
                "message": "Weather forecast is temporarily unavailable; insights are based on local events and sales history only.",
                "daily": [],
                "location_label": self._location_label(),
                "fetched_at": utcnow().isoformat(),
            }
            cache.set(FORECAST_CACHE_KEY, payload, timeout=min(ttl, 900))
            return payload

    def _request_params(self, api_key: str) -> Dict[str, Any]:
        params = {
            "appid": api_key,
            "units": "metric",
        }
        lat = (self.config.get("STORE_LATITUDE") or "").strip()
        lon = (self.config.get("STORE_LONGITUDE") or "").strip()
        if lat and lon:
            params.update({"lat": lat, "lon": lon})
            return params

        store = self.config.get("STORE_DETAILS", {})
        city = (store.get("city") or "Coimbatore").strip()
        country = (self.config.get("STORE_COUNTRY_CODE") or "IN").strip()
        params["q"] = f"{city},{country}" if country else city
        return params

    def _location_label(self) -> str:
        lat = (self.config.get("STORE_LATITUDE") or "").strip()
        lon = (self.config.get("STORE_LONGITUDE") or "").strip()
        if lat and lon:
            return f"{lat},{lon}"
        store = self.config.get("STORE_DETAILS", {})
        city = (store.get("city") or "Coimbatore").strip()
        country = (self.config.get("STORE_COUNTRY_CODE") or "IN").strip()
        return f"{city},{country}" if country else city

    def _normalize_response(self, payload: Dict[str, Any]) -> Dict[str, Any]:
        by_day: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
        for item in payload.get("list", []):
            dt_value = item.get("dt")
            if not dt_value:
                continue
            forecast_dt = datetime.fromtimestamp(int(dt_value), tz=timezone.utc)
            by_day[forecast_dt.date()].append(item)

        daily = [self._daily_summary(day, entries) for day, entries in sorted(by_day.items())]
        city = payload.get("city") or {}
        location = city.get("name") or self._location_label()
        if city.get("country"):
            location = f"{location},{city['country']}"

        return {
            "status": "ok",
            "message": "",
            "source": "openweathermap",
            "location_label": location,
            "fetched_at": utcnow().isoformat(),
            "daily": daily[:7],
        }

    def _daily_summary(self, forecast_date, entries: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        rows = list(entries)
        temps = [float(row.get("main", {}).get("temp")) for row in rows if row.get("main", {}).get("temp") is not None]
        humidity = [
            float(row.get("main", {}).get("humidity"))
            for row in rows
            if row.get("main", {}).get("humidity") is not None
        ]
        precipitation = [
            float(row.get("pop"))
            for row in rows
            if row.get("pop") is not None
        ]
        weather = rows[0].get("weather", [{}])[0] if rows else {}
        return {
            "date": forecast_date.isoformat(),
            "temp_min_c": min(temps) if temps else None,
            "temp_max_c": max(temps) if temps else None,
            "humidity_avg": mean(humidity) if humidity else None,
            "precipitation_probability": max(precipitation) if precipitation else None,
            "condition": weather.get("main") or "Unknown",
            "description": weather.get("description") or "",
        }

    def _store_daily_snapshots(self, daily_rows: List[Dict[str, Any]], location_label: str) -> None:
        try:
            for row in daily_rows:
                forecast_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
                snapshot = WeatherSnapshot.query.filter_by(
                    forecast_date=forecast_date,
                    source="openweathermap",
                    location_label=location_label,
                ).first()
                if snapshot is None:
                    snapshot = WeatherSnapshot(
                        forecast_date=forecast_date,
                        source="openweathermap",
                        location_label=location_label,
                    )
                    db.session.add(snapshot)
                snapshot.condition = row.get("condition")
                snapshot.description = row.get("description")
                snapshot.temp_min_c = _decimal_or_none(row.get("temp_min_c"))
                snapshot.temp_max_c = _decimal_or_none(row.get("temp_max_c"))
                snapshot.humidity_avg = _decimal_or_none(row.get("humidity_avg"))
                snapshot.precipitation_probability = _decimal_or_none(
                    row.get("precipitation_probability")
                )
                snapshot.fetched_at = utcnow()
            db.session.commit()
        except SQLAlchemyError:
            db.session.rollback()
            current_app.logger.exception("Unable to store weather snapshots.")
