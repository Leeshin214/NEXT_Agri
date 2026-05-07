"""대체 거래처(판매자) 자동 추천 + 자동 견적 주문 생성 서비스.

판매자가 활성 주문을 취소했을 때 (order_service.cancel_order, role=SELLER) 백그라운드에서
호출되어 다음을 수행한다:

  1) 취소된 주문의 첫 번째 item 의 product 와 동일 카테고리·다른 판매자의 활성 상품 조회.
  2) LLM 으로 "본질 상품 동일성" 판별 — '창원 감자' / '여주 감자' 처럼 이름은 달라도
     실제 같은 품목이면 통과, 'OTHER' 카테고리 안에서 잡상품이 섞이는 케이스 등은 차단.
  3) 재고 충분 + 가격 합리성 기준 상위 3개 판매자 선정.
  4) 각 판매자에게 원래 주문의 quantity / unit_price / delivery_date / delivery_address 를
     그대로 복사해 새 QUOTE_REQUESTED 주문 자동 생성 (order_service.create_order).
  5) alternative_partner_recommendations 테이블에 결과 UPSERT.
  6) 구매자에게 ALTERNATIVE_PARTNERS 알림 emit (link_url → 주문 상세 패널).

설계 원칙:
  - 모든 단계가 fire-and-forget. 어떤 단계 실패도 호출처(cancel_order) 트랜잭션을
    절대 막지 않는다 (notification_service.emit 와 동일 패턴).
  - LLM 호출 실패 시 fallback: 상품명 정규화(공백/대소문자) 후 부분 일치로 후보 압축.
  - 멀티 아이템 주문은 V1 에서는 첫 번째 item 만 처리 (대부분의 케이스 커버).
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import datetime, timezone
from typing import Optional

from app.core.supabase import get_supabase_client
from app.core.llm import get_openai_client, DEFAULT_MODEL


logger = logging.getLogger(__name__)


# 한 cancelled_order 당 최대 추천 수
MAX_RECOMMENDATIONS = 3
# 카테고리 안에서 LLM 에 전달할 후보 풀 상한 (토큰/지연 보호)
CANDIDATE_POOL_LIMIT = 20


class AlternativePartnerService:
    def __init__(self):
        self._client = None

    @property
    def client(self):
        if self._client is None:
            self._client = get_supabase_client()
        return self._client

    @property
    def recs_table(self):
        return self.client.table("alternative_partner_recommendations")

    # ===========================================
    # public — 진입점
    # ===========================================
    async def find_and_notify(self, cancelled_order: dict) -> Optional[dict]:
        """판매자 취소 → 자동 대체 거래처 탐색 + 자동 견적 생성 + 알림.

        cancelled_order 는 order_service.get_order() 가 반환하는 평탄 dict
        (items/buyer_id/seller_id/order_number/delivery_date 등 포함).

        반환: 저장된 recommendation row dict (실패해도 None 반환, 예외 던지지 않음).
        """
        try:
            return await self._run(cancelled_order)
        except Exception as e:
            logger.error(
                "[alternative_partner_service.find_and_notify] 전체 흐름 실패 (무시): "
                "order_id=%s error=%s: %s",
                cancelled_order.get("id"),
                type(e).__name__,
                e,
            )
            return None

    # ===========================================
    # internal — 메인 흐름
    # ===========================================
    async def _run(self, cancelled_order: dict) -> Optional[dict]:
        order_id = cancelled_order.get("id")
        buyer_id = cancelled_order.get("buyer_id")
        original_seller_id = cancelled_order.get("seller_id")
        order_number = cancelled_order.get("order_number") or ""
        items = cancelled_order.get("items") or []

        if not (order_id and buyer_id and items):
            logger.warning(
                "[alternative_partner_service] 필수 필드 누락 — order_id=%s buyer_id=%s items=%s",
                order_id, buyer_id, len(items),
            )
            return None

        # 첫 번째 item 만 처리 (V1 정책)
        first_item = items[0]
        original_product_name = first_item.get("product_name")
        original_category = first_item.get("product_category")
        quantity = first_item.get("quantity")
        unit_price = first_item.get("unit_price")
        unit = first_item.get("product_unit") or ""

        if not (original_product_name and original_category and quantity and unit_price):
            logger.warning(
                "[alternative_partner_service] item 정보 부족 — product=%s cat=%s qty=%s price=%s",
                original_product_name, original_category, quantity, unit_price,
            )
            # 알림은 보내되 후보 0개로
            await self._upsert_recommendation(order_id, buyer_id, [], "SELLER_CANCELLED")
            await self._emit_notification(
                buyer_id=buyer_id,
                cancelled_order_id=order_id,
                cancelled_order_number=order_number,
                product_name=original_product_name or "상품",
                found_count=0,
            )
            return None

        # 1) 후보 상품 조회 (같은 카테고리 OR 같은 상품명, 다른 판매자, 재고 quantity 이상)
        raw_candidates = await self._fetch_candidate_products(
            category=original_category,
            product_name=original_product_name,
            exclude_seller_id=str(original_seller_id) if original_seller_id else None,
            min_stock=quantity,
        )
        logger.info(
            "[alternative_partner_service] order=%s 카테고리=%s 1차 후보=%d",
            order_id, original_category, len(raw_candidates),
        )

        # 2) LLM 으로 본질 상품 동일성 판별
        same_product_candidates = await self._filter_same_product_with_llm(
            original_name=original_product_name,
            candidates=raw_candidates,
        )
        logger.info(
            "[alternative_partner_service] order=%s LLM 통과 후보=%d",
            order_id, len(same_product_candidates),
        )

        # 3) 상위 3건 — 재고 DESC, 가격 ASC
        top3 = sorted(
            same_product_candidates,
            key=lambda p: (-int(p.get("stock_quantity") or 0), int(p.get("price_per_unit") or 0)),
        )[:MAX_RECOMMENDATIONS]

        # 4) 각 후보에 자동 견적 주문 생성 (실패해도 다른 후보는 진행)
        for candidate in top3:
            try:
                auto_order = await self._create_auto_quote(
                    buyer_id=buyer_id,
                    cancelled_order=cancelled_order,
                    candidate=candidate,
                    quantity=quantity,
                    unit_price=unit_price,
                )
                candidate["auto_order_id"] = auto_order["id"]
                candidate["auto_order_number"] = auto_order["order_number"]
                candidate["auto_order_error"] = None
                # 가격 결정 메타 (effective_unit_price/price_strategy/...)
                meta = auto_order.get("_meta") or {}
                candidate["original_unit_price"] = meta.get("original_unit_price")
                candidate["effective_unit_price"] = meta.get("effective_unit_price")
                candidate["price_strategy"] = meta.get("price_strategy")
            except Exception as e:
                candidate["auto_order_id"] = None
                candidate["auto_order_number"] = None
                candidate["auto_order_error"] = f"{type(e).__name__}: {e}"
                # 실패 케이스에도 정책 의도가 보이도록 기록 (가능한 만큼)
                try:
                    eff, strat = self._decide_effective_price(
                        original_price=unit_price,
                        candidate_listed_price=candidate.get("price_per_unit"),
                    )
                    candidate["original_unit_price"] = int(unit_price) if unit_price else None
                    candidate["effective_unit_price"] = int(eff)
                    candidate["price_strategy"] = strat
                except Exception:
                    candidate["original_unit_price"] = int(unit_price) if unit_price else None
                    candidate["effective_unit_price"] = None
                    candidate["price_strategy"] = None
                logger.error(
                    "[alternative_partner_service] 자동 견적 실패 — seller=%s err=%s",
                    candidate.get("seller_id"), candidate["auto_order_error"],
                )

        # 5) 거래 이력 enrich (trade_count, last_trade_date)
        await self._enrich_trade_history(top3, buyer_id)

        # 6) DB 저장 (UPSERT on cancelled_order_id)
        saved = await self._upsert_recommendation(order_id, buyer_id, top3, "SELLER_CANCELLED")

        # 7) 알림
        await self._emit_notification(
            buyer_id=buyer_id,
            cancelled_order_id=order_id,
            cancelled_order_number=order_number,
            product_name=original_product_name,
            found_count=len(top3),
        )

        return saved

    # ===========================================
    # 1) 후보 상품 조회
    # ===========================================
    async def _fetch_candidate_products(
        self,
        *,
        category: str,
        product_name: str,
        exclude_seller_id: Optional[str],
        min_stock: int,
    ) -> list[dict]:
        """다른 판매자·재고 충분·삭제 안 됨·OUT_OF_STOCK 아닌 상품 후보 풀.

        1차 후보 수집 정책 (2026-05-06 수정):
          - q1 (category 매칭): 같은 카테고리의 상품 — 카테고리 분류가 일관된 셀러들 매칭
          - q2 (name 부분 일치): 카테고리 무관, 상품명 ILIKE %original% 매칭 — 같은 상품이
            다른 카테고리에 등록된 케이스(예: 같은 '감자' 가 한 곳은 GRAIN, 다른 곳은 VEGETABLE
            로 등록) 까지 후보 풀에 포함. 프런트엔드 카테고리 옵션이 4개로 좁아 셀러마다
            분류가 달라지는 경우가 흔하므로 카테고리 hard filter 만으로는 누락 위험.
          - 두 결과를 id 기준 dedupe 한 뒤 반환.

        본질 상품 동일성 판별은 호출처(_filter_same_product_with_llm)가 수행하므로
        여기서는 풀을 넓게 가져오는 게 안전 (LLM 이 가공품·다른 품목은 거른다).
        """
        def _query_by_category():
            q = (
                self.client.table("products")
                .select(
                    "id, seller_id, name, category, unit, price_per_unit, stock_quantity, status, "
                    "seller:users!seller_id(name, company_name, phone, email)"
                )
                .eq("category", category)
                .gte("stock_quantity", int(min_stock))
                .neq("status", "OUT_OF_STOCK")
                .is_("deleted_at", None)
                .limit(CANDIDATE_POOL_LIMIT)
            )
            if exclude_seller_id:
                q = q.neq("seller_id", exclude_seller_id)
            return q.execute()

        def _query_by_name():
            # 카테고리 무관 — 같은 상품명이 다른 카테고리에 등록된 케이스 방어
            q = (
                self.client.table("products")
                .select(
                    "id, seller_id, name, category, unit, price_per_unit, stock_quantity, status, "
                    "seller:users!seller_id(name, company_name, phone, email)"
                )
                .ilike("name", f"%{product_name}%")
                .gte("stock_quantity", int(min_stock))
                .neq("status", "OUT_OF_STOCK")
                .is_("deleted_at", None)
                .limit(CANDIDATE_POOL_LIMIT)
            )
            if exclude_seller_id:
                q = q.neq("seller_id", exclude_seller_id)
            return q.execute()

        rows: list[dict] = []
        try:
            r1 = await asyncio.to_thread(_query_by_category)
            rows.extend(r1.data or [])
        except Exception as e:
            logger.error(
                "[alternative_partner_service] 후보 조회(category) 실패: %s: %s",
                type(e).__name__, e,
            )
        if product_name:
            try:
                r2 = await asyncio.to_thread(_query_by_name)
                rows.extend(r2.data or [])
            except Exception as e:
                logger.error(
                    "[alternative_partner_service] 후보 조회(name ilike) 실패: %s: %s",
                    type(e).__name__, e,
                )

        # id 기준 dedupe — 두 query 가 겹치는 row 정리
        unique_by_id: dict[str, dict] = {}
        for r in rows:
            rid = r.get("id")
            if rid and rid not in unique_by_id:
                unique_by_id[rid] = r
        rows = list(unique_by_id.values())

        # seller_id 별 1상품만 (재고 최대인 상품)
        best_per_seller: dict[str, dict] = {}
        for r in rows:
            sid = r.get("seller_id")
            if not sid:
                continue
            seller_info = r.pop("seller", None) or {}
            r["seller_name"] = seller_info.get("name") or ""
            r["seller_company"] = seller_info.get("company_name") or ""
            r["seller_phone"] = seller_info.get("phone") or ""
            r["seller_email"] = seller_info.get("email") or ""

            cur = best_per_seller.get(sid)
            if (cur is None) or (
                int(r.get("stock_quantity") or 0) > int(cur.get("stock_quantity") or 0)
            ):
                best_per_seller[sid] = r
        return list(best_per_seller.values())

    # ===========================================
    # 2) LLM 본질 상품 동일성 판별
    # ===========================================
    async def _filter_same_product_with_llm(
        self,
        *,
        original_name: str,
        candidates: list[dict],
    ) -> list[dict]:
        """LLM 에 후보 이름들을 보여주고 "본질적으로 같은 상품" 인 것만 골라낸다.

        실패 시 fallback: 정규화된 이름의 substring 일치로 압축.
        """
        if not candidates:
            return []

        # 정규화 fallback 미리 준비 (LLM 실패 / 응답 파싱 실패 시 사용)
        def _normalize(s: str) -> str:
            return re.sub(r"\s+", "", (s or "").lower())
        original_norm = _normalize(original_name)
        # original 이름의 핵심 단어 — '창원 감자' → '감자' 추출 시도
        # 단순 fallback 으로 마지막 토큰을 핵심 단어로 가정
        original_core = (original_name or "").split()[-1] if original_name else ""
        original_core_norm = _normalize(original_core)

        def _fallback() -> list[dict]:
            kept: list[dict] = []
            for c in candidates:
                cn = _normalize(c.get("name") or "")
                if not cn:
                    continue
                # 후보 이름이 원본 핵심 단어를 포함하거나, 원본이 후보를 포함하면 통과
                if original_core_norm and original_core_norm in cn:
                    kept.append(c)
                elif original_norm and (original_norm in cn or cn in original_norm):
                    kept.append(c)
            return kept

        try:
            client = get_openai_client()
            # 후보 인덱스 + 이름만 LLM 에 전달 (개인정보 노출 최소화)
            candidate_payload = [
                {"index": i, "name": c.get("name") or ""}
                for i, c in enumerate(candidates)
            ]
            system = (
                "당신은 농산물 B2B 플랫폼의 상품 매칭 판정자입니다. "
                "사용자가 원래 주문하려던 상품과, 후보 상품 목록을 비교해 "
                "'본질적으로 같은 상품' 인 후보의 index 리스트만 JSON 으로 반환하세요. "
                "예: '창원 감자' 와 '여주 감자' 는 둘 다 감자라 같은 상품. "
                "'사과' 와 '청사과' 는 둘 다 사과라 같은 상품. "
                "'고구마' 와 '감자' 는 다른 상품. "
                "'홍로 사과' 와 '사과 주스' 는 가공 여부가 달라 다른 상품. "
                "응답은 반드시 {\"matches\": [정수 index, ...]} 형식의 JSON 만 출력. "
                "다른 텍스트, 마크다운 금지."
            )
            user_content = json.dumps(
                {"original": original_name, "candidates": candidate_payload},
                ensure_ascii=False,
            )
            resp = await client.chat.completions.create(
                model=DEFAULT_MODEL,
                temperature=0,
                response_format={"type": "json_object"},
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_content},
                ],
            )
            text = (resp.choices[0].message.content or "").strip()
            parsed = json.loads(text)
            indices = parsed.get("matches") or []
            kept: list[dict] = []
            for i in indices:
                if isinstance(i, int) and 0 <= i < len(candidates):
                    kept.append(candidates[i])
            if not kept:
                # LLM 이 0개로 응답해도 fallback 으로 한번 더 검증
                logger.info(
                    "[alternative_partner_service] LLM 매칭 0건 → fallback 시도 (original=%s)",
                    original_name,
                )
                return _fallback()
            return kept
        except Exception as e:
            logger.error(
                "[alternative_partner_service] LLM 매칭 실패 → fallback: %s: %s",
                type(e).__name__, e,
            )
            return _fallback()

    # ===========================================
    # 3) 자동 견적 주문 생성
    # ===========================================
    @staticmethod
    def _decide_effective_price(
        original_price: Optional[int],
        candidate_listed_price: Optional[int],
    ) -> tuple[int, str]:
        """원래 주문가와 대체 셀러 표시가 중 구매자에게 더 유리한 단가를 결정한다.

        정책 (사용자 요구 2026-05-07):
          - 둘 다 양수: min(둘) 채택
            * original < candidate → "ORIGINAL_LOWER"  (기존 가격으로 협상가 제시)
            * original > candidate → "CANDIDATE_LOWER" (새 셀러가 더 저렴 → 그 단가 채택)
            * original == candidate → "EQUAL"
          - 한쪽만 양수: 그 값 채택 ("FALLBACK_ORIGINAL" / "FALLBACK_CANDIDATE")
          - 둘 다 None/0: ValueError — 호출처가 catch 해 auto_order_error 로 기록.

        반환: (effective_price, strategy_str)
        """
        op = int(original_price) if original_price else 0
        cp = int(candidate_listed_price) if candidate_listed_price else 0

        if op > 0 and cp > 0:
            if op < cp:
                return op, "ORIGINAL_LOWER"
            if op > cp:
                return cp, "CANDIDATE_LOWER"
            return op, "EQUAL"
        if op > 0:
            return op, "FALLBACK_ORIGINAL"
        if cp > 0:
            return cp, "FALLBACK_CANDIDATE"
        raise ValueError("가격 정보 부족 — original/candidate 모두 None/0")

    async def _create_auto_quote(
        self,
        *,
        buyer_id: str,
        cancelled_order: dict,
        candidate: dict,
        quantity: int,
        unit_price: int,
    ) -> dict:
        """후보 판매자에게 새 견적 주문 자동 생성.

        가격 결정 (2026-05-07 — 사용자 요구):
          - effective_unit_price = 구매자에게 더 유리한 단가 (원래가 vs 새 셀러 표시가 중 min)
          - auto_confirm=True 로 호출 — order_service.create_order 가 단가 비교 후 자동 분기:
              * effective < listed (= 원래가가 더 쌌고 그것을 채택한 경우):
                자동 카운터오퍼 카드 발사 → NEGOTIATING (사용자 요구 "기존 가격으로 협상가 제시")
              * effective == listed (= 새 셀러가 더 쌌고 그것을 채택한 경우 / 동일 케이스):
                QUOTE_REQUESTED 로 시작, 판매자 검토 대기 (사용자 요구 "그 단가로 주문")
          - 메타 정보(effective_unit_price, price_strategy) 는 반환 dict 의 _meta 키에 담아
            호출처가 candidates 응답에 합쳐 저장한다.

        지연 import (순환 참조 방지) — order_service 가 이 모듈을 사용하지는 않지만,
        cancel_order 흐름에서 alternative_partner_service 가 호출되므로 안전 차원에서
        함수 내 import.

        반환 형식:
          {**created_order_dict, "_meta": {
              "original_unit_price": int|None,
              "candidate_listed_price": int|None,
              "effective_unit_price": int,
              "price_strategy": str,
          }}
        실패 시 ValueError 또는 order_service 의 HTTPException 등 그대로 전파 (호출처 try/except 처리).
        """
        from app.services.order_service import order_service

        original_number = cancelled_order.get("order_number") or ""
        delivery_date = cancelled_order.get("delivery_date")
        delivery_address = cancelled_order.get("delivery_address")

        # delivery_date 는 OrderCreate 필수 — None 이면 오늘 날짜로 fallback
        if not delivery_date:
            delivery_date = datetime.now(timezone.utc).date().isoformat()

        # ── 가격 결정 ──
        candidate_listed = candidate.get("price_per_unit")
        effective_price, strategy = self._decide_effective_price(
            original_price=unit_price,
            candidate_listed_price=candidate_listed,
        )

        # 메모 — 가격 전략 인지 가능하도록 자연어 표기
        if strategy == "ORIGINAL_LOWER":
            price_note = (
                f"기존 주문 단가({int(unit_price):,}원) 가 새 셀러 표시가"
                f"({int(candidate_listed or 0):,}원) 보다 낮아 기존 단가로 협상가 제시."
            )
        elif strategy == "CANDIDATE_LOWER":
            price_note = (
                f"새 셀러 표시가({int(candidate_listed or 0):,}원) 가 기존 주문 단가"
                f"({int(unit_price):,}원) 보다 낮아 그 단가로 주문."
            )
        elif strategy == "EQUAL":
            price_note = f"기존/새 셀러 단가가 동일({effective_price:,}원)."
        else:
            price_note = f"가격 정책: {strategy} (effective={effective_price:,}원)."

        notes = (
            f"자동 견적 (취소된 주문 {original_number} 의 대체 판매자 추천). "
            f"수량 {int(quantity)} 그대로 / {price_note}"
        )

        payload = {
            "seller_id": str(candidate["seller_id"]),
            "delivery_date": str(delivery_date)[:10],
            "delivery_address": delivery_address,
            "notes": notes,
            "items": [
                {
                    "product_id": str(candidate["id"]),
                    "quantity": int(quantity),
                    "unit_price": int(effective_price),
                    "notes": None,
                }
            ],
        }
        # auto_confirm=True — order_service 의 자동 분기 활용:
        #   effective < listed → 자동 카운터오퍼 (NEGOTIATING)
        #   effective == listed → QUOTE_REQUESTED 정상 흐름
        order = await order_service.create_order(
            buyer_id=buyer_id,
            data=payload,
            auto_confirm=True,
        )
        # 메타 정보 첨부 (호출처가 candidates 응답에 흡수)
        if isinstance(order, dict):
            order = {**order, "_meta": {
                "original_unit_price": int(unit_price) if unit_price else None,
                "candidate_listed_price": int(candidate_listed) if candidate_listed else None,
                "effective_unit_price": int(effective_price),
                "price_strategy": strategy,
            }}
        return order

    # ===========================================
    # 4) 거래 이력 enrich
    # ===========================================
    async def _enrich_trade_history(self, candidates: list[dict], buyer_id: str) -> None:
        """각 candidate 에 (buyer ↔ seller) 의 trade_count / last_trade_date 채워 넣음.

        실패해도 0/None 으로 두고 진행.
        """
        if not candidates:
            return
        seller_ids = list({str(c["seller_id"]) for c in candidates if c.get("seller_id")})
        if not seller_ids:
            return

        def _query():
            return (
                self.client.table("orders")
                .select("seller_id, created_at, status")
                .eq("buyer_id", str(buyer_id))
                .in_("seller_id", seller_ids)
                .neq("status", "CANCELLED")
                .is_("deleted_at", None)
                .order("created_at", desc=True)
                .limit(200)
                .execute()
            )

        try:
            result = await asyncio.to_thread(_query)
        except Exception as e:
            logger.warning(
                "[alternative_partner_service] trade history 조회 실패 (무시): %s: %s",
                type(e).__name__, e,
            )
            for c in candidates:
                c["trade_count"] = 0
                c["last_trade_date"] = None
            return

        rows = result.data or []
        count_map: dict[str, int] = {}
        last_map: dict[str, str] = {}
        for r in rows:
            sid = r.get("seller_id")
            if not sid:
                continue
            count_map[sid] = count_map.get(sid, 0) + 1
            if sid not in last_map:
                last_map[sid] = r.get("created_at")

        for c in candidates:
            sid = str(c.get("seller_id") or "")
            c["trade_count"] = count_map.get(sid, 0)
            c["last_trade_date"] = last_map.get(sid)

    # ===========================================
    # 5) DB UPSERT
    # ===========================================
    async def _upsert_recommendation(
        self,
        cancelled_order_id: str,
        buyer_id: str,
        candidates: list[dict],
        reason: str,
    ) -> Optional[dict]:
        """alternative_partner_recommendations 에 UPSERT (cancelled_order_id UNIQUE).

        candidates 의 각 원소는 다음 키를 포함하도록 정규화:
          seller_id, seller_name, seller_company,
          product_id, product_name, stock_quantity, price_per_unit, unit,
          trade_count, last_trade_date,
          auto_order_id, auto_order_number, auto_order_error
        """
        normalized = [
            {
                "seller_id": str(c.get("seller_id") or ""),
                "seller_name": c.get("seller_name") or "",
                "seller_company": c.get("seller_company") or "",
                "product_id": str(c.get("id") or c.get("product_id") or ""),
                "product_name": c.get("name") or c.get("product_name") or "",
                "stock_quantity": int(c.get("stock_quantity") or 0),
                "price_per_unit": int(c.get("price_per_unit") or 0),
                "unit": c.get("unit") or "",
                "trade_count": int(c.get("trade_count") or 0),
                "last_trade_date": c.get("last_trade_date"),
                "auto_order_id": c.get("auto_order_id"),
                "auto_order_number": c.get("auto_order_number"),
                "auto_order_error": c.get("auto_order_error"),
                # 가격 결정 메타 (2026-05-07)
                "original_unit_price": c.get("original_unit_price"),
                "effective_unit_price": c.get("effective_unit_price"),
                "price_strategy": c.get("price_strategy"),
            }
            for c in candidates
        ]
        payload = {
            "cancelled_order_id": str(cancelled_order_id),
            "buyer_id": str(buyer_id),
            "candidates": normalized,
            "reason": reason,
            "found_count": len(normalized),
        }

        # cancelled_order_id 가 UNIQUE 라 같은 키로 두 번 들어오면 23505 → DELETE 후 INSERT 로 대응.
        try:
            result = await asyncio.to_thread(
                lambda: self.recs_table.insert(payload).execute()
            )
            row = (result.data or [{}])[0] if result.data else None
            return row
        except Exception as e:
            err_str = f"{type(e).__name__}: {e}"
            if "23505" in err_str or "duplicate" in err_str.lower():
                # 기존 row 삭제 후 재시도
                try:
                    await asyncio.to_thread(
                        lambda: self.recs_table.delete()
                        .eq("cancelled_order_id", str(cancelled_order_id))
                        .execute()
                    )
                    result = await asyncio.to_thread(
                        lambda: self.recs_table.insert(payload).execute()
                    )
                    return (result.data or [{}])[0] if result.data else None
                except Exception as e2:
                    logger.error(
                        "[alternative_partner_service] recommendations UPSERT 재시도 실패: %s: %s",
                        type(e2).__name__, e2,
                    )
                    return None
            logger.error(
                "[alternative_partner_service] recommendations INSERT 실패: %s",
                err_str,
            )
            return None

    # ===========================================
    # 6) 알림
    # ===========================================
    async def _emit_notification(
        self,
        *,
        buyer_id: str,
        cancelled_order_id: str,
        cancelled_order_number: str,
        product_name: str,
        found_count: int,
    ) -> None:
        # 지연 import — notification_service 가 이 모듈을 사용하지 않으므로 순환 위험은 없지만,
        # 통일성 차원에서 함수 내 import.
        from app.services.notification_service import notification_service

        if found_count > 0:
            title = "대체 판매자 자동 견적이 생성됐습니다"
            body = (
                f"판매자가 주문 {cancelled_order_number} ({product_name}) 을(를) 취소했습니다. "
                f"같은 상품을 파는 판매자 {found_count}곳에 자동으로 견적을 요청했습니다."
            )
        else:
            title = "대체 판매자를 찾지 못했습니다"
            body = (
                f"판매자가 주문 {cancelled_order_number} ({product_name}) 을(를) 취소했습니다. "
                f"현재는 같은 상품을 판매하는 다른 판매자가 없어 자동 견적을 만들지 못했습니다."
            )

        await notification_service.emit(
            user_id=buyer_id,
            notification_type="ALTERNATIVE_PARTNERS",
            title=title,
            body=body,
            link_url=f"/buyer/orders?id={cancelled_order_id}",
            order_id=cancelled_order_id,
        )


# 모듈 레벨 싱글톤
alternative_partner_service = AlternativePartnerService()
