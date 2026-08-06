from datetime import timedelta

from clock import utcnow
from models import LocalEvent, WeatherSnapshot, cache, db
from services.demand_service import DemandService
from services.weather_service import WeatherService


def sign_in(test_client, email, password):
    return test_client.post(
        "/auth/login",
        data={"email": email, "password": password},
        follow_redirects=False,
    )


def test_demand_insights_page_gracefully_handles_missing_weather_key(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")

    response = admin_client.get("/admin/demand-insights")

    assert response.status_code == 200
    assert b"Demand Insights" in response.data
    assert b"Set OPENWEATHER_API_KEY" in response.data
    assert b"Advisory" in response.data
    assert b'data-toggle-target="#add-local-event-form"' in response.data
    assert b'id="add-local-event-form" class="card hidden"' in response.data


def test_admin_can_add_local_event_for_demand_insights(admin_client):
    sign_in(admin_client, "admin@bakery.com", "Admin@bakery")
    event_date = utcnow().date() + timedelta(days=2)

    response = admin_client.post(
        "/admin/demand-insights/events",
        data={
            "name": "College Fest",
            "event_date": event_date.isoformat(),
            "expected_impact": "high",
            "notes": "Expected evening footfall.",
        },
        follow_redirects=True,
    )

    assert response.status_code == 200
    assert b"College Fest" in response.data
    with admin_client.application.app_context():
        event = LocalEvent.query.filter_by(name="College Fest").first()
        assert event is not None
        assert event.expected_impact == "high"


def test_weather_service_caches_and_stores_daily_snapshots(admin_app, monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            base = int(utcnow().timestamp())
            return {
                "city": {"name": "Coimbatore", "country": "IN"},
                "list": [
                    {
                        "dt": base,
                        "main": {"temp": 36, "humidity": 60},
                        "weather": [{"main": "Clear", "description": "clear sky"}],
                        "pop": 0.1,
                    },
                    {
                        "dt": base + 3 * 60 * 60,
                        "main": {"temp": 38, "humidity": 56},
                        "weather": [{"main": "Clear", "description": "clear sky"}],
                        "pop": 0.0,
                    },
                ],
            }

    calls = {"count": 0}

    def fake_get(*args, **kwargs):
        calls["count"] += 1
        return FakeResponse()

    monkeypatch.setattr("services.weather_service.requests.get", fake_get)
    admin_app.config["OPENWEATHER_API_KEY"] = "test-key"

    with admin_app.app_context():
        cache.delete("weather:openweather:forecast")
        first = WeatherService(admin_app.config).get_forecast()
        second = WeatherService(admin_app.config).get_forecast()

        assert first["status"] == "ok"
        assert second["status"] == "ok"
        assert calls["count"] == 1
        assert WeatherSnapshot.query.count() == 1


def test_demand_service_marks_hot_weather_correlation_insufficient(admin_app):
    with admin_app.app_context():
        payload = DemandService(admin_app.config).dashboard_payload()
        correlation = payload["correlations"]["hot_day_cold_desserts"]

        assert correlation["status"] == "insufficient"
        assert "need at least" in correlation["message"]
        assert payload["narrative"]["source"] == "deterministic"
