"""거래처(Partner) 관련 도구.

도메인 helper:
- _build_partner_response : partner_user 임베딩을 평탄화한 응답 빌더.

Cross-domain 의존 (agent/_shared.py 에서 lazy import):
- _UUID_PATTERN
"""
from __future__ import annotations

from datetime import datetime
from typing import Optional

from app.core.supabase import get_supabase_client

from .._registry import tool


# ─────────────────────────────────────────────
# 도메인 헬퍼
# ─────────────────────────────────────────────

def _build_partner_response(supabase, partner_row: dict) -> dict:
    """본인 row 에 partner_user 임베딩(name/company_name/role/phone)을 붙여 반환.

    partner_service.create_partner 의 응답 형식과 동일하게 맞춘다.
    임베딩 조회 실패 시에는 partner_row 만 반환 (best-effort).
    """
    partner_id = partner_row.get("id")
    if not partner_id:
        return partner_row

    try:
        result = (
            supabase.table("partners")
            .select(
                "*, partner_user:users!partner_user_id(name, company_name, role, phone)"
            )
            .eq("id", partner_id)
            .single()
            .execute()
        )
        row = result.data or partner_row
    except Exception:
        row = partner_row

    partner_user = row.pop("partner_user", None) or {}
    row["partner_name"] = partner_user.get("name")
    row["partner_company"] = partner_user.get("company_name")
    row["partner_role"] = partner_user.get("role")
    row["partner_phone"] = partner_user.get("phone")
    return row


# ─────────────────────────────────────────────
# 대체 거래처 탐색 도구
# ─────────────────────────────────────────────

@tool(
    name="find_alternative_partners",
    description=(
        "재고 부족·협상 결렬·직접 요청 등의 상황에서 대체 거래처를 탐색한다. "
        "BUYER 호출 시: 해당 카테고리 보유 판매자 목록(재고·단가 포함) + 기존 거래 이력(trade_count) 반환. "
        "SELLER 호출 시: 해당 카테고리 주문 이력이 있는 구매자 목록 + 기존 거래 이력 반환. "
        "결과 정렬·추천 순위는 이 tool이 아닌 LLM(response_node)이 자연어로 직접 생성한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "현재 사용자의 UUID (거래 이력 조회 기준)",
            },
            "role": {
                "type": "string",
                "description": "현재 사용자의 역할",
                "enum": ["SELLER", "BUYER"],
            },
            "category": {
                "type": "string",
                "description": "탐색 대상 카테고리. 허용값: FRUIT, VEGETABLE, GRAIN, MUSHROOM, SEAFOOD, MEAT, DAIRY, HERB, LEGUME, ROOT, LEAF, PROCESSED, OTHER",
            },
            "reason": {
                "type": "string",
                "description": "탐색 이유 (선택, 예: '재고 부족', '협상 결렬', '직접 요청'). LLM 추천 문구 생성에 활용됨.",
            },
        },
        "required": ["user_id", "role", "category"],
    },
    groups=("inventory_order",),
)
def find_alternative_partners(
    user_id: str,
    role: str,
    category: str,
    reason: str = "",
) -> dict:
    """대체 거래처를 탐색한다.
    - BUYER 호출: products 테이블에서 해당 카테고리 보유 판매자 + partners 거래 이력(trade_count) 조인
      결과에 stock_quantity, price_per_unit 포함
    - SELLER 호출: orders 테이블에서 해당 카테고리 주문 이력 있는 구매자 + partners 거래 이력
    결과 정렬 공식 적용 금지 — LLM이 추천 순위/이유를 response_node에서 생성한다.
    DB 쿼리 최대 20건 제한.
    반환: {success, alternatives, count}
    """
    try:
        supabase = get_supabase_client()

        if role == "BUYER":
            # 해당 카테고리 상품을 보유한 판매자 목록 조회 (재고 있는 것만)
            prod_result = (
                supabase.table("products")
                .select("seller_id, name, stock_quantity, price_per_unit, unit, status, category")
                .eq("category", category.upper())
                .gt("stock_quantity", 0)
                .is_("deleted_at", None)
                .limit(20)
                .execute()
            )
            products = prod_result.data or []
            # 본인 제외 (BUYER 가 자기 자신을 다시 추천받지 않도록 — 단, role mismatch 시 의미 없음)
            seller_ids = list({
                p["seller_id"] for p in products
                if p.get("seller_id") and p["seller_id"] != user_id
            })

            if not seller_ids:
                return {"success": True, "alternatives": [], "count": 0}

            # 판매자 기본 정보 조회
            users_result = (
                supabase.table("users")
                .select("id, name, company_name, phone, email")
                .in_("id", seller_ids)
                .execute()
            )
            seller_map = {u["id"]: u for u in (users_result.data or [])}

            # orders 테이블에서 seller_id별 거래 건수 / 최근 거래일 동적 집계
            # (취소 제외, 삭제 제외, 최근 100건 제한)
            orders_result = (
                supabase.table("orders")
                .select("seller_id, created_at")
                .in_("seller_id", seller_ids)
                .neq("status", "CANCELLED")
                .is_("deleted_at", None)
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            # Python 단에서 seller_id별 집계
            trade_count_map: dict[str, int] = {}
            last_trade_map: dict[str, str] = {}
            for row in (orders_result.data or []):
                sid = row["seller_id"]
                trade_count_map[sid] = trade_count_map.get(sid, 0) + 1
                if sid not in last_trade_map:
                    last_trade_map[sid] = row["created_at"]

            # seller_id별 대표 상품 하나씩 선택 (stock 최대 기준)
            best_product: dict = {}
            for p in products:
                sid = p["seller_id"]
                if sid not in best_product or p["stock_quantity"] > best_product[sid]["stock_quantity"]:
                    best_product[sid] = p

            alternatives = []
            for sid in seller_ids:
                user_info = seller_map.get(sid, {})
                prod_info = best_product.get(sid, {})
                alternatives.append({
                    "user_id": sid,
                    "name": user_info.get("name", "알 수 없음"),
                    "company_name": user_info.get("company_name", ""),
                    "phone": user_info.get("phone", ""),
                    "email": user_info.get("email", ""),
                    "trade_count": trade_count_map.get(sid, 0),
                    "last_trade_date": last_trade_map.get(sid),
                    "stock_quantity": prod_info.get("stock_quantity", 0),
                    "price_per_unit": prod_info.get("price_per_unit", 0),
                    "unit": prod_info.get("unit", ""),
                    "product_name": prod_info.get("name", ""),
                })

        else:  # SELLER
            # 해당 카테고리 상품을 주문한 이력이 있는 구매자 목록
            prod_result = (
                supabase.table("products")
                .select("id")
                .eq("category", category.upper())
                .execute()
            )
            product_ids = [p["id"] for p in (prod_result.data or [])]
            if not product_ids:
                return {"success": True, "alternatives": [], "count": 0}

            items_result = (
                supabase.table("order_items")
                .select("order_id, orders!inner(buyer_id)")
                .in_("product_id", product_ids)
                .limit(100)
                .execute()
            )
            # 본인 제외 (SELLER 가 자기 자신을 추천받지 않도록 — 단, role mismatch 시 의미 없음)
            buyer_ids = list({
                item["orders"]["buyer_id"]
                for item in (items_result.data or [])
                if item.get("orders")
                and item["orders"].get("buyer_id")
                and item["orders"]["buyer_id"] != user_id
            })[:20]

            if not buyer_ids:
                return {"success": True, "alternatives": [], "count": 0}

            users_result = (
                supabase.table("users")
                .select("id, name, company_name, phone, email")
                .in_("id", buyer_ids)
                .execute()
            )
            buyer_map = {u["id"]: u for u in (users_result.data or [])}

            # orders 테이블에서 buyer_id별 거래 건수 / 최근 거래일 동적 집계
            # (취소 제외, 삭제 제외, 최근 100건 제한)
            orders_result = (
                supabase.table("orders")
                .select("buyer_id, created_at")
                .in_("buyer_id", buyer_ids)
                .neq("status", "CANCELLED")
                .is_("deleted_at", None)
                .order("created_at", desc=True)
                .limit(100)
                .execute()
            )
            # Python 단에서 buyer_id별 집계
            trade_count_map_b: dict[str, int] = {}
            last_trade_map_b: dict[str, str] = {}
            for row in (orders_result.data or []):
                bid = row["buyer_id"]
                trade_count_map_b[bid] = trade_count_map_b.get(bid, 0) + 1
                if bid not in last_trade_map_b:
                    last_trade_map_b[bid] = row["created_at"]

            alternatives = []
            for bid in buyer_ids:
                user_info = buyer_map.get(bid, {})
                alternatives.append({
                    "user_id": bid,
                    "name": user_info.get("name", "알 수 없음"),
                    "company_name": user_info.get("company_name", ""),
                    "phone": user_info.get("phone", ""),
                    "email": user_info.get("email", ""),
                    "trade_count": trade_count_map_b.get(bid, 0),
                    "last_trade_date": last_trade_map_b.get(bid),
                })

        return {
            "success": True,
            "alternatives": alternatives,
            "count": len(alternatives),
        }
    except Exception as e:
        return {"success": False, "error": str(e), "alternatives": [], "count": 0}


# ─────────────────────────────────────────────
# 거래처 등록 도구 (양방향 PENDING — V1.6)
# ─────────────────────────────────────────────

@tool(
    name="request_partner_registration",
    description=(
        "거래처 등록 요청을 상대방에게 보낸다 (양방향 PENDING 모델). "
        "사용자가 '○○를 거래처로 등록해줘', '○○ 추가해줘', '거래처 신청 보내줘', "
        "'○○랑 거래 트고 싶어' 같은 자연어 요청 시 호출. "
        "이 도구는 상대방 user_id(UUID) 를 정확히 아는 경우만 사용한다. "
        "이름/회사명만 알면 request_partner_registration_by_name 을 먼저 사용하거나 "
        "get_user_profile 로 UUID 를 조회한 뒤 호출하라. "
        "성공 시 상대 화면에 PENDING_INCOMING 상태로 보이며, 상대가 수락해야 ACTIVE 거래처가 된다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "신청자(현재 로그인 사용자)의 UUID. 서버에서 현재 user_id 로 강제 주입됨.",
            },
            "target_user_id": {
                "type": "string",
                "description": "거래처로 등록할 상대방 사용자의 UUID. 자기 자신 UUID 는 거부됨.",
            },
            "note": {
                "type": "string",
                "description": "본인 row 에 저장될 메모 (선택). 예: '경북 청송 사과 거래용'.",
            },
        },
        "required": ["target_user_id"],
    },
    groups=("inventory_order",),
)
def request_partner_registration(
    user_id: str,
    target_user_id: str,
    note: Optional[str] = None,
) -> dict:
    """거래처 등록 요청을 상대방에게 보낸다 (양방향 PENDING).

    이 도구는 상대방 사용자 UUID 가 정확히 알려진 경우에만 호출한다.
    이름/회사명만 알면 먼저 request_partner_registration_by_name 도구를 사용하거나,
    get_user_profile 로 UUID 를 조회한 뒤 호출하라.

    동작 (partner_service.create_partner 와 동일):
      - 본인 row(PENDING_OUTGOING) + 상대 row(PENDING_INCOMING) 두 row 동시 INSERT
      - 상대가 POST /partners/{id}/accept 호출 시 양쪽 ACTIVE 로 전환
      - notes 는 본인 row 에만 적용 (상대 row 는 빈 값)

    반환:
      - 성공: {"success": True, "partner_id": "...", "status": "PENDING_OUTGOING",
              "partner_name": "...", "partner_company": "...", "message": "..."}
      - 자기 자신: {"success": False, "error": "self_registration_not_allowed", ...}
      - 이미 등록됨/요청 중: {"success": False, "error": "already_partner", ...}
      - 상대방 없음: {"success": False, "error": "user_not_found", ...}
    """
    from .._shared import _UUID_PATTERN

    # 입력 검증
    user_id_str = (user_id or "").strip()
    target_id_str = (target_user_id or "").strip()

    if not user_id_str or not _UUID_PATTERN.match(user_id_str):
        return {
            "success": False,
            "error": "invalid_user_id",
            "detail": "요청자 UUID 가 유효하지 않습니다.",
        }
    if not target_id_str or not _UUID_PATTERN.match(target_id_str):
        return {
            "success": False,
            "error": "invalid_target_user_id",
            "detail": (
                "상대방 UUID 가 유효하지 않습니다. "
                "이름/회사명으로만 알고 있다면 request_partner_registration_by_name 도구를 사용하세요."
            ),
        }

    # 자기 자신 거래처 등록 차단
    if user_id_str == target_id_str:
        return {
            "success": False,
            "error": "self_registration_not_allowed",
            "detail": "자기 자신을 거래처로 등록할 수 없습니다.",
        }

    try:
        supabase = get_supabase_client()

        # 상대방 존재 + soft-delete 확인
        target_result = (
            supabase.table("users")
            .select("id, name, company_name, role")
            .eq("id", target_id_str)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if not target_result.data:
            return {
                "success": False,
                "error": "user_not_found",
                "detail": "상대방 사용자를 찾을 수 없습니다.",
            }
        target = target_result.data[0]
        target_name = target.get("name") or target.get("company_name") or "상대방"

        # 기존 active row(ACTIVE / PENDING_*) 사전 체크 — partial unique index 충돌 방지
        existing = (
            supabase.table("partners")
            .select("id, status")
            .eq("user_id", user_id_str)
            .eq("partner_user_id", target_id_str)
            .is_("deleted_at", None)
            .limit(1)
            .execute()
        )
        if existing.data:
            existing_row = existing.data[0]
            return {
                "success": False,
                "error": "already_partner",
                "detail": (
                    f"이미 거래처입니다 (status={existing_row.get('status')}). "
                    "거래처 목록에서 확인해 주세요."
                ),
                "partner_id": existing_row.get("id"),
                "partner_status": existing_row.get("status"),
            }

        # 본인 row INSERT (PENDING_OUTGOING)
        outgoing_payload = {
            "user_id": user_id_str,
            "partner_user_id": target_id_str,
            "status": "PENDING_OUTGOING",
            "notes": note,
        }
        try:
            outgoing_result = (
                supabase.table("partners").insert(outgoing_payload).execute()
            )
        except Exception as e:
            err_msg = str(e)
            if "23505" in err_msg or "duplicate" in err_msg.lower():
                return {
                    "success": False,
                    "error": "already_partner",
                    "detail": "이미 등록되었거나 요청 중인 거래처입니다.",
                }
            return {
                "success": False,
                "error": "insert_failed",
                "detail": f"본인 row INSERT 실패: {type(e).__name__}: {e}",
            }

        if not outgoing_result.data:
            return {
                "success": False,
                "error": "insert_failed",
                "detail": "본인 row INSERT 결과가 비어있습니다.",
            }
        outgoing_row = outgoing_result.data[0]
        outgoing_id = outgoing_row["id"]

        # 상대 row INSERT (PENDING_INCOMING) — 실패 시 본인 row hard-delete 보상
        incoming_payload = {
            "user_id": target_id_str,
            "partner_user_id": user_id_str,
            "status": "PENDING_INCOMING",
        }
        try:
            incoming_result = (
                supabase.table("partners").insert(incoming_payload).execute()
            )
            if not incoming_result.data:
                raise RuntimeError("상대 row INSERT 결과가 비어있습니다.")
        except Exception as e:
            # 보상: 본인 row hard-delete
            try:
                supabase.table("partners").delete().eq("id", outgoing_id).execute()
            except Exception as rollback_err:
                print(
                    f"[request_partner_registration] rollback 실패 "
                    f"outgoing_id={outgoing_id}: "
                    f"{type(rollback_err).__name__}: {rollback_err}"
                )
            err_msg = str(e)
            if "23505" in err_msg or "duplicate" in err_msg.lower():
                return {
                    "success": False,
                    "error": "already_partner",
                    "detail": "상대방과 이미 거래처 관계가 존재합니다.",
                }
            return {
                "success": False,
                "error": "insert_failed",
                "detail": f"상대 row INSERT 실패: {type(e).__name__}: {e}",
            }

        # 응답 — partner_user 임베딩 포함
        enriched = _build_partner_response(supabase, outgoing_row)

        return {
            "success": True,
            "partner_id": enriched.get("id"),
            "status": enriched.get("status", "PENDING_OUTGOING"),
            "partner_name": enriched.get("partner_name") or target_name,
            "partner_company": enriched.get("partner_company"),
            "partner_role": enriched.get("partner_role"),
            "message": (
                f"{target_name} 님에게 거래처 등록 요청을 보냈습니다. "
                "상대가 수락하면 거래처 목록에 활성 상태로 표시됩니다."
            ),
        }

    except Exception as e:
        return {
            "success": False,
            "error": "unexpected_error",
            "detail": f"{type(e).__name__}: {e}",
        }


@tool(
    name="request_partner_registration_by_name",
    description=(
        "이름이나 회사명으로 거래처 등록 요청을 보낸다. "
        "사용자가 '행복농산을 거래처로 등록해줘', '김철수님 거래처 추가' 처럼 "
        "UUID 가 아닌 이름/업체명만 말한 경우 사용한다. "
        "내부적으로 사용자 검색을 거쳐 단일 매칭이면 즉시 신청, 다중 매칭이면 "
        "needs_confirmation=true 응답으로 후보 리스트를 반환한다 — "
        "이 경우 사용자에게 어느 분인지 확인받은 뒤 request_partner_registration 으로 "
        "user_id 를 직접 지정해 다시 호출하라. "
        "절대 보내지 말 것: needs_confirmation=true 인데 '등록했습니다' 라고 답변하면 거짓 보고가 된다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "신청자(현재 로그인 사용자)의 UUID. 서버에서 현재 user_id 로 강제 주입됨.",
            },
            "target_name_or_company": {
                "type": "string",
                "description": "거래처로 등록할 상대방의 이름 또는 회사명 (부분 일치 검색).",
            },
            "note": {
                "type": "string",
                "description": "본인 row 에 저장될 메모 (선택).",
            },
        },
        "required": ["target_name_or_company"],
    },
    groups=("inventory_order",),
)
def request_partner_registration_by_name(
    user_id: str,
    target_name_or_company: str,
    note: Optional[str] = None,
) -> dict:
    """이름/회사명으로 거래처 등록 요청.

    내부적으로 사용자를 검색해 단일 매칭이면 즉시 신청, 다중 매칭이면
    confirmation 응답을 반환한다 (send_chat_message 의 needs_confirmation 패턴).

    검색 조건:
      - users.name ilike '%{target}%' 또는 company_name ilike '%{target}%'
      - is_active=true, deleted_at IS NULL
      - 본인 제외

    반환:
      - 단일 매칭 + 신청 성공: request_partner_registration 응답과 동일
      - 다중 매칭: {"success": False, "needs_confirmation": True,
                  "candidates": [{user_id, name, company_name, role}, ...]}
      - 0건: {"success": False, "error": "no_match", "detail": "○○ 님을 찾을 수 없습니다"}
      - 자기 자신 매칭: {"success": False, "error": "self_registration_not_allowed", ...}
    """
    from .._shared import _UUID_PATTERN

    user_id_str = (user_id or "").strip()
    query_str = (target_name_or_company or "").strip()

    if not user_id_str or not _UUID_PATTERN.match(user_id_str):
        return {
            "success": False,
            "error": "invalid_user_id",
            "detail": "요청자 UUID 가 유효하지 않습니다.",
        }
    if not query_str:
        return {
            "success": False,
            "error": "missing_target",
            "detail": "거래처로 등록할 상대방의 이름이나 회사명을 알려주세요.",
        }

    try:
        supabase = get_supabase_client()

        # 이름/회사명 OR 검색 (본인 제외)
        result = (
            supabase.table("users")
            .select("id, name, company_name, role")
            .or_(
                f"name.ilike.%{query_str}%,"
                f"company_name.ilike.%{query_str}%"
            )
            .neq("id", user_id_str)
            .eq("is_active", True)
            .is_("deleted_at", None)
            .limit(10)
            .execute()
        )
        candidates = result.data or []

        if not candidates:
            return {
                "success": False,
                "error": "no_match",
                "detail": f"'{query_str}' 님을 찾을 수 없습니다.",
            }

        if len(candidates) >= 2:
            return {
                "success": False,
                "needs_confirmation": True,
                "candidates": [
                    {
                        "user_id": c["id"],
                        "name": c.get("name"),
                        "company_name": c.get("company_name"),
                        "role": c.get("role"),
                    }
                    for c in candidates
                ],
                "message": (
                    f"'{query_str}' 와 일치하는 사용자가 {len(candidates)} 명 있습니다. "
                    "어느 분을 거래처로 등록할지 확인 후 user_id 를 직접 지정해 "
                    "request_partner_registration 도구로 다시 호출하세요."
                ),
            }

        # 단일 매칭 → 즉시 신청
        target = candidates[0]
        return request_partner_registration(
            user_id=user_id_str,
            target_user_id=target["id"],
            note=note,
        )

    except Exception as e:
        return {
            "success": False,
            "error": "unexpected_error",
            "detail": f"{type(e).__name__}: {e}",
        }


@tool(
    name="get_partners",
    description=(
        "사용자의 현재 거래처 목록을 조회한다. status 또는 status_in 으로 필터 가능. "
        "기본값은 ACTIVE — 사용자가 '내 거래처', '거래처 목록', '거래 중인 곳', "
        "'거래하고 있는 거래처', '거래처 보여줘', '내가 거래하는 사람들' 같이 자연어로 물으면 호출. "
        "PENDING_OUTGOING 은 내가 보낸 신청('내가 신청한 거래처', '보낸 요청'), "
        "PENDING_INCOMING 은 받은 신청('받은 거래처 요청' — 단, 들어온 요청만 단독 조회 시엔 "
        "get_incoming_partner_requests 사용 권장), INACTIVE 는 거래 종료된 거래처. "
        "사용자가 명시하지 않은 상태는 추가하지 말 것. "
        "도구 결과 외 임의 정보 늘어놓기 금지. 결과 0건이면 '현재 활성 거래처가 없습니다' 만 안내."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {
                "type": "string",
                "description": "현재 로그인 사용자 UUID",
            },
            "status": {
                "type": "string",
                "description": (
                    "단일 상태 필터 (선택). 미지정 시 ACTIVE 기본. "
                    "status_in 과 동시 지정 시 status_in 이 우선."
                ),
                "enum": [
                    "ACTIVE",
                    "PENDING_OUTGOING",
                    "PENDING_INCOMING",
                    "INACTIVE",
                ],
            },
            "status_in": {
                "type": "array",
                "items": {
                    "type": "string",
                    "enum": [
                        "ACTIVE",
                        "PENDING_OUTGOING",
                        "PENDING_INCOMING",
                        "INACTIVE",
                    ],
                },
                "description": (
                    "다중 상태 필터 (선택). 사용자가 '진행 중인 거래처와 보낸 요청 둘 다' "
                    "처럼 명시적으로 여러 상태를 한꺼번에 물을 때만 사용."
                ),
            },
        },
        "required": ["user_id"],
    },
    groups=("inventory_order",),
)
def get_partners(
    user_id: str,
    status: Optional[str] = None,
    status_in: Optional[list[str]] = None,
) -> dict:
    """현재 거래처 목록 조회.

    status (단일) 또는 status_in (배열) 으로 필터링.
    가능한 status: ACTIVE, PENDING_OUTGOING, PENDING_INCOMING, INACTIVE
      (REJECTED 는 partners 스키마에 없어 0건 반환됨 — 거절 시 soft-delete 처리됨)
    상태 미지정 시 ACTIVE 만 기본 (사용자 의도가 보통 '활성 거래처').

    내부적으로 partner_service.list_partners 에 위임 (limit=200 으로 1페이지 조회).
    응답 row 는 partner_user 임베딩이 평탄화된 형태:
      {id, user_id, partner_user_id, status, nickname, notes,
       partner_name, partner_company, partner_role, partner_phone,
       created_at, updated_at, ...}
    """
    from .._shared import _UUID_PATTERN

    user_clean = (user_id or "").strip()
    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {
            "success": False,
            "error": "invalid_user_id",
            "partners": [],
            "count": 0,
        }

    # status_in 우선 적용 — 배열이면 status 단일 필터를 무시하고 OR 조회.
    # supabase-py 는 in_() 를 지원 — partner_service.list_partners 가 단일 status 만
    # 지원하므로, status_in 이 들어오면 직접 supabase 쿼리로 처리한다.
    requested_status_list: Optional[list[str]] = None
    if status_in and isinstance(status_in, list) and len(status_in) > 0:
        requested_status_list = [s for s in status_in if isinstance(s, str) and s]
    elif status and isinstance(status, str):
        requested_status_list = [status]
    else:
        # 기본값 — 활성 거래처만
        requested_status_list = ["ACTIVE"]

    try:
        supabase = get_supabase_client()

        # 임베디드 조인 — partner_service.list_partners 와 동일한 패턴.
        query = (
            supabase.table("partners")
            .select(
                "*, partner_user:users!partner_user_id(name, company_name, role, phone)"
            )
            .eq("user_id", user_clean)
            .is_("deleted_at", None)
        )

        # 단일 vs 다중 필터 분기
        if len(requested_status_list) == 1:
            query = query.eq("status", requested_status_list[0])
        else:
            query = query.in_("status", requested_status_list)

        # 최신 순, 도구 응답은 1페이지 200건 한도
        result = query.order("created_at", desc=True).limit(200).execute()
        rows = result.data or []

        partners: list[dict] = []
        for row in rows:
            partner_user = row.pop("partner_user", None) or {}
            row["partner_name"] = partner_user.get("name")
            row["partner_company"] = partner_user.get("company_name")
            row["partner_role"] = partner_user.get("role")
            row["partner_phone"] = partner_user.get("phone")
            partners.append(row)

        return {
            "success": True,
            "partners": partners,
            "count": len(partners),
            "filter_status": requested_status_list,
        }
    except Exception as e:
        return {
            "success": False,
            "error": str(e),
            "partners": [],
            "count": 0,
        }


@tool(
    name="get_incoming_partner_requests",
    description=(
        "내게 들어온 PENDING_INCOMING 거래처 등록 요청 목록을 조회한다. "
        "'들어온 거래처 요청 있어?', '거래처 신청 왔어?', '거래처 요청 확인해줘' 같은 요청 시 호출."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "현재 로그인 사용자 UUID"},
        },
        "required": ["user_id"],
    },
    groups=("inventory_order",),
)
def get_incoming_partner_requests(user_id: str) -> dict:
    """내게 들어온 PENDING_INCOMING 거래처 등록 요청 목록을 반환한다."""
    from .._shared import _UUID_PATTERN

    user_clean = (user_id or "").strip()
    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id"}
    try:
        supabase = get_supabase_client()
        result = supabase.table("partners") \
            .select("id, partner_user_id, status, notes, created_at, users!partners_partner_user_id_fkey(name, company_name, role)") \
            .eq("user_id", user_clean) \
            .eq("status", "PENDING_INCOMING") \
            .is_("deleted_at", None) \
            .execute()
        requests = []
        for row in (result.data or []):
            partner_user = row.get("users") or {}
            requests.append({
                "partner_id": row["id"],
                "from_user_id": row["partner_user_id"],
                "from_name": partner_user.get("name", ""),
                "from_company": partner_user.get("company_name", ""),
                "from_role": partner_user.get("role", ""),
                "created_at": row.get("created_at", ""),
            })
        return {"success": True, "requests": requests, "count": len(requests)}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="accept_partner_request",
    description=(
        "들어온 거래처 등록 요청을 수락한다. "
        "'거래처 요청 수락해줘', '○○ 거래처 수락', '승인해줘' 같은 요청 시 호출. "
        "partner_id 를 모르면 get_incoming_partner_requests 로 먼저 조회하라. "
        "중요: partner_id 는 get_incoming_partner_requests 결과의 'partner_id' 필드값을 사용한다. "
        "'from_user_id' 필드가 아님에 주의."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "현재 로그인 사용자 UUID"},
            "partner_id": {"type": "string", "description": "수락할 partners 테이블 row UUID. get_incoming_partner_requests 결과의 'partner_id' 필드값. 'from_user_id' 가 아님."},
        },
        "required": ["user_id", "partner_id"],
    },
    groups=("inventory_order",),
)
def accept_partner_request(user_id: str, partner_id: str) -> dict:
    """들어온 거래처 등록 요청을 수락한다. partner_id는 partners 테이블 row UUID."""
    from .._shared import _UUID_PATTERN

    user_clean = (user_id or "").strip()
    partner_clean = (partner_id or "").strip()
    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id"}
    if not partner_clean or not _UUID_PATTERN.match(partner_clean):
        return {"success": False, "error": "invalid_partner_id", "message": "partner_id가 필요합니다. get_incoming_partner_requests로 먼저 조회하세요."}
    try:
        supabase = get_supabase_client()
        # 본인 row 확인
        my_row = supabase.table("partners").select("*").eq("id", partner_clean).eq("user_id", user_clean).is_("deleted_at", None).single().execute().data
        if not my_row:
            return {"success": False, "error": "not_found", "message": "해당 거래처 요청을 찾을 수 없습니다."}
        if my_row.get("status") != "PENDING_INCOMING":
            return {"success": False, "error": "invalid_status", "message": f"수락할 수 없는 상태입니다: {my_row.get('status')}"}
        # 양쪽 ACTIVE 전환
        supabase.table("partners").update({"status": "ACTIVE"}).eq("id", partner_clean).execute()
        supabase.table("partners").update({"status": "ACTIVE"}) \
            .eq("user_id", my_row["partner_user_id"]).eq("partner_user_id", user_clean).is_("deleted_at", None).execute()
        return {"success": True, "message": "거래처 등록 요청을 수락했습니다. 이제 거래처 목록에서 확인할 수 있습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="reject_partner_request",
    description=(
        "들어온 거래처 등록 요청을 거절한다. "
        "'거래처 요청 거절해줘', '○○ 거래처 거절', '거절해줘' 같은 요청 시 호출. "
        "partner_id 를 모르면 get_incoming_partner_requests 로 먼저 조회하라."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "현재 로그인 사용자 UUID"},
            "partner_id": {"type": "string", "description": "거절할 partners 테이블 row UUID"},
        },
        "required": ["user_id", "partner_id"],
    },
    groups=("inventory_order",),
)
def reject_partner_request(user_id: str, partner_id: str) -> dict:
    """들어온 거래처 등록 요청을 거절한다. partner_id는 partners 테이블 row UUID."""
    from .._shared import _UUID_PATTERN

    user_clean = (user_id or "").strip()
    partner_clean = (partner_id or "").strip()
    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id"}
    if not partner_clean or not _UUID_PATTERN.match(partner_clean):
        return {"success": False, "error": "invalid_partner_id", "message": "partner_id가 필요합니다. get_incoming_partner_requests로 먼저 조회하세요."}
    try:
        supabase = get_supabase_client()
        my_row = supabase.table("partners").select("*").eq("id", partner_clean).eq("user_id", user_clean).is_("deleted_at", None).single().execute().data
        if not my_row:
            return {"success": False, "error": "not_found", "message": "해당 거래처 요청을 찾을 수 없습니다."}
        if my_row.get("status") != "PENDING_INCOMING":
            return {"success": False, "error": "invalid_status", "message": f"거절할 수 없는 상태입니다: {my_row.get('status')}"}
        now = datetime.utcnow().isoformat()
        supabase.table("partners").update({"deleted_at": now}).eq("id", partner_clean).execute()
        supabase.table("partners").update({"deleted_at": now}) \
            .eq("user_id", my_row["partner_user_id"]).eq("partner_user_id", user_clean).is_("deleted_at", None).execute()
        return {"success": True, "message": "거래처 등록 요청을 거절했습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}


@tool(
    name="delete_partner",
    description=(
        "활성 거래처 관계를 삭제(해제)한다. "
        "'거래처 삭제해줘', '○○ 거래처 끊어줘', '거래처 해제해줘', '거래처 없애줘' 같은 요청 시 호출. "
        "partner_id 를 모르면 get_partners 로 먼저 조회하여 id를 확인하라. "
        "양측 row 를 모두 soft-delete 한다."
    ),
    parameters={
        "type": "object",
        "properties": {
            "user_id": {"type": "string", "description": "현재 로그인 사용자 UUID"},
            "partner_id": {"type": "string", "description": "삭제할 partners 테이블 row UUID"},
        },
        "required": ["user_id", "partner_id"],
    },
    groups=("inventory_order",),
)
def delete_partner(user_id: str, partner_id: str) -> dict:
    """활성 거래처를 soft-delete. 양측(내 row + 상대방 row) 모두 deleted_at 설정."""
    from .._shared import _UUID_PATTERN

    user_clean = (user_id or "").strip()
    partner_clean = (partner_id or "").strip()
    if not user_clean or not _UUID_PATTERN.match(user_clean):
        return {"success": False, "error": "invalid_user_id"}
    if not partner_clean or not _UUID_PATTERN.match(partner_clean):
        return {"success": False, "error": "invalid_partner_id", "message": "partner_id가 필요합니다. get_partners로 먼저 조회하세요."}
    try:
        supabase = get_supabase_client()
        my_row = (
            supabase.table("partners")
            .select("*")
            .eq("id", partner_clean)
            .eq("user_id", user_clean)
            .is_("deleted_at", None)
            .single()
            .execute()
            .data
        )
        if not my_row:
            return {"success": False, "error": "not_found", "message": "해당 거래처를 찾을 수 없습니다."}
        now = datetime.utcnow().isoformat()
        supabase.table("partners").update({"deleted_at": now}).eq("id", partner_clean).execute()
        supabase.table("partners").update({"deleted_at": now}) \
            .eq("user_id", my_row["partner_user_id"]).eq("partner_user_id", user_clean).is_("deleted_at", None).execute()
        partner_name = my_row.get("partner_name") or my_row.get("partner_user_id", "")
        return {"success": True, "message": f"거래처 '{partner_name}'를 삭제했습니다."}
    except Exception as e:
        return {"success": False, "error": str(e)}
