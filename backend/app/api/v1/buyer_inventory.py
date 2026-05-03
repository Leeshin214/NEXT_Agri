"""구매자(BUYER) 재고 API.

엔드포인트 4개 — POST 는 없음 (자동 누적):
- GET    /buyer/inventory                — 본인 재고 목록 (search/product_id/sort_by)
- GET    /buyer/inventory/{inventory_id} — 단건 상세
- PATCH  /buyer/inventory/{inventory_id} — 수량/메모 수동 조정
- DELETE /buyer/inventory/{inventory_id} — soft delete (목록에서 숨김)

INSERT/누적은 order_service.update_status 의 COMPLETED 분기에서 자동 실행
(_add_buyer_inventory_for_order). 사용자가 수동 INSERT 할 수 없도록 POST 미노출.
"""

from typing import Optional
from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from app.dependencies import require_buyer
from app.schemas.buyer_inventory import (
    BuyerInventoryResponse,
    BuyerInventoryUpdate,
)
from app.schemas.common import SuccessResponse
from app.services.buyer_inventory_service import buyer_inventory_service


router = APIRouter(prefix="/buyer/inventory", tags=["buyer_inventory"])


@router.get(
    "",
    response_model=SuccessResponse[list[BuyerInventoryResponse]],
)
async def list_inventory(
    search: Optional[str] = Query(None, description="상품명(products.name) ilike 검색"),
    product_id: Optional[UUID] = Query(
        None, description="특정 상품 한정 — 보통 같은 product 의 누적 history 확인용"
    ),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=200),
    sort_by: str = Query(
        "recent",
        description="recent(기본, last_added_at DESC) | quantity(quantity DESC) | name(상품명 ASC)",
    ),
    current_user: dict = Depends(require_buyer),
):
    """본인(BUYER) 재고 목록 + meta(페이지네이션)."""
    rows, meta = await buyer_inventory_service.list_buyer_inventory(
        buyer_id=current_user["id"],
        search=search,
        product_id=product_id,
        page=page,
        limit=limit,
        sort_by=sort_by,
    )
    return {"data": rows, "meta": meta.model_dump()}


@router.get(
    "/{inventory_id}",
    response_model=SuccessResponse[BuyerInventoryResponse],
)
async def get_inventory(
    inventory_id: UUID,
    current_user: dict = Depends(require_buyer),
):
    """본인 재고 단건 상세. 다른 buyer 의 row 는 404."""
    row = await buyer_inventory_service.get_buyer_inventory(
        buyer_id=current_user["id"],
        inventory_id=inventory_id,
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="재고 항목을 찾을 수 없습니다.",
        )
    return {"data": row}


@router.patch(
    "/{inventory_id}",
    response_model=SuccessResponse[BuyerInventoryResponse],
)
async def update_inventory(
    inventory_id: UUID,
    data: BuyerInventoryUpdate,
    current_user: dict = Depends(require_buyer),
):
    """수량/메모 수동 조정. 본인 재고만, soft-deleted 행은 404."""
    # mode="json": 미래 date/UUID 필드 추가 시 회귀 방지 일관성 유지
    row = await buyer_inventory_service.update_buyer_inventory(
        buyer_id=current_user["id"],
        inventory_id=inventory_id,
        payload=data.model_dump(exclude_unset=True, mode="json"),
    )
    if not row:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="재고 항목을 찾을 수 없습니다.",
        )
    return {"data": row}


@router.delete("/{inventory_id}", status_code=204)
async def delete_inventory(
    inventory_id: UUID,
    current_user: dict = Depends(require_buyer),
):
    """본인 재고 soft delete (목록 숨김).

    같은 (buyer_id, product_id) 로 다음 주문 COMPLETED 시 새 active row 가
    자동 생성되므로, 사용자가 의도적으로 hide 한 row 가 다시 살아나지는 않는다.
    """
    deleted = await buyer_inventory_service.delete_buyer_inventory(
        buyer_id=current_user["id"],
        inventory_id=inventory_id,
    )
    if not deleted:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="재고 항목을 찾을 수 없습니다.",
        )
