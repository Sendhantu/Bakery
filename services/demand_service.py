from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any, Dict, Iterable, List, Optional

import requests
from flask import current_app
from sqlalchemy import func, or_

from clock import utcnow
from models import (
    Category,
    LocalEvent,
    Order,
    OrderItem,
    Product,
    ProductMaterial,
    RawMaterial,
    WeatherSnapshot,
    db,
)
from services.analytics_service import REVENUE_ORDER_STATUSES, REVENUE_PAYMENT_STATUSES
from services.weather_service import WeatherService


COLD_DESSERT_KEYWORDS = (
    "ice",
    "cold",
    "chill",
    "shake",
    "smoothie",
    "mousse",
    "cream",
    "pudding",
    "custard",
    "cheesecake",
    "dessert",
    "gelato",
)
RAIN_KEYWORDS = ("rain", "drizzle", "storm", "thunder")


def _as_date(value):
    if value is None:
        return None
    if hasattr(value, "date") and not isinstance(value, str):
        return value.date()
    if isinstance(value, str):
        return datetime.strptime(value[:10], "%Y-%m-%d").date()
    return value


def _decimal(value: Any, default: Decimal = Decimal("0")) -> Decimal:
    try:
        return Decimal(str(value if value is not None else default))
    except (InvalidOperation, TypeError, ValueError):
        return default


def _round(value: Any, places: int = 1):
    if value is None:
        return None
    return round(float(value), places)


class DemandService:
    """Deterministic demand advisory engine for admins."""

    def __init__(self, config=None, weather_service: Optional[WeatherService] = None):
        self.config = config or current_app.config
        self.weather_service = weather_service or WeatherService(self.config)

    def dashboard_payload(self) -> Dict[str, Any]:
        today = utcnow().date()
        forecast = self.weather_service.get_forecast()
        upcoming_events = self._upcoming_events(today)
        history = self._history_report(today)
        correlations = self._correlations(today)
        advisories = self._advisories(today, forecast, upcoming_events, correlations, history)
        narrative = self._narrative(advisories, history, forecast)
        return {
            "generated_at": utcnow(),
            "forecast": forecast,
            "upcoming_events": upcoming_events,
            "recent_events": self._recent_events(today),
            "history": history,
            "correlations": correlations,
            "advisories": advisories,
            "narrative": narrative,
            "config": {
                "hot_day_threshold_c": float(self.config.get("HOT_DAY_THRESHOLD_C", 35)),
                "min_history_days": int(self.config.get("DEMAND_MIN_HISTORY_DAYS", 21)),
                "min_matching_days": int(self.config.get("DEMAND_MIN_MATCHING_DAYS", 3)),
            },
        }

    def _sales_filters(self, start=None, end=None):
        filters = [
            Order.status.in_(REVENUE_ORDER_STATUSES),
            Order.payment_status.in_(REVENUE_PAYMENT_STATUSES),
        ]
        if start is not None:
            filters.append(Order.placed_at >= start)
        if end is not None:
            filters.append(Order.placed_at < end)
        return filters

    def _history_report(self, today) -> Dict[str, Any]:
        lookback_start = datetime.combine(today - timedelta(days=180), datetime.min.time())
        distinct_sales_days = (
            db.session.query(func.count(func.distinct(func.date(Order.placed_at))))
            .filter(*self._sales_filters(lookback_start, datetime.combine(today, datetime.min.time())))
            .scalar()
            or 0
        )
        snapshot_days = (
            WeatherSnapshot.query.filter(WeatherSnapshot.forecast_date < today).count()
        )
        event_days = LocalEvent.query.filter(LocalEvent.event_date < today).count()
        min_history = int(self.config.get("DEMAND_MIN_HISTORY_DAYS", 21))
        return {
            "lookback_days": 180,
            "sales_days": int(distinct_sales_days),
            "weather_snapshot_days": int(snapshot_days),
            "local_event_days": int(event_days),
            "sales_history_sufficient": distinct_sales_days >= min_history,
            "weather_history_sufficient": snapshot_days >= int(self.config.get("DEMAND_MIN_MATCHING_DAYS", 3)),
            "message": self._history_message(distinct_sales_days, snapshot_days, event_days),
        }

    def _history_message(self, sales_days, snapshot_days, event_days):
        min_history = int(self.config.get("DEMAND_MIN_HISTORY_DAYS", 21))
        min_matching = int(self.config.get("DEMAND_MIN_MATCHING_DAYS", 3))
        if sales_days < min_history:
            return f"Only {sales_days} delivered paid sales days are available in the last 180 days; collect at least {min_history} before using quantified demand lifts."
        if snapshot_days < min_matching:
            return f"Sales history is usable, but only {snapshot_days} past weather snapshot days exist, so weather correlations stay qualitative for now."
        if event_days < min_matching:
            return f"Weather history is usable. Local-event correlations are still thin with {event_days} past event days."
        return "Sales, weather, and local-event history are sufficient for cautious quantified advisory signals."

    def _correlations(self, today) -> Dict[str, Any]:
        return {
            "hot_day_cold_desserts": self._hot_day_cold_dessert_correlation(today),
            "local_events": self._event_correlation(today),
        }

    def _hot_day_cold_dessert_correlation(self, today) -> Dict[str, Any]:
        threshold = float(self.config.get("HOT_DAY_THRESHOLD_C", 35))
        min_matching = int(self.config.get("DEMAND_MIN_MATCHING_DAYS", 3))
        hot_dates = [
            snapshot.forecast_date
            for snapshot in WeatherSnapshot.query.filter(
                WeatherSnapshot.forecast_date < today,
                WeatherSnapshot.temp_max_c >= threshold,
            ).all()
        ]
        if len(hot_dates) < min_matching:
            return {
                "status": "insufficient",
                "matching_days": len(hot_dates),
                "threshold_c": threshold,
                "message": f"Found {len(hot_dates)} past hot weather snapshot days; need at least {min_matching} to quantify a cold-dessert lift.",
            }

        start = datetime.combine(today - timedelta(days=180), datetime.min.time())
        end = datetime.combine(today, datetime.min.time())
        daily_units = self._daily_units(start, end, cold_only=True)
        if not daily_units:
            return {
                "status": "insufficient",
                "matching_days": len(hot_dates),
                "threshold_c": threshold,
                "message": "No delivered paid cold-dessert sales were found for the history window.",
            }

        overall_avg = sum(daily_units.values()) / len(daily_units)
        hot_values = [daily_units.get(day, 0) for day in hot_dates]
        hot_avg = sum(hot_values) / len(hot_values)
        lift_pct = ((hot_avg - overall_avg) / overall_avg * 100) if overall_avg else 0
        return {
            "status": "ok",
            "matching_days": len(hot_dates),
            "threshold_c": threshold,
            "overall_avg_units": _round(overall_avg),
            "matching_avg_units": _round(hot_avg),
            "lift_pct": _round(lift_pct),
            "message": f"Past hot snapshot days averaged {_round(hot_avg)} cold-dessert units versus {_round(overall_avg)} normally.",
        }

    def _event_correlation(self, today) -> Dict[str, Any]:
        min_matching = int(self.config.get("DEMAND_MIN_MATCHING_DAYS", 3))
        result = {}
        for impact in ("high", "medium", "low"):
            dates = [
                event.event_date
                for event in LocalEvent.query.filter(
                    LocalEvent.event_date < today,
                    LocalEvent.expected_impact == impact,
                ).all()
            ]
            if len(dates) < min_matching:
                result[impact] = {
                    "status": "insufficient",
                    "matching_days": len(dates),
                    "message": f"{len(dates)} past {impact}-impact event days logged; need {min_matching} for a quantified lift.",
                }
                continue
            start = datetime.combine(today - timedelta(days=180), datetime.min.time())
            end = datetime.combine(today, datetime.min.time())
            daily_units = self._daily_units(start, end, cold_only=False)
            event_values = [daily_units.get(day, 0) for day in dates]
            overall_avg = sum(daily_units.values()) / len(daily_units) if daily_units else 0
            event_avg = sum(event_values) / len(event_values) if event_values else 0
            lift_pct = ((event_avg - overall_avg) / overall_avg * 100) if overall_avg else 0
            result[impact] = {
                "status": "ok",
                "matching_days": len(dates),
                "overall_avg_units": _round(overall_avg),
                "matching_avg_units": _round(event_avg),
                "lift_pct": _round(lift_pct),
                "message": f"Past {impact}-impact event days averaged {_round(event_avg)} units versus {_round(overall_avg)} normally.",
            }
        return result

    def _daily_units(self, start, end, cold_only=False):
        query = (
            db.session.query(
                func.date(Order.placed_at).label("sale_date"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("units"),
            )
            .join(OrderItem, OrderItem.order_id == Order.id)
            .outerjoin(Product, Product.id == OrderItem.product_id)
            .outerjoin(Category, Category.id == Product.category_id)
            .filter(*self._sales_filters(start, end))
        )
        if cold_only:
            query = query.filter(self._cold_product_clause())
        rows = query.group_by(func.date(Order.placed_at)).all()
        return {_as_date(row.sale_date): int(row.units or 0) for row in rows}

    def _cold_product_clause(self):
        clauses = []
        for keyword in COLD_DESSERT_KEYWORDS:
            pattern = f"%{keyword}%"
            clauses.extend([Product.name.ilike(pattern), Category.name.ilike(pattern)])
        return or_(*clauses)

    def _upcoming_events(self, today):
        end = today + timedelta(days=7)
        return (
            LocalEvent.query.filter(LocalEvent.event_date >= today, LocalEvent.event_date <= end)
            .order_by(LocalEvent.event_date.asc(), LocalEvent.id.asc())
            .all()
        )

    def _recent_events(self, today):
        start = today - timedelta(days=30)
        return (
            LocalEvent.query.filter(LocalEvent.event_date < today, LocalEvent.event_date >= start)
            .order_by(LocalEvent.event_date.desc(), LocalEvent.id.desc())
            .limit(8)
            .all()
        )

    def _advisories(self, today, forecast, upcoming_events, correlations, history):
        advisories = []
        for day in forecast.get("daily", []):
            date_label = day.get("date")
            temp_max = day.get("temp_max_c")
            if temp_max is not None and float(temp_max) >= float(self.config.get("HOT_DAY_THRESHOLD_C", 35)):
                advisories.append(
                    self._hot_day_advisory(date_label, temp_max, correlations["hot_day_cold_desserts"], history)
                )
            condition_text = f"{day.get('condition', '')} {day.get('description', '')}".lower()
            if any(keyword in condition_text for keyword in RAIN_KEYWORDS):
                advisories.append(self._rain_advisory(date_label, day))

        for event in upcoming_events:
            advisories.append(self._event_advisory(event, correlations["local_events"].get(event.expected_impact, {})))

        if not advisories:
            advisories.append(
                {
                    "id": f"steady-{today.isoformat()}",
                    "type": "steady",
                    "title": "No unusual demand signal detected",
                    "confidence": "low" if not history["sales_history_sufficient"] else "medium",
                    "summary": "No weather or local-event trigger currently suggests a prep adjustment.",
                    "actions": ["Review normal prep and reorder checks before confirming the plan."],
                    "stock_risks": [],
                }
            )
        return advisories

    def _hot_day_advisory(self, date_label, temp_max, correlation, history):
        products = self._top_products(cold_only=True)
        lift_pct = correlation.get("lift_pct") if correlation.get("status") == "ok" else None
        actions = []
        stock_risks = []
        for product in products[:3]:
            suggested_units = self._suggested_units(product["avg_daily_units"], lift_pct)
            actions.append(
                f"Review prep for {product['name']}: target about {suggested_units} units if staffing and orders allow."
            )
            stock_risks.extend(self._stock_risks(product["id"], suggested_units))
        if not actions:
            actions.append("Review chilled dessert and cream-based products; no matching paid sales history is available yet.")
        confidence = "medium" if correlation.get("status") == "ok" and history["sales_history_sufficient"] else "low"
        summary = correlation.get("message") or "Hot forecast detected, but weather-linked sales history is still thin."
        return {
            "id": f"hot-{date_label}",
            "type": "weather",
            "title": f"Hot day forecast for {date_label}",
            "confidence": confidence,
            "summary": f"{summary} Forecast high is {_round(temp_max)} C.",
            "actions": actions,
            "stock_risks": stock_risks[:5],
        }

    def _rain_advisory(self, date_label, day):
        return {
            "id": f"rain-{date_label}",
            "type": "weather",
            "title": f"Rain risk on {date_label}",
            "confidence": "low",
            "summary": f"{day.get('description') or day.get('condition') or 'Rain'} is forecast. This is advisory-only because no delivery conversion correlation is stored yet.",
            "actions": [
                "Review delivery staffing and packaging readiness before the shift.",
                "Avoid changing prices or stock automatically from this signal.",
            ],
            "stock_risks": [],
        }

    def _event_advisory(self, event: LocalEvent, correlation):
        confidence = "medium" if correlation.get("status") == "ok" else "low"
        actions = [
            f"Review prep capacity for {event.name} on {event.event_date.strftime('%d %b %Y')}.",
            "Prioritize fast-moving display items before adjusting any production plan.",
        ]
        return {
            "id": f"event-{event.id}",
            "type": "local_event",
            "title": f"{event.expected_impact.title()} impact event: {event.name}",
            "confidence": confidence,
            "summary": correlation.get("message") or "Local event logged; not enough past event days exist for a quantified lift.",
            "actions": actions,
            "stock_risks": [],
            "event": event,
        }

    def _top_products(self, cold_only=False):
        start = datetime.combine(utcnow().date() - timedelta(days=60), datetime.min.time())
        query = (
            db.session.query(
                Product.id.label("id"),
                Product.name.label("name"),
                func.coalesce(func.sum(OrderItem.quantity), 0).label("units"),
            )
            .join(OrderItem, OrderItem.product_id == Product.id)
            .join(Order, Order.id == OrderItem.order_id)
            .outerjoin(Category, Category.id == Product.category_id)
            .filter(*self._sales_filters(start, utcnow()))
            .group_by(Product.id, Product.name)
            .order_by(func.coalesce(func.sum(OrderItem.quantity), 0).desc())
        )
        if cold_only:
            query = query.filter(self._cold_product_clause())
        rows = query.limit(5).all()
        if not rows and cold_only:
            rows = (
                Product.query.outerjoin(Category, Category.id == Product.category_id)
                .filter(Product.is_active == True, self._cold_product_clause())
                .limit(5)
                .all()
            )
            return [{"id": row.id, "name": row.name, "avg_daily_units": 4} for row in rows]
        return [
            {
                "id": row.id,
                "name": row.name,
                "avg_daily_units": max(1, int(round(float(row.units or 0) / 60))),
            }
            for row in rows
        ]

    def _suggested_units(self, avg_daily_units, lift_pct):
        base = max(1, int(avg_daily_units or 1))
        if lift_pct is None:
            return max(3, base + 2)
        return max(1, int(round(base * (1 + max(0, float(lift_pct)) / 100))))

    def _stock_risks(self, product_id, suggested_units):
        risks = []
        recipe_items = ProductMaterial.query.filter_by(product_id=product_id).all()
        if not recipe_items:
            return risks
        material_ids = [item.raw_material_id for item in recipe_items]
        materials = {material.id: material for material in RawMaterial.query.filter(RawMaterial.id.in_(material_ids)).all()}
        for recipe_item in recipe_items:
            material = materials.get(recipe_item.raw_material_id)
            if material is None:
                continue
            required = _decimal(recipe_item.quantity_required) * Decimal(suggested_units)
            stock = _decimal(material.stock)
            reorder = _decimal(material.reorder_level)
            if stock <= reorder or stock < required:
                risks.append(
                    {
                        "material_name": material.name,
                        "unit": material.unit,
                        "current_stock": float(stock),
                        "reorder_level": float(reorder),
                        "required_for_suggestion": float(required),
                    }
                )
        return risks

    def _narrative(self, advisories, history, forecast):
        fallback = self._fallback_narrative(advisories, history, forecast)
        if not self.config.get("DEMAND_USE_OLLAMA"):
            return {"text": fallback, "source": "deterministic", "available": False}

        try:
            response = requests.post(
                f"{self.config.get('OLLAMA_BASE_URL', 'http://127.0.0.1:11434').rstrip('/')}/api/generate",
                json={
                    "model": self.config.get("OLLAMA_MODEL", "llama3.1"),
                    "stream": False,
                    "prompt": (
                        "Rewrite these bakery demand advisories in two concise admin-facing sentences. "
                        "Do not add numbers, products, reasons, or confidence claims that are not present. "
                        f"Facts: {fallback}"
                    ),
                },
                timeout=8,
            )
            response.raise_for_status()
            text = (response.json().get("response") or "").strip()
            return {"text": text or fallback, "source": "ollama", "available": bool(text)}
        except Exception:
            return {"text": fallback, "source": "deterministic", "available": False}

    def _fallback_narrative(self, advisories, history, forecast):
        if forecast.get("status") not in {"ok", "stale"}:
            weather_note = forecast.get("message") or "Weather context is unavailable."
        else:
            weather_note = f"Weather context is available for {forecast.get('location_label')}."
        lead = advisories[0]["summary"] if advisories else "No active advisory."
        return f"{weather_note} {lead} {history['message']}"
