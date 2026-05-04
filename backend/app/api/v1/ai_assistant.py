import json

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
    # tool_context 가 있으면 UUID 정보를 assistant 메시지에 첨부해
    # 다음 턴 LLM이 직전 조회 UUID를 재활용할 수 있게 한다.
    #
    # [history 오염 방지]
    # 현재 요청과 동일한 user 메시지를 가진 이력 쌍은 제외한다.
    # LLM(temperature=0)이 이전 잘못된 응답을 그대로 복사하는 "history echo" 버그 방지.
    current_prompt_normalized = request.prompt.strip()

    history = []
    for row in reversed(history_result.data or []):
        if row["prompt"].strip() == current_prompt_normalized:
            continue  # 동일 요청의 이전 응답(오답 포함)을 history에서 제거

        history.append({"role": "user", "content": row["prompt"]})

        assistant_content = row["response"]
        tool_ctx = row.get("tool_context")
        if tool_ctx:
            # Supabase는 JSONB를 자동으로 dict/list로 파싱해서 반환한다
            if isinstance(tool_ctx, str):
                try:
                    tool_ctx = json.loads(tool_ctx)
                except Exception:
                    tool_ctx = None
            if tool_ctx:
                uuid_hint = _extract_uuid_context(tool_ctx)
                if uuid_hint:
                    assistant_content += uuid_hint

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
