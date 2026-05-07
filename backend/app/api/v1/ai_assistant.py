import json
import re

from fastapi import APIRouter, Depends

from app.core.llm import get_openai_client
from app.core.supabase import get_supabase_client
from app.dependencies import get_current_user
from app.schemas.ai import (
    AIChatRequest,
    AISummarizeChatRequest,
    AISummarizeResponse,
    AIConversationResponse,
)
from app.schemas.common import SuccessResponse
from app.services.orchestrator import agent_orchestrator

router = APIRouter(prefix="/ai", tags=["ai"])


# ───────────────────────────────────────────────
# 되묻기(follow-up question) 응답 판정 휴리스틱
#
# 의도: 도구 호출이 있던 응답이라도 "사용자에게 정보를 되묻는" 마지막 한 마디로 끝나는
#       응답은 history echo 의 위험이 거의 없고, 오히려 본문이 사라지면 다음 턴 router 가
#       follow-up 답변(예: "5월 22로 해줘")의 컨텍스트를 잃어 잘못된 부서로 라우팅된다.
#       이 경우 본문을 보존해 다음 턴이 같은 흐름(ORDER/CALENDAR 등)으로 이어지게 한다.
# ───────────────────────────────────────────────

# 응답 끝부분에서 흔히 나타나는 되묻기 패턴
_FOLLOWUP_TAIL_RE = re.compile(
    r"("
    r"\?\s*$"                                      # 물음표로 끝남
    r"|언제로\s*(?:할까요|드릴까요|하시겠어요|하시겠습니까)"
    r"|얼마(?:로|에|에요|예요|입니까|일까요)"
    r"|얼마로\s*(?:할까요|드릴까요)"
    r"|어떻게\s*할까요"
    r"|어느\s*것"
    r"|어떤\s*(?:상품|판매자|거래처|날짜|가격|수량|주기)"
    r"|어디로"
    r"|몇\s*(?:kg|박스|개|건|시|분|일|주|월)"
    r"|알려\s*(?:주세요|주시겠어요|주시면)"
    r"|말씀해\s*(?:주세요|주시겠어요|주시면)"
    r"|선택해\s*(?:주세요|주시겠어요)"
    r"|골라\s*(?:주세요|주시겠어요)"
    r"|확인\s*부탁\s*(?:드립니다|드려요|해\s*주세요)"
    r"|다시\s*(?:한\s*번\s*)?(?:말씀해|알려)"
    r")",
    flags=re.IGNORECASE,
)


def _is_followup_question(response_text: str, tool_results: list) -> bool:
    """assistant 응답이 사용자에게 정보를 되묻는 'follow-up question' 인지 판정.

    판정 기준 (둘 중 하나라도 매칭되면 True):
      1. 응답 본문 끝부분 ~120자에 의문/요청 표현이 있음 (_FOLLOWUP_TAIL_RE).
      2. tool_results 의 모든 호출이 success=False 로 끝남 — 도구가 모두 실패해 LLM 이
         사용자에게 다시 묻는 상태(예: hard guard 가 unit_price/delivery_date 거부 후
         LLM 이 사용자에게 되묻는 케이스). 이 경우 raw 데이터가 노출된 게 없으므로
         echo 위험 없음.
    """
    if not response_text:
        return False

    tail = response_text[-120:]
    if _FOLLOWUP_TAIL_RE.search(tail):
        return True

    if tool_results:
        all_failed = all(
            isinstance((c.get("result") or {}), dict)
            and (c.get("result") or {}).get("success") is False
            for c in tool_results
        )
        if all_failed:
            return True

    return False


def _extract_uuid_context(tool_results: list) -> str:
    """tool_results 에서 seller/product UUID 정보를 추출해 히스토리 주입용 문자열로 반환.

    LLM이 다음 턴에서 이전 조회의 UUID를 재사용할 수 있도록 assistant 메시지 끝에 첨부된다.
    UUID 데이터가 없으면 빈 문자열 반환.
    """
    lines: list[str] = []
    for tr in (tool_results or []):
        tool_name = tr.get("tool_name", "")
        result = tr.get("result") or {}

        if tool_name == "find_sellers_by_product":
            for s in (result.get("sellers") or []):
                sid = s.get("seller_id")
                name = s.get("seller_name") or s.get("seller_company") or ""
                company = s.get("seller_company") or ""
                if sid:
                    lines.append(
                        f"- 판매자 '{name}'(회사: {company}) → seller_id: {sid}"
                    )

        elif tool_name == "get_user_profile":
            user = result.get("user") or {}
            uid = user.get("id")
            name = user.get("name") or user.get("company_name") or ""
            if uid:
                lines.append(f"- 사용자 '{name}' → user_id: {uid}")

        elif tool_name in ("check_stock", "get_products"):
            for p in (result.get("products") or [result] if result.get("id") else []):
                pid = p.get("id") or p.get("product_id")
                pname = p.get("name") or ""
                if pid:
                    lines.append(f"- 상품 '{pname}' → product_id: {pid}")

    if not lines:
        return ""
    return "\n\n[직전 조회에서 확인된 UUID 참고]\n" + "\n".join(lines)


@router.post(
    "/summarize-chat",
    response_model=SuccessResponse[AISummarizeResponse],
)
async def summarize_chat(
    request: AISummarizeChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """채팅 대화 AI 요약"""
    client = get_openai_client()

    context_info = request.context or "농산물 유통 거래 채팅"

    response = await client.chat.completions.create(
        model="gpt-4o-mini",
        max_tokens=512,
        messages=[
            {
                "role": "system",
                "content": (
                    "당신은 농산물 유통업 B2B 플랫폼의 대화 요약 도우미입니다.\n"
                    "아래 채팅 대화를 읽고 핵심 내용을 한국어로 간결하게 요약해주세요.\n"
                    "주요 합의 사항, 가격, 수량, 납품일 등 중요한 정보를 빠짐없이 포함하세요."
                ),
            },
            {
                "role": "user",
                "content": f"[{context_info}]\n\n{request.messages}\n\n위 대화를 요약해주세요.",
            },
        ],
    )

    summary_text = response.choices[0].message.content or ""
    return {"data": {"summary": summary_text}}


@router.post(
    "/agent/chat",
    response_model=SuccessResponse[dict],
)
async def agent_chat(
    request: AIChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """
    tool_use 오케스트레이터 기반 AI 에이전트 채팅.

    기존 /chat과 달리 LLM 이 DB를 직접 조회/수정하는 tool 을 선택해서
    실시간 데이터를 바탕으로 답변한다.

    응답에 response(최종 텍스트)와 tools_used(사용한 tool 목록)를 포함한다.
    """
    user_id = current_user["id"]
    role = current_user.get("role", "BUYER")

    supabase = get_supabase_client()

    # DB에서 최근 대화 10개 조회 (최신순) — tool_context 포함
    history_result = (
        supabase.table("ai_conversations")
        .select("prompt, response, tool_context")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    # 최신순 → 오래된순으로 변환 후 user/assistant 쌍으로 변환
    #
    # [history echo 방지 정책 — 2026-05-06 강화]
    # LLM(temperature=0)이 직전 응답을 그대로 복제(echo)해 도구 재호출을 생략하는
    # 문제가 있었다 (예: "감자 찾아줘" 두 번 → 두 번째는 도구 안 부르고 옛 응답 복붙).
    # 사용자 정책: 같은/유사 프롬프트라도 항상 에이전트가 다시 도구를 호출해 fresh
    # 데이터를 가져와야 한다.
    #
    # 정책:
    #   1) 도구 호출이 있던(tool_context 가 있는) assistant 응답의 본문은 LLM 에 그대로
    #      넘기지 않는다. 본문은 "[직전 턴: 도구 X 호출됨. 데이터 캐시 사용 금지 —
    #      매 발화에서 새로 도구를 호출해 최신 상태를 받아라]" 같은 메타 마킹으로 교체.
    #   2) UUID hint(seller_id/product_id) 는 그대로 유지 — 직전 조회 식별자는
    #      재활용 가능해야 한다(예: "그 판매자한테 주문해줘"의 seller_id 매핑).
    #   3) 도구 호출이 없던 응답(GENERAL/인사 등)은 그대로 보존.
    #   4) 동일 prompt 가 history 에 있어도 마킹 정책으로 캐시가 차단되므로 굳이
    #      엔트리 자체를 제거할 필요 없음. 히스토리 길이 보존이 컨텍스트 안정성에 유리.
    history = []
    for row in reversed(history_result.data or []):
        history.append({"role": "user", "content": row["prompt"]})

        tool_ctx = row.get("tool_context")
        if tool_ctx:
            # Supabase는 JSONB를 자동으로 dict/list로 파싱해서 반환한다
            if isinstance(tool_ctx, str):
                try:
                    tool_ctx = json.loads(tool_ctx)
                except Exception:
                    tool_ctx = None

        if tool_ctx:
            # ── 되묻기(follow-up question) 응답이면 본문 보존 ──
            # 다음 턴 router 가 사용자의 짧은 답변(예: "5월 22로 해줘")을
            # 직전 흐름(ORDER 등) 으로 이어가기 위해 컨텍스트가 필요하다.
            # 이 경우 raw 데이터 노출이 거의 없거나(hard guard 차단 등) 사용자에게
            # 단순 질문으로 끝나므로 echo 위험이 낮다.
            if _is_followup_question(row.get("response") or "", tool_ctx):
                assistant_content = row["response"]
            else:
                tool_names = sorted({
                    c.get("tool_name") for c in tool_ctx if c.get("tool_name")
                })
                uuid_hint = _extract_uuid_context(tool_ctx)
                assistant_content = (
                    "[이전 턴 메타: "
                    + (f"도구 {', '.join(tool_names)} 호출됨. " if tool_names else "")
                    + "구체적 데이터(가격/재고/목록/잔여 수량 등)는 매 발화마다 도구로 "
                    + "새로 조회해야 한다. 이 메시지를 캐시 답변으로 재사용 금지.]"
                    + uuid_hint
                )
        else:
            # 도구 미사용 응답: 직전 짧은 답변/인사/되묻기 등은 컨텍스트 유지에 필요
            assistant_content = row["response"]

        history.append({"role": "assistant", "content": assistant_content})

    # 오케스트레이터 실행 — tool 루프 포함, 최종 응답 반환
    result = await agent_orchestrator.run(
        user_message=request.prompt,
        user_id=user_id,
        role=role,
        user_info={
            "name": current_user.get("name", "사용자"),
            "company_name": current_user.get("company_name", "미설정"),
        },
        history=history,
        order_id=request.order_id,
        room_id=request.room_id,
    )

    # 대화 기록 저장 (tool_context 포함)
    tool_results = result.get("tool_results") or []
    insert_payload: dict = {
        "user_id": user_id,
        "prompt": request.prompt,
        "response": result["response"],
        "prompt_type": (
            ",".join(result["tools_used"]) if result["tools_used"] else request.prompt_type
        ),
    }
    if tool_results:
        insert_payload["tool_context"] = json.dumps(tool_results, ensure_ascii=False)

    supabase.table("ai_conversations").insert(insert_payload).execute()

    return {"data": result}


@router.get(
    "/history",
    response_model=SuccessResponse[list[AIConversationResponse]],
)
async def list_ai_history(
    limit: int = 20,
    current_user: dict = Depends(get_current_user),
):
    """AI 대화 히스토리 조회"""
    supabase = get_supabase_client()
    result = (
        supabase.table("ai_conversations")
        .select("*")
        .eq("user_id", current_user["id"])
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    return {"data": result.data}
