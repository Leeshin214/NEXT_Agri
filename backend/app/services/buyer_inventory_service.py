"""구매자(BUYER) 재고 서비스 — 자동 누적은 order_service 가 담당, 본 모듈은 조회/수정/삭제만.

- list_buyer_inventory: products + sellers 임베딩 join, soft-delete 제외, 페이지네이션
- get_buyer_inventory: 단건 조회 + 본인 소유 검증
- update_buyer_inventory: quantity / notes 수정
- delete_buyer_inventory: soft delete (목록에서 숨김)
"""

import asyncio
import logging
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta


logger = logging.getLogger(__name__)


# PostgREST 임베딩 — products + sellers (3-depth)
# product:products.image_url 까지 평탄화 응답에 노출.
# seller:users 는 products.seller_id FK 가 column-alias 로 자동 추론됨.
INVENTORY_SELECT_WITH_JOINS = (
    "*,"
    "product:products("
    "name,category,image_url,deleted_at,"
    "seller:users!seller_id(name,company_name,deleted_at)"
    ")"
)


def _flatten_inventory_row(row: dict) -> dict:
    """PostgREST 임베딩 응답을 BuyerInventoryResponse 평탄 구조로 변환.

    임베딩이 None(상품/판매자 soft-delete 등) 이면 빈 dict 처리해 None 으로 채움.
    상품/판매자 soft-delete 자체는 응답에서 막지 않는다 — 사용자는 자기 재고 row 를
    그대로 볼 수 있어야 하므로 (이력 보존). 단지 join 필드가 None 으로 나갈 뿐.
    """
    product = row.pop("product", None) or {}
    seller = product.pop("seller", None) or {} if product else {}

    # product 자체가 soft-delete 되었으면 임베딩 필드 모두 None
    product_deleted = bool(product.get("deleted_at"))
    seller_deleted = bool(seller.get("deleted_at"))

    row["product_name"] = None if product_deleted else product.get("name")
    row["product_category"] = None if product_deleted else product.get("category")
    row["product_image_url"] = None if product_deleted else product.get("image_url")
    row["seller_name"] = None if (product_deleted or seller_deleted) else seller.get("name")
    row["seller_company"] = (
        None if (product_deleted or seller_deleted) else seller.get("company_name")
    )
    return row


class BuyerInventoryService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("buyer_inventories")

    # ===========================================
    # list_buyer_inventory — 본인 재고 목록 (검색 / product_id 필터 / 페이지)
    # ===========================================
    async def list_buyer_inventory(
        self,
        *,
        buyer_id: UUID | str,
        search: Optional[str] = None,
        product_id: Optional[UUID | str] = None,
        page: int = 1,
        limit: int = 20,
        sort_by: str = "recent",
    ) -> tuple[list[dict], PaginationMeta]:
        """본인 재고 목록.

        - search: products.name ilike 검색 (PostgREST 임베딩 컬럼 ilike 패턴)
        - product_id: 특정 상품 한정
        - sort_by:
            "recent"   — last_added_at DESC (NULLS LAST)
            "quantity" — quantity DESC
            "name"     — products.name ASC (임베딩 컬럼 정렬)
            기타 값은 "recent" 폴백.
        """
        buyer_id_str = str(buyer_id)

        query = (
            self.table.select(INVENTORY_SELECT_WITH_JOINS, count="exact")
            .eq("buyer_id", buyer_id_str)
            .is_("deleted_at", None)
        )

        if product_id is not None:
            query = query.eq("product_id", str(product_id))

        if search:
            # PostgREST 임베딩 컬럼 검색 — products.name 에 ilike
            # foreignTable 인자로 임베딩 측 필터 적용 가능
            query = query.ilike("product.name", f"%{search}%")

        # 정렬
        if sort_by == "quantity":
            query = query.order("quantity", desc=True)
        elif sort_by == "name":
            # 임베딩 컬럼 정렬 — products.name ASC
            query = query.order("name", desc=False, foreign_table="product")
        else:  # "recent" 또는 fallback
            query = query.order("last_added_at", desc=True, nullsfirst=False)

        offset = (page - 1) * limit
        query = query.range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0
        rows = [_flatten_inventory_row(r) for r in (result.data or [])]

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return rows, meta

    # ===========================================
    # get_buyer_inventory — 단건 조회 + 본인 소유 검증
    # ===========================================
    async def get_buyer_inventory(
        self, *, buyer_id: UUID | str, inventory_id: UUID | str
    ) -> Optional[dict]:
        """본인 재고 단건. 다른 buyer 의 row 는 None 반환 (라우터에서 404)."""
        result = await asyncio.to_thread(
            lambda: self.table.select(INVENTORY_SELECT_WITH_JOINS)
            .eq("id", str(inventory_id))
            .eq("buyer_id", str(buyer_id))
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        rows = result.data or []
        if not rows:
            return None
        return _flatten_inventory_row(rows[0])

    # ===========================================
    # update_buyer_inventory — quantity / notes 수정
    # ===========================================
    async def update_buyer_inventory(
        self,
        *,
        buyer_id: UUID | str,
        inventory_id: UUID | str,
        payload: dict,
    ) -> Optional[dict]:
        """본인 재고 수량/메모 수정.

        payload 에서 None 값은 제외 (미전달 = 변경 안 함).
        업데이트 후 임베딩 join 결과를 다시 조회해 반환.
        """
        update_fields = {k: v for k, v in payload.items() if v is not None}
        if not update_fields:
            # 변경 없음 — 그냥 현재 row 반환
            return await self.get_buyer_inventory(
                buyer_id=buyer_id, inventory_id=inventory_id
            )

        # 사전 존재/권한 확인 (supabase-py update().execute() 응답 비신뢰 패턴 회피)
        pre = await asyncio.to_thread(
            lambda: self.table.select("id")
            .eq("id", str(inventory_id))
            .eq("buyer_id", str(buyer_id))
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not (pre.data or []):
            return None

        await asyncio.to_thread(
            lambda: self.table.update(update_fields)
            .eq("id", str(inventory_id))
            .eq("buyer_id", str(buyer_id))
            .is_("deleted_at", None)
            .execute()
        )

        # 재조회 — 임베딩 join 갱신된 결과 반환
        return await self.get_buyer_inventory(
            buyer_id=buyer_id, inventory_id=inventory_id
        )

    # ===========================================
    # delete_buyer_inventory — soft delete
    # ===========================================
    async def delete_buyer_inventory(
        self, *, buyer_id: UUID | str, inventory_id: UUID | str
    ) -> bool:
        """본인 재고 soft delete (목록에서 숨김).

        - 멱등성: 이미 deleted_at 인 row 는 .is_("deleted_at", None) 필터로 차단되어 False 반환.
        - 같은 (buyer_id, product_id) 로 다음 주문 COMPLETED 시 새 row 가 자동 생성됨
          (partial unique index 가 deleted_at IS NULL 만 적용하므로).
        """
        deleted_at = datetime.now(timezone.utc).isoformat()

        # 사전 존재 확인 (update().execute() 응답 비신뢰 패턴 회피)
        pre = await asyncio.to_thread(
            lambda: self.table.select("id")
            .eq("id", str(inventory_id))
            .eq("buyer_id", str(buyer_id))
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not (pre.data or []):
            return False

        await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(inventory_id))
            .eq("buyer_id", str(buyer_id))
            .is_("deleted_at", None)
            .execute()
        )
        return True


buyer_inventory_service = BuyerInventoryService()
