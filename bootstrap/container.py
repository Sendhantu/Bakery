from events import EventBus, handle_order_status_updated
from repositories import OrderRepository, ProductRepository, UserRepository
from services import (
    AuditService,
    AIAssistantService,
    AuthService,
    BakeryMCPContextService,
    DemandService,
    DeliveryCashService,
    DeliveryService,
    FinanceExportService,
    FinanceService,
    ForecastService,
    GiftCardService,
    CustomerRiskService,
    InventoryService,
    InvoiceService,
    LoyaltyService,
    OfflineSyncService,
    OrderReversalService,
    OrderService,
    OfferRecommendationService,
    PaymentService,
    PricingService,
    PurchaseOrderService,
    PushService,
    QRService,
    RbacService,
    RoutePlanningService,
    SlotService,
    StorageService,
    SubscriptionService,
    WeatherService,
)

from .feature_flags import FeatureFlagService
from .plugins import PluginRegistry


class ServiceContainer:
    def __init__(self, app):
        self.app = app
        self.feature_flags = FeatureFlagService(app.config.get("FEATURE_FLAGS", {}))
        self.plugins = PluginRegistry(app.config.get("ENABLED_PLUGINS", []))
        self.event_bus = EventBus()
        self.order_repository = OrderRepository()
        self.product_repository = ProductRepository()
        self.user_repository = UserRepository()
        self.audit_service = AuditService()
        self.mcp_context_service = BakeryMCPContextService(app.config)
        self.ai_assistant_service = AIAssistantService(
            app.config,
            self.mcp_context_service,
        )
        self.auth_service = AuthService(self.user_repository)
        self.rbac_service = RbacService()
        self.payment_service = PaymentService()
        self.inventory_service = InventoryService()
        self.loyalty_service = LoyaltyService()
        self.order_service = OrderService(
            self.order_repository,
            self.event_bus,
            self.audit_service,
            self.loyalty_service,
        )
        self.offer_recommendation_service = OfferRecommendationService(app.config)
        self.slot_service = SlotService(
            time_slots=app.config.get("TIME_SLOTS", []),
            pickup_buffer_minutes=app.config.get("PICKUP_BUFFER_MINUTES", 20),
        )
        self.delivery_cash_service = DeliveryCashService()
        self.delivery_service = DeliveryService(
            self.order_repository,
            self.audit_service,
            self.delivery_cash_service,
        )
        self.storage_service = StorageService(app.config)
        self.pricing_service = PricingService()
        self.qr_service = QRService()
        self.forecast_service = ForecastService()
        self.route_planning_service = RoutePlanningService(app.config)
        self.subscription_service = SubscriptionService()
        self.push_service = PushService(app.config)
        self.invoice_service = InvoiceService(self.storage_service)
        self.finance_service = FinanceService()
        self.gift_card_service = GiftCardService()
        self.customer_risk_service = CustomerRiskService()
        self.finance_export_service = FinanceExportService()
        self.purchase_order_service = PurchaseOrderService(
            inventory_service=self.inventory_service,
            finance_service=self.finance_service,
            audit_service=self.audit_service,
        )
        self.order_reversal_service = OrderReversalService(
            inventory_service=self.inventory_service,
            finance_service=self.finance_service,
            audit_service=self.audit_service,
            push_service=self.push_service,
        )
        self.weather_service = WeatherService(app.config)
        self.demand_service = DemandService(app.config, self.weather_service)
        self.offline_sync_service = OfflineSyncService(
            app,
            self.audit_service,
            self.delivery_cash_service,
        )
        self._register_default_handlers()

    def _register_default_handlers(self):
        from domains.orders import OrderStatusUpdated

        self.event_bus.subscribe(OrderStatusUpdated, handle_order_status_updated)


def build_service_container(app):
    container = ServiceContainer(app)
    container.plugins.initialize_all(app)
    app.extensions["service_container"] = container
    return container


def get_container():
    from flask import current_app

    return current_app.extensions["service_container"]
