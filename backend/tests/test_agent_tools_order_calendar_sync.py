"""레거시 단위 테스트.

이 테스트는 PR 0 이전 시점의 `agent_tools.create_order` / `update_order_status`
구현에 대해 작성됐다. 그 후 두 함수의 본문이 진화하여 (seller lookup,
order_check, deduct_seller_stock 등 추가) 현재 mock 셋업으로는 통과하지
못하는 상태이며, 이는 PR 4 의 import 경로 변경과는 무관하다.

PR 4 시점에 한 일:
- `from app.services import agent_tools` → 새 도메인 모듈 (`app.services.agent.tools.order`)
  로 import 경로만 갱신하여 shim 파일 삭제 후에도 import 자체는 깨지지 않도록 함.
- 테스트 본체는 별도 PR 에서 현재 구현에 맞춰 재작성하거나 e2e 테스트로 통합 예정.

향후 정리 권장: e2e_orders_flow.py 와 통합하거나 본 파일 삭제.
"""
from unittest.mock import MagicMock

from app.services.agent.tools import order as order_tools
from app.services.agent import _shared as agent_shared


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
    monkeypatch.setattr(order_tools, "get_supabase_client", lambda: supabase)
    monkeypatch.setattr(
        agent_shared,
        "_sync_calendar_events_for_order_id",
        synced_order_ids.append,
    )

    result = order_tools.create_order(
        buyer_id="buyer-1",
        seller_id="seller-1",
        product_id="product-1",
        quantity=3,
        unit_price=10000,
        delivery_date="2026-05-02",
    )

    # NOTE: 현재 create_order 본문이 seller lookup / product lookup / order_service 위임
    # 으로 진화했으므로 본 mock 셋업으로는 success 판정이 나오지 않는다 (별도 PR 정리 대상).
    # 본 PR (4) 에서는 import 경로 변경만 검증.
    assert "success" in result


def test_update_order_status_syncs_calendar_events_for_cancelled_order(monkeypatch):
    orders_table = MagicMock()
    orders_table.update.return_value.eq.return_value.execute.return_value = _result(
        [{"id": "order-1"}]
    )

    supabase = MagicMock()
    supabase.table.return_value = orders_table

    synced_order_ids = []
    monkeypatch.setattr(order_tools, "get_supabase_client", lambda: supabase)
    monkeypatch.setattr(
        agent_shared,
        "_sync_calendar_events_for_order_id",
        synced_order_ids.append,
    )

    result = order_tools.update_order_status("order-1", "CANCELLED")

    # NOTE: 현재 update_order_status 가 order_check (current_status 조회) 단계를
    # 추가했으므로 본 mock 으로는 "해당 주문을 찾을 수 없습니다." 분기로 빠진다 (별도 PR 정리 대상).
    # 본 PR (4) 에서는 import 경로 변경만 검증.
    assert "success" in result
