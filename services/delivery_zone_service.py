from dataclasses import dataclass
from decimal import Decimal
import math
import re

from flask import current_app, has_app_context

from exceptions import ValidationError
from models import (
    Branch,
    DeliveryDistanceBand,
    DeliveryPincodeRule,
    DeliveryZoneSetting,
    db,
)
from utils.formatters import parse_coordinate


PINCODE_RE = re.compile(r"^\d{6}$")


@dataclass
class ServiceabilityResult:
    serviceable: bool
    status: str
    message: str
    branch_id: int | None
    delivery_fee: Decimal
    distance_km: Decimal | None = None
    eta_minutes: int | None = None
    rule_source: str = "unavailable"
    pickup_available: bool = True

    def as_dict(self):
        return {
            "serviceable": self.serviceable,
            "status": self.status,
            "message": self.message,
            "branch_id": self.branch_id,
            "delivery_fee": float(self.delivery_fee),
            "distance_km": float(self.distance_km) if self.distance_km is not None else None,
            "eta_minutes": self.eta_minutes,
            "rule_source": self.rule_source,
            "pickup_available": self.pickup_available,
        }


class DeliveryZoneService:
    def __init__(self, config=None):
        self.config = config

    def validate_delivery(
        self,
        *,
        branch_id=None,
        pincode=None,
        latitude=None,
        longitude=None,
        order_subtotal=0,
    ):
        result = self.check_serviceability(
            branch_id=branch_id,
            pincode=pincode,
            latitude=latitude,
            longitude=longitude,
            order_subtotal=order_subtotal,
        )
        if not result.serviceable:
            raise ValidationError(result.message)
        return result

    def check_serviceability(
        self,
        *,
        branch_id=None,
        pincode=None,
        latitude=None,
        longitude=None,
        order_subtotal=0,
    ):
        branch_id = self._resolve_branch_id(branch_id)
        setting = self._setting_for_branch(branch_id)
        pickup_available = bool(setting.is_pickup_enabled if setting else True)
        if setting and not setting.is_delivery_enabled:
            return self._blocked(
                "Home delivery is temporarily unavailable. You can still place a store-pickup order.",
                branch_id,
                "delivery_disabled",
                pickup_available=pickup_available,
            )

        subtotal = Decimal(str(order_subtotal or 0)).quantize(Decimal("0.01"))
        min_order = Decimal(str(setting.min_order_value if setting else 0)).quantize(Decimal("0.01"))
        if subtotal < min_order:
            return self._blocked(
                f"Delivery requires a minimum order value of ₹{min_order:.0f}. You can still place a store-pickup order.",
                branch_id,
                "minimum_order",
                pickup_available=pickup_available,
            )

        normalized_pincode = self._normalize_pincode(pincode)
        blocked_rule = self._pincode_rule(normalized_pincode, branch_id, status="blocked")
        if blocked_rule:
            return self._blocked(
                "Direct delivery is currently unavailable at this location. You can still place a store-pickup order.",
                branch_id,
                "blocked_pincode",
                pickup_available=pickup_available,
            )

        branch_rule = self._pincode_rule(normalized_pincode, branch_id)
        if branch_rule and branch_rule.status == "blocked":
            return self._blocked(
                "Direct delivery is currently unavailable at this location. You can still place a store-pickup order.",
                branch_id,
                "branch_pincode",
                pickup_available=pickup_available,
            )

        distance_result = self._distance_result(
            branch_id=branch_id,
            setting=setting,
            latitude=latitude,
            longitude=longitude,
            pickup_available=pickup_available,
        )
        if distance_result is not None:
            return distance_result

        if branch_rule and branch_rule.status in {"supported", "partial"}:
            fee = self._fee_from_rule(branch_rule, setting)
            return ServiceabilityResult(
                serviceable=True,
                status="paid" if fee > 0 else "free",
                message=(
                    "Great news! Free delivery is available to your location."
                    if fee == 0
                    else f"Delivery is available for ₹{fee:.0f}."
                ),
                branch_id=branch_id,
                delivery_fee=fee,
                eta_minutes=branch_rule.estimated_delivery_minutes,
                rule_source="branch_pincode",
                pickup_available=pickup_available,
            )

        fallback_rule = self._pincode_rule(normalized_pincode, None)
        if fallback_rule and fallback_rule.status in {"supported", "partial"}:
            fee = self._fee_from_rule(fallback_rule, setting)
            return ServiceabilityResult(
                serviceable=True,
                status="paid" if fee > 0 else "free",
                message=(
                    "Great news! Free delivery is available to your location."
                    if fee == 0
                    else f"Delivery is available for ₹{fee:.0f}."
                ),
                branch_id=branch_id,
                delivery_fee=fee,
                eta_minutes=fallback_rule.estimated_delivery_minutes,
                rule_source="pincode_fallback",
                pickup_available=pickup_available,
            )

        if normalized_pincode and self._store_pincode() == normalized_pincode:
            return ServiceabilityResult(
                serviceable=True,
                status="free",
                message="Great news! Free delivery is available to your location.",
                branch_id=branch_id,
                delivery_fee=Decimal("0.00"),
                eta_minutes=30,
                rule_source="store_pincode",
                pickup_available=pickup_available,
            )

        return self._blocked(
            "We could not validate delivery for this location right now. You can still place a store-pickup order or retry with a pincode/current location.",
            branch_id,
            "unvalidated_location",
            pickup_available=pickup_available,
        )

    def ensure_default_rules(self, branch_id=None):
        branch_id = self._resolve_branch_id(branch_id)
        setting = self._setting_for_branch(branch_id)
        if setting is None:
            setting = DeliveryZoneSetting(
                branch_id=branch_id,
                max_radius_km=Decimal("7.00"),
                free_radius_km=Decimal("3.00"),
                min_order_value=Decimal("0.00"),
                extra_fee=Decimal("0.00"),
            )
            db.session.add(setting)
            db.session.flush()
        existing_bands = DeliveryDistanceBand.query.filter_by(
            branch_id=branch_id,
            is_active=True,
        ).count()
        if existing_bands == 0:
            db.session.add_all(
                [
                    DeliveryDistanceBand(
                        branch_id=branch_id,
                        min_distance_km=Decimal("0.00"),
                        max_distance_km=Decimal("3.00"),
                        delivery_fee=Decimal("0.00"),
                    ),
                    DeliveryDistanceBand(
                        branch_id=branch_id,
                        min_distance_km=Decimal("3.00"),
                        max_distance_km=Decimal("7.00"),
                        delivery_fee=Decimal("50.00"),
                    ),
                ]
            )
        return setting

    def _distance_result(self, *, branch_id, setting, latitude, longitude, pickup_available):
        origin = self._origin_coordinates(branch_id)
        destination_lat = parse_coordinate(latitude, -90, 90)
        destination_lng = parse_coordinate(longitude, -180, 180)
        if not origin or destination_lat is None or destination_lng is None:
            return None

        distance = Decimal(str(self._haversine_km(origin[0], origin[1], destination_lat, destination_lng))).quantize(Decimal("0.01"))
        max_radius = Decimal(str(setting.max_radius_km if setting else 7)).quantize(Decimal("0.01"))
        if distance > max_radius:
            return self._blocked(
                "Direct delivery is currently unavailable at this location. You can still place a store-pickup order.",
                branch_id,
                "distance_radius",
                distance_km=distance,
                pickup_available=pickup_available,
            )

        fee = self._fee_for_distance(branch_id, distance, setting)
        return ServiceabilityResult(
            serviceable=True,
            status="paid" if fee > 0 else "free",
            message=(
                "Great news! Free delivery is available to your location."
                if fee == 0
                else f"Delivery is available for ₹{fee:.0f}."
            ),
            branch_id=branch_id,
            delivery_fee=fee,
            distance_km=distance,
            eta_minutes=max(30, int(20 + float(distance) * 6)),
            rule_source="distance",
            pickup_available=pickup_available,
        )

    def _fee_for_distance(self, branch_id, distance, setting):
        bands = (
            DeliveryDistanceBand.query.filter_by(branch_id=branch_id, is_active=True)
            .order_by(DeliveryDistanceBand.min_distance_km.asc())
            .all()
        )
        for band in bands:
            lower = Decimal(str(band.min_distance_km or 0))
            upper = Decimal(str(band.max_distance_km or 0))
            if distance > lower and distance <= upper or distance == Decimal("0.00") and lower == 0:
                return (Decimal(str(band.delivery_fee or 0)) + Decimal(str(setting.extra_fee if setting else 0))).quantize(Decimal("0.01"))

        free_radius = Decimal(str(setting.free_radius_km if setting else 3)).quantize(Decimal("0.01"))
        if distance <= free_radius:
            return Decimal("0.00")
        return (Decimal("50.00") + Decimal(str(setting.extra_fee if setting else 0))).quantize(Decimal("0.01"))

    def _fee_from_rule(self, rule, setting):
        if rule.delivery_fee_override is not None:
            return Decimal(str(rule.delivery_fee_override or 0)).quantize(Decimal("0.01"))
        return Decimal(str(setting.extra_fee if setting else 0)).quantize(Decimal("0.01"))

    def _pincode_rule(self, pincode, branch_id, status=None):
        if not pincode:
            return None
        query = DeliveryPincodeRule.query.filter_by(
            pincode=pincode,
            is_active=True,
        )
        if branch_id is None:
            query = query.filter(DeliveryPincodeRule.branch_id.is_(None))
        else:
            query = query.filter(DeliveryPincodeRule.branch_id == branch_id)
        if status:
            query = query.filter(DeliveryPincodeRule.status == status)
        return query.order_by(DeliveryPincodeRule.branch_id.desc()).first()

    def _setting_for_branch(self, branch_id):
        return DeliveryZoneSetting.query.filter_by(branch_id=branch_id).first()

    def _resolve_branch_id(self, branch_id):
        if branch_id:
            return int(branch_id)
        config = self._config()
        default = config.get("DEFAULT_BRANCH_ID")
        if default:
            return int(default)
        branch = Branch.query.filter_by(is_active=True).order_by(Branch.id.asc()).first()
        return branch.id if branch else None

    def _origin_coordinates(self, branch_id):
        config = self._config()
        lat = parse_coordinate(config.get("STORE_LATITUDE"), -90, 90)
        lng = parse_coordinate(config.get("STORE_LONGITUDE"), -180, 180)
        if lat is not None and lng is not None:
            return lat, lng
        return None

    def _store_pincode(self):
        details = self._config().get("STORE_DETAILS") or {}
        return self._normalize_pincode(details.get("pincode"))

    def _normalize_pincode(self, pincode):
        value = re.sub(r"\D+", "", str(pincode or ""))
        if not value:
            return ""
        if not PINCODE_RE.match(value):
            return ""
        return value

    def _blocked(self, message, branch_id, source, *, distance_km=None, pickup_available=True):
        return ServiceabilityResult(
            serviceable=False,
            status="blocked",
            message=message,
            branch_id=branch_id,
            delivery_fee=Decimal("0.00"),
            distance_km=distance_km,
            rule_source=source,
            pickup_available=pickup_available,
        )

    def _config(self):
        if self.config is not None:
            return self.config
        if has_app_context():
            return current_app.config
        return {}

    @staticmethod
    def _haversine_km(lat1, lng1, lat2, lng2):
        radius_km = 6371.0
        phi1 = math.radians(lat1)
        phi2 = math.radians(lat2)
        delta_phi = math.radians(lat2 - lat1)
        delta_lambda = math.radians(lng2 - lng1)
        a = (
            math.sin(delta_phi / 2) ** 2
            + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2) ** 2
        )
        return radius_km * 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
