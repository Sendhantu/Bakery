import json
import math

import requests

from models import Delivery, DeliveryRoutePlan, cache, db


class RoutePlanningService:
    def __init__(self, config):
        self.config = config

    def plan_for_agent(self, agent, deliveries):
        route_date = deliveries[0].order.delivery_date if deliveries else None
        ordered_deliveries = sorted(
            [delivery for delivery in deliveries if delivery.order],
            key=lambda delivery: self._distance_score(agent, delivery),
        )
        total_distance = 0.0
        for current, nxt in zip(ordered_deliveries, ordered_deliveries[1:]):
            total_distance += self._haversine(
                current.order.delivery_latitude,
                current.order.delivery_longitude,
                nxt.order.delivery_latitude,
                nxt.order.delivery_longitude,
            )

        plan = DeliveryRoutePlan.query.filter_by(
            agent_id=agent.id,
            route_date=route_date,
        ).first()
        if plan is None:
            plan = DeliveryRoutePlan(agent_id=agent.id, branch_id=agent.branch_id, route_date=route_date)
            db.session.add(plan)
        plan.status = "planned"
        plan.stop_count = len(ordered_deliveries)
        plan.total_distance_km = round(total_distance, 2)
        plan.estimated_duration_minutes = int(max(15, total_distance * 8))
        plan.route_payload_json = json.dumps(
            [delivery.id for delivery in ordered_deliveries], sort_keys=True
        )
        db.session.commit()
        return plan

    def eta_for_delivery(self, delivery):
        if not delivery.order:
            return None
        if delivery.eta_minutes:
            return delivery.eta_minutes
        cache_key = f"delivery_eta:{delivery.id}"
        cached = cache.get(cache_key)
        if cached is not None:
            return cached

        eta = None
        if self.config.get("GOOGLE_MAPS_API_KEY"):
            eta = self._google_eta_minutes(delivery)
        if eta is None:
            eta = int(max(15, self._distance_score(delivery.agent, delivery) * 6))
        cache.set(cache_key, eta, timeout=self.config.get("ROUTE_CACHE_TTL_SECONDS", 900))
        delivery.eta_minutes = eta
        return eta

    def _google_eta_minutes(self, delivery):
        if not delivery.agent or delivery.agent.current_latitude is None or delivery.agent.current_longitude is None:
            return None
        if delivery.order.delivery_latitude is None or delivery.order.delivery_longitude is None:
            return None
        try:
            response = requests.get(
                "https://maps.googleapis.com/maps/api/distancematrix/json",
                params={
                    "origins": f"{delivery.agent.current_latitude},{delivery.agent.current_longitude}",
                    "destinations": f"{delivery.order.delivery_latitude},{delivery.order.delivery_longitude}",
                    "key": self.config["GOOGLE_MAPS_API_KEY"],
                },
                timeout=5,
            )
            payload = response.json()
            duration = payload["rows"][0]["elements"][0]["duration"]["value"]
            return max(5, int(duration // 60))
        except Exception:
            return None

    def _distance_score(self, agent, delivery):
        if not agent or agent.current_latitude is None or agent.current_longitude is None:
            return 0
        return self._haversine(
            agent.current_latitude,
            agent.current_longitude,
            delivery.order.delivery_latitude,
            delivery.order.delivery_longitude,
        )

    def _haversine(self, lat1, lon1, lat2, lon2):
        if None in {lat1, lon1, lat2, lon2}:
            return 0
        radius = 6371
        dlat = math.radians(lat2 - lat1)
        dlon = math.radians(lon2 - lon1)
        a = (
            math.sin(dlat / 2) ** 2
            + math.cos(math.radians(lat1))
            * math.cos(math.radians(lat2))
            * math.sin(dlon / 2) ** 2
        )
        return 2 * radius * math.atan2(math.sqrt(a), math.sqrt(1 - a))
