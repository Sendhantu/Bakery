from utils.notifications import check_and_send_inventory_alerts


class InventoryService:
    def dispatch_low_stock_alerts(self):
        return check_and_send_inventory_alerts()
