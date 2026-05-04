import asyncio
import math
from datetime import datetime, timezone
from typing import Optional
from uuid import UUID

from app.core.supabase import get_supabase_client
from app.schemas.common import PaginationMeta


class ProductService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def table(self):
        return self.client.table("products")

    async def list_products(
        self,
        *,
        seller_id: Optional[UUID] = None,
        category: Optional[str] = None,
        status: Optional[str] = None,
        search: Optional[str] = None,
        max_price: Optional[int] = None,
        min_stock: Optional[int] = None,
        page: int = 1,
        limit: int = 20,
    ) -> tuple[list[dict], PaginationMeta]:
        query = self.table.select("*", count="exact").is_("deleted_at", None)

        if seller_id:
            query = query.eq("seller_id", str(seller_id))
        if category:
            query = query.eq("category", category)
        if status:
            query = query.eq("status", status)
        if search:
            query = query.ilike("name", f"%{search}%")
        if max_price is not None:
            query = query.lte("price_per_unit", max_price)
        if min_stock is not None:
            query = query.gte("stock_quantity", min_stock)

        offset = (page - 1) * limit
        query = query.order("created_at", desc=True).range(offset, offset + limit - 1)

        result = await asyncio.to_thread(lambda: query.execute())
        total = result.count or 0

        meta = PaginationMeta(
            total=total,
            page=page,
            limit=limit,
            total_pages=math.ceil(total / limit) if total > 0 else 0,
        )
        return result.data, meta

    async def get_product(self, product_id: UUID) -> Optional[dict]:
        result = await asyncio.to_thread(
            lambda: self.table.select("*")
            .eq("id", str(product_id))
            .is_("deleted_at", None)
            .execute()
        )
        return result.data[0] if result.data else None

    # ===========================================
    # 상품 상세 페이지 — 한 번의 호출로 join 정보 종합 (B.1, 2026-05-04)
    # ===========================================
    async def get_product_detail(
        self,
        product_id: UUID,
        *,
        current_user_id: UUID,
        current_user_role: str,
    ) -> Optional[dict]:
        """상품 본인 정보 + 판매자 join + (구매자) partner 관계/주문 카운트 + 같은 판매자의 다른 상품.

        시그니처:
          - product_id: 조회 대상
          - current_user_id / current_user_role: 인증 dependency 결과 (구매자면 BUYER)

        반환:
          - 상품이 없거나 soft-deleted 면 None.
          - 그 외 dict — ProductDetailResponse 와 호환되는 키 셋:
              {*ProductResponse fields,
               seller_name, seller_company,
               partner_relationship_status: 'ACTIVE'|'PENDING_OUTGOING'|'PENDING_INCOMING'|'INACTIVE'|None,
               previous_order_count: int (soft-deleted/CANCELLED 제외),
               completed_order_count: int (COMPLETED 만),
               other_seller_products: list[ProductMinimal-like dict]}

        성능 메모:
          - PostgREST 임베딩(`seller:users!seller_id`) 으로 1회에 product+seller 조인.
          - partners / orders / 다른 상품은 현재 user 가 SELLER 본인이면 추가 쿼리 스킵.
          - BUYER 일 땐 partner relationship 1쿼리 + orders 1쿼리 + other products 1쿼리 = 총 4쿼리.
        """
        current_user_id_str = str(current_user_id)

        # 1) 상품 + 판매자 임베딩 조회 (단일 쿼리)
        product_result = await asyncio.to_thread(
            lambda: self.table.select(
                "*, seller:users!seller_id(id, name, company_name, deleted_at)"
            )
            .eq("id", str(product_id))
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        rows = product_result.data or []
        if not rows:
            return None

        product = rows[0]
        seller = product.pop("seller", None) or {}
        seller_id_str = str(product.get("seller_id") or "")

        # 판매자 자체가 soft-deleted 면 비공개 처리 (구매자에게 노출되면 안 됨)
        # SELLER 본인이 자기 상품 조회는 허용
        if seller.get("deleted_at") and current_user_id_str != seller_id_str:
            return None

        product["seller_name"] = seller.get("name")
        product["seller_company"] = seller.get("company_name")

        # 기본값 (SELLER 본인 케이스 / orders 조회 실패 등 모두 일관)
        product["partner_relationship_status"] = None
        product["previous_order_count"] = 0
        product["completed_order_count"] = 0
        product["other_seller_products"] = []

        # 2) BUYER 인 경우만 partner 관계 + 주문 카운트 조회
        # - SELLER 가 본인 상품 보면 불필요 (자기 거래 통계는 별도 페이지에서)
        # - ADMIN 등은 partner 자체 개념이 약하므로 None 유지
        if current_user_role == "BUYER" and seller_id_str:
            # 2a) partner relationship — 본인의 row (user_id=me, partner_user_id=seller)
            try:
                partner_result = await asyncio.to_thread(
                    lambda: self.client.table("partners")
                    .select("status")
                    .eq("user_id", current_user_id_str)
                    .eq("partner_user_id", seller_id_str)
                    .is_("deleted_at", None)
                    .limit(1)
                    .execute()
                )
                if partner_result.data:
                    product["partner_relationship_status"] = partner_result.data[0].get("status")
            except Exception as e:
                # 조회 실패는 상세 응답을 막지 않음 — None 유지
                print(
                    f"[product_service.get_product_detail] partners 조회 실패 (무시): "
                    f"{type(e).__name__}: {e}"
                )

            # 2b) 주문 카운트 — me 가 buyer 이고 seller 가 이 판매자
            try:
                orders_result = await asyncio.to_thread(
                    lambda: self.client.table("orders")
                    .select("id, status")
                    .eq("buyer_id", current_user_id_str)
                    .eq("seller_id", seller_id_str)
                    .is_("deleted_at", None)
                    .neq("status", "CANCELLED")
                    .execute()
                )
                orders = orders_result.data or []
                product["previous_order_count"] = len(orders)
                product["completed_order_count"] = sum(
                    1 for o in orders if o.get("status") == "COMPLETED"
                )
            except Exception as e:
                print(
                    f"[product_service.get_product_detail] orders 카운트 실패 (무시): "
                    f"{type(e).__name__}: {e}"
                )

        # 3) 같은 판매자의 다른 상품 (모든 조회자에게 노출)
        # OUT_OF_STOCK 우선순위 낮춤 — DB 레벨 정렬은 status 문자열 정렬이라 안 맞으므로
        # 8개 가져와서 메모리에서 OUT_OF_STOCK 후순위로 정렬 후 4개 절단.
        try:
            others_result = await asyncio.to_thread(
                lambda: self.table.select(
                    "id, name, category, unit, price_per_unit, "
                    "stock_quantity, status, image_url, created_at"
                )
                .eq("seller_id", seller_id_str)
                .neq("id", str(product_id))
                .is_("deleted_at", None)
                .order("created_at", desc=True)
                .limit(8)
                .execute()
            )
            others_raw = others_result.data or []
            # OUT_OF_STOCK 후순위 정렬 — Python sort 는 stable 이므로 created_at DESC 보존
            others_sorted = sorted(
                others_raw,
                key=lambda p: 1 if (p.get("status") == "OUT_OF_STOCK") else 0,
            )
            product["other_seller_products"] = [
                {
                    "id": p["id"],
                    "name": p.get("name"),
                    "category": p.get("category"),
                    "unit": p.get("unit"),
                    "price_per_unit": p.get("price_per_unit"),
                    "stock_quantity": p.get("stock_quantity"),
                    "status": p.get("status"),
                    "image_url": p.get("image_url"),
                }
                for p in others_sorted[:4]
            ]
        except Exception as e:
            print(
                f"[product_service.get_product_detail] other_products 조회 실패 (무시): "
                f"{type(e).__name__}: {e}"
            )

        return product

    async def create_product(self, seller_id: UUID, data: dict) -> dict:
        payload = {**data, "seller_id": str(seller_id)}
        result = await asyncio.to_thread(lambda: self.table.insert(payload).execute())
        return result.data[0]

    async def update_product(
        self, product_id: UUID, seller_id: UUID, data: dict
    ) -> Optional[dict]:
        # 본인 소유 확인
        update_data = {k: v for k, v in data.items() if v is not None}
        if not update_data:
            return await self.get_product(product_id)

        result = await asyncio.to_thread(
            lambda: self.table.update(update_data)
            .eq("id", str(product_id))
            .eq("seller_id", str(seller_id))
            .execute()
        )
        return result.data[0] if result.data else None

    async def delete_product(self, product_id: UUID, seller_id: UUID) -> bool:
        deleted_at = datetime.now(timezone.utc).isoformat()
        result = await asyncio.to_thread(
            lambda: self.table.update({"deleted_at": deleted_at})
            .eq("id", str(product_id))
            .eq("seller_id", str(seller_id))
            .execute()
        )
        return bool(result.data)


product_service = ProductService()
