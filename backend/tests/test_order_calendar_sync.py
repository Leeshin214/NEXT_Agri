from copy import deepcopy

from app.services.order_service import OrderService


class FakeResult:
    def __init__(self, data):
        self.data = data
        self.count = len(data)


class FakeQuery:
    def __init__(self, rows, operation, payload=None):
        self.rows = rows
        self.operation = operation
        self.payload = payload
        self.filters = []
        self.order_field = None

    def eq(self, field, value):
        self.filters.append(("eq", field, value))
        return self

    def is_(self, field, value):
        self.filters.append(("is", field, value))
        return self

    def order(self, field, **_kwargs):
        self.order_field = field
        return self

    def _matches(self, row):
        for op, field, value in self.filters:
            if op == "eq" and str(row.get(field)) != str(value):
                return False
            if op == "is" and row.get(field) is not value:
                return False
        return True

    def _matching_rows(self):
        rows = [row for row in self.rows if self._matches(row)]
        if self.order_field:
            rows.sort(key=lambda row: row.get(self.order_field) or "")
        return rows

    def execute(self):
        if self.operation == "select":
            return FakeResult([deepcopy(row) for row in self._matching_rows()])

        if self.operation == "insert":
            row = deepcopy(self.payload)
            row.setdefault("id", f"event-{len(self.rows) + 1}")
            row.setdefault("created_at", f"2026-04-27T00:00:0{len(self.rows)}")
            self.rows.append(row)
            return FakeResult([deepcopy(row)])

        if self.operation == "update":
            updated = []
            for row in self._matching_rows():
                row.update(deepcopy(self.payload))
                updated.append(deepcopy(row))
            return FakeResult(updated)

        raise AssertionError(f"Unsupported operation: {self.operation}")


class FakeTable:
    def __init__(self, rows):
        self.rows = rows

    def select(self, *_args, **_kwargs):
        return FakeQuery(self.rows, "select")

    def insert(self, payload):
        return FakeQuery(self.rows, "insert", payload)

    def update(self, payload):
        return FakeQuery(self.rows, "update", payload)


class FakeSupabase:
    def __init__(self, tables):
        self.tables = tables

    def table(self, name):
        return FakeTable(self.tables.setdefault(name, []))


def make_service(calendar_rows=None):
    service = OrderService()
    service._client = FakeSupabase({"calendar_events": calendar_rows or []})
    return service


def make_order(**overrides):
    order = {
        "id": "order-1",
        "order_number": "ORD-20260427-1001",
        "buyer_id": "buyer-1",
        "seller_id": "seller-1",
        "status": "QUOTE_REQUESTED",
        "total_amount": 120000,
        "delivery_date": None,
        "delivery_address": "서울시 강남구",
        "notes": "오전 배송 희망",
        "created_at": "2026-04-25T09:30:00+00:00",
        "deleted_at": None,
    }
    order.update(overrides)
    return order


def test_sync_calendar_events_creates_buyer_and_seller_events_for_active_quote():
    service = make_service()

    service._sync_calendar_events_for_order_sync(make_order())

    events = service.client.tables["calendar_events"]
    assert len(events) == 2
    assert {event["user_id"] for event in events} == {"buyer-1", "seller-1"}
    assert {event["order_id"] for event in events} == {"order-1"}
    assert {event["event_date"] for event in events} == {"2026-04-25"}
    assert all(event["event_type"] == "ORDER" for event in events)
    assert all(event["deleted_at"] is None for event in events)
    assert all("견적 요청" in event["title"] for event in events)


def test_sync_calendar_events_updates_reactivates_and_deduplicates_events():
    existing = [
        {
            "id": "buyer-primary",
            "user_id": "buyer-1",
            "order_id": "order-1",
            "title": "old",
            "event_date": "2026-04-25",
            "deleted_at": None,
            "created_at": "2026-04-01T00:00:00",
        },
        {
            "id": "buyer-duplicate",
            "user_id": "buyer-1",
            "order_id": "order-1",
            "title": "duplicate",
            "event_date": "2026-04-25",
            "deleted_at": None,
            "created_at": "2026-04-02T00:00:00",
        },
        {
            "id": "seller-deleted",
            "user_id": "seller-1",
            "order_id": "order-1",
            "title": "deleted",
            "event_date": "2026-04-25",
            "deleted_at": "2026-04-26T00:00:00+00:00",
            "created_at": "2026-04-01T00:00:00",
        },
    ]
    service = make_service(existing)

    service._sync_calendar_events_for_order_sync(
        make_order(
            status="CONFIRMED",
            total_amount=150000,
            delivery_date="2026-05-02",
            delivery_address="부산시 해운대구",
        )
    )

    events = {event["id"]: event for event in service.client.tables["calendar_events"]}
    assert events["buyer-primary"]["event_date"] == "2026-05-02"
    assert events["buyer-primary"]["deleted_at"] is None
    assert "주문 확정" in events["buyer-primary"]["title"]
    assert "150,000원" in events["buyer-primary"]["description"]
    assert events["buyer-duplicate"]["deleted_at"] is not None
    assert events["seller-deleted"]["deleted_at"] is None
    assert events["seller-deleted"]["event_date"] == "2026-05-02"


def test_sync_calendar_events_soft_deletes_linked_events_for_cancelled_order():
    existing = [
        {
            "id": "buyer-event",
            "user_id": "buyer-1",
            "order_id": "order-1",
            "deleted_at": None,
        },
        {
            "id": "seller-event",
            "user_id": "seller-1",
            "order_id": "order-1",
            "deleted_at": None,
        },
        {
            "id": "other-order-event",
            "user_id": "buyer-1",
            "order_id": "order-2",
            "deleted_at": None,
        },
    ]
    service = make_service(existing)

    service._sync_calendar_events_for_order_sync(make_order(status="CANCELLED"))

    events = {event["id"]: event for event in service.client.tables["calendar_events"]}
    assert events["buyer-event"]["deleted_at"] is not None
    assert events["seller-event"]["deleted_at"] is not None
    assert events["other-order-event"]["deleted_at"] is None
