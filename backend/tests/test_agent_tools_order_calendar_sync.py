from unittest.mock import MagicMock

from app.services import agent_tools


def _result(data):
    result = MagicMock()
    result.data = data
    return result


def test_create_order_syncs_calendar_events_after_order_and_item_insert(monkeypatch):
    order = {
        "id": "order-1",
        "order_number": "ORD-20260427-1001",
    }
    orders_table = MagicMock()
    order_items_table = MagicMock()
    orders_table.insert.return_value.execute.return_value = _result([order])
    order_items_table.insert.return_value.execute.return_value = _result([{"id": "item-1"}])

    supabase = MagicMock()
    supabase.table.side_effect = {
        "orders": orders_table,
        "order_items": order_items_table,
    }.__getitem__

    synced_order_ids = []
    monkeypatch.setattr(agent_tools, "get_supabase_client", lambda: supabase)
    monkeypatch.setattr(
        agent_tools,
        "_sync_calendar_events_for_order_id",
        synced_order_ids.append,
    )

    result = agent_tools.create_order(
        buyer_id="buyer-1",
        seller_id="seller-1",
        product_id="product-1",
        quantity=3,
        unit_price=10000,
        delivery_date="2026-05-02",
    )

    assert result["success"] is True
    assert synced_order_ids == ["order-1"]


def test_update_order_status_syncs_calendar_events_for_cancelled_order(monkeypatch):
    orders_table = MagicMock()
    orders_table.update.return_value.eq.return_value.execute.return_value = _result(
        [{"id": "order-1"}]
    )

    supabase = MagicMock()
    supabase.table.return_value = orders_table

    synced_order_ids = []
    monkeypatch.setattr(agent_tools, "get_supabase_client", lambda: supabase)
    monkeypatch.setattr(
        agent_tools,
        "_sync_calendar_events_for_order_id",
        synced_order_ids.append,
    )

    result = agent_tools.update_order_status("order-1", "CANCELLED")

    assert result == {
        "success": True,
        "order_id": "order-1",
        "new_status": "CANCELLED",
    }
    assert synced_order_ids == ["order-1"]
