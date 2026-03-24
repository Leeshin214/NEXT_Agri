import pytest
from unittest.mock import patch, MagicMock
from httpx import AsyncClient, ASGITransport

from app.main import app


# 테스트용 사용자 데이터
SELLER_USER = {
    "id": "11111111-1111-1111-1111-111111111111",
    "email": "seller@test.com",
    "name": "테스트판매자",
    "role": "SELLER",
    "company_name": "테스트농장",
    "phone": "010-1234-5678",
}

BUYER_USER = {
    "id": "22222222-2222-2222-2222-222222222222",
    "email": "buyer@test.com",
    "name": "테스트구매자",
    "role": "BUYER",
    "company_name": "테스트마트",
    "phone": "010-9876-5432",
}


@pytest.fixture
async def client():
    """비인증 AsyncClient"""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as ac:
        yield ac


@pytest.fixture
def mock_seller_auth():
    """판매자 인증 모킹"""
    from app.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: SELLER_USER
    yield SELLER_USER
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def mock_buyer_auth():
    """구매자 인증 모킹"""
    from app.dependencies import get_current_user
    app.dependency_overrides[get_current_user] = lambda: BUYER_USER
    yield BUYER_USER
    app.dependency_overrides.pop(get_current_user, None)


@pytest.fixture
def mock_supabase():
    """Supabase 클라이언트 모킹.

    각 서비스는 lazy initialization을 사용하므로, 서비스 모듈에서 임포트된
    get_supabase_client 참조와 서비스 인스턴스의 캐시된 _client를 함께 교체한다.
    """
    mock_client = MagicMock()

    # 테이블 이름별로 동일한 Mock 객체를 반환해야 테스트에서 설정한
    # execute.return_value가 서비스 호출 시에도 동일하게 적용된다.
    _table_cache: dict = {}

    def make_table_mock() -> MagicMock:
        table = MagicMock()
        table.select.return_value = table
        table.insert.return_value = table
        table.update.return_value = table
        table.delete.return_value = table
        table.eq.return_value = table
        table.neq.return_value = table
        table.in_.return_value = table
        table.is_.return_value = table
        table.lt.return_value = table
        table.order.return_value = table
        table.limit.return_value = table
        table.range.return_value = table
        table.or_.return_value = table

        # Supabase .single() 은 data를 dict(단일 행)으로 반환한다.
        # 일반 .execute() 는 data를 list로 반환한다.
        # mock에서도 이 차이를 반영하기 위해 single_table은 별도 execute_result를 가진다.
        single_table = MagicMock()
        single_table.execute = MagicMock()
        single_execute_result = MagicMock()
        single_execute_result.data = None
        single_execute_result.count = 0
        single_table.execute.return_value = single_execute_result
        table.single.return_value = single_table

        execute_result = MagicMock()
        execute_result.data = []
        execute_result.count = 0
        table.execute.return_value = execute_result

        return table

    def mock_table(name):
        if name not in _table_cache:
            _table_cache[name] = make_table_mock()
        return _table_cache[name]

    mock_client.table = mock_table

    # 서비스 모듈 각각의 get_supabase_client 참조를 패치하고,
    # 이미 생성된 서비스 인스턴스의 _client 캐시를 교체한다.
    from app.services.product_service import product_service
    from app.services.order_service import order_service
    from app.services.partner_service import partner_service
    from app.services.chat_service import chat_service

    patch_targets = [
        "app.services.product_service.get_supabase_client",
        "app.services.order_service.get_supabase_client",
        "app.services.partner_service.get_supabase_client",
        "app.services.chat_service.get_supabase_client",
        "app.dependencies.get_supabase_client",
    ]

    # 서비스 인스턴스의 캐시된 클라이언트를 mock으로 교체
    original_clients = {
        "product": product_service._client,
        "order": order_service._client,
        "partner": partner_service._client,
        "chat": chat_service._client,
    }
    product_service._client = mock_client
    order_service._client = mock_client
    partner_service._client = mock_client
    chat_service._client = mock_client

    patchers = [patch(target, return_value=mock_client) for target in patch_targets]
    for p in patchers:
        p.start()

    yield mock_client

    # 복원
    for p in patchers:
        p.stop()
    product_service._client = original_clients["product"]
    order_service._client = original_clients["order"]
    partner_service._client = original_clients["partner"]
    chat_service._client = original_clients["chat"]
