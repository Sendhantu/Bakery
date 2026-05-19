import json
from collections import defaultdict
from datetime import date, datetime, timedelta
from decimal import Decimal

from sqlalchemy import func

from models import (
    InventoryForecast,
    Order,
    OrderItem,
    Product,
    ProductMaterial,
    cache,
    db,
)


class ForecastService:
    def build_daily_forecasts(self, *, target_date=None, branch_id=None):
        target_date = target_date or (datetime.utcnow().date() + timedelta(days=1))
        lookback_days = 28
        start_date = target_date - timedelta(days=lookback_days)

        rows = (
            db.session.query(
                OrderItem.product_id,
                func.date(Order.delivery_date).label("delivery_day"),
                func.sum(OrderItem.quantity).label("quantity"),
            )
            .join(Order, Order.id == OrderItem.order_id)
            .filter(
                Order.delivery_date >= start_date,
                Order.delivery_date < target_date,
                Order.status.in_(["PLACED", "PREPARING", "PACKED", "OUT_FOR_DELIVERY", "DELIVERED"]),
            )
            .group_by(OrderItem.product_id, "delivery_day")
            .all()
        )

        grouped = defaultdict(list)
        for product_id, _delivery_day, quantity in rows:
            grouped[product_id].append(Decimal(str(quantity or 0)))

        forecasts = []
        for product in Product.query.filter_by(is_active=True).all():
            history = grouped.get(product.id, [])
            if history:
                average = sum(history) / Decimal(str(len(history)))
            else:
                average = Decimal("0")

            weekday_multiplier = Decimal("1.15") if target_date.weekday() in {4, 5, 6} else Decimal("1.00")
            predicted = (average * weekday_multiplier).quantize(Decimal("0.01"))
            ingredients = self._ingredient_projection(product.id, predicted)

            forecast = InventoryForecast.query.filter_by(
                branch_id=branch_id,
                product_id=product.id,
                forecast_date=target_date,
                horizon="daily",
            ).first()
            if forecast is None:
                forecast = InventoryForecast(
                    branch_id=branch_id,
                    product_id=product.id,
                    forecast_date=target_date,
                    horizon="daily",
                )
                db.session.add(forecast)

            forecast.predicted_quantity = predicted
            forecast.ingredient_projection_json = json.dumps(
                ingredients, sort_keys=True, default=str
            )
            forecast.confidence_score = 70 if history else 35
            forecast.alert_level = "warning" if predicted > 0 and predicted < Decimal("3") else "normal"
            forecasts.append(forecast)

        db.session.commit()
        self._emit_low_stock_alerts(forecasts)
        cache.set(
            f"inventory_forecasts:{branch_id or 'all'}:{target_date.isoformat()}",
            [
                {
                    "product_id": forecast.product_id,
                    "predicted_quantity": float(forecast.predicted_quantity or 0),
                    "alert_level": forecast.alert_level,
                }
                for forecast in forecasts
            ],
            timeout=3600,
        )
        return forecasts

    def weekly_summary(self, *, branch_id=None):
        today = date.today()
        forecasts = (
            InventoryForecast.query.filter(
                InventoryForecast.forecast_date >= today,
                InventoryForecast.forecast_date <= today + timedelta(days=6),
            )
            .filter(
                InventoryForecast.branch_id == branch_id
                if branch_id is not None
                else InventoryForecast.branch_id.is_(None)
            )
            .all()
        )
        return forecasts

    def _emit_low_stock_alerts(self, forecasts):
        from bootstrap import get_container

        audit = get_container().audit_service
        for forecast in forecasts:
            if forecast.alert_level != "warning":
                continue
            product = db.session.get(Product, forecast.product_id)
            if not product:
                continue
            audit.alert(
                "low_stock_forecast",
                f"Low demand forecast: {product.name}",
                f"Predicted quantity {forecast.predicted_quantity} for {forecast.forecast_date}.",
                severity="warning",
                branch_id=forecast.branch_id,
            )
        db.session.commit()

    def _ingredient_projection(self, product_id, quantity):
        ingredients = {}
        requirements = ProductMaterial.query.filter_by(product_id=product_id).all()
        for requirement in requirements:
            ingredients[requirement.raw_material.name] = float(
                Decimal(str(requirement.quantity_required or 0)) * Decimal(str(quantity or 0))
            )
        return ingredients
