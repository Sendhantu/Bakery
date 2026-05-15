from events import EventBus, handle_order_status_updated
from repositories import OrderRepository, ProductRepository, UserRepository
from services import AuthService, InventoryService, OrderService, PaymentService

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
        self.auth_service = AuthService(self.user_repository)
        self.payment_service = PaymentService()
        self.inventory_service = InventoryService()
        self.order_service = OrderService(self.order_repository, self.event_bus)
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
