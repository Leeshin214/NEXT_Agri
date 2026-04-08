from fastapi import APIRouter, Depends
from fastapi.responses import StreamingResponse

from app.core.config import settings
from app.core.supabase import get_supabase_client
from app.dependencies import get_current_user
from app.schemas.ai import (
    AIChatRequest,
    AISummarizeChatRequest,
    AISummarizeResponse,
    AIConversationResponse,
)
from app.schemas.common import SuccessResponse
from app.services.ai_context import ai_context_builder
from app.services.orchestrator import agent_orchestrator

router = APIRouter(prefix="/ai", tags=["ai"])

SELLER_SYSTEM_PROMPT = """당신은 AgriFlow 농산물 유통 플랫폼의 AI 업무 도우미입니다.

[사용자 정보]
- 역할: 판매자 (농가/도매상/유통업체)
- 회사명: {company_name}
- 담당자: {user_name}

[현재 업무 현황]
{context}

[응답 원칙]
1. 반드시 한국어로 답변
2. 농산물 유통업 실무 용어 사용 (출하, 납품, 단가, 도매가, 박스 등)
3. 간결하고 실용적인 정보 제공
4. 수치가 있으면 구체적으로 언급
5. 긴 답변은 항목으로 구분하여 읽기 쉽게 작성
6. 불확실한 정보는 확인이 필요하다고 명시"""

BUYER_SYSTEM_PROMPT = """당신은 AgriFlow 농산물 유통 플랫폼의 AI 업무 도우미입니다.

[사용자 정보]
- 역할: 구매자 (마트/식자재업체/식당)
- 회사명: {company_name}
- 담당자: {user_name}

[현재 업무 현황]
{context}

[응답 원칙]
1. 반드시 한국어로 답변
2. 구매자 관점의 용어 사용 (발주, 납품, 단가 비교, 수급 등)
3. 비용 절감 및 효율적인 구매에 도움되는 정보 우선
4. 간결하고 실용적인 정보 제공
5. 납품 일정, 가격 변동에 민감하게 반응"""


@router.post("/chat")
async def ai_chat(
    request: AIChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """AI 채팅 (스트리밍 응답) - 역할별 컨텍스트 포함"""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    role = current_user.get("role", "BUYER")
    company = current_user.get("company_name", "미설정")
    name = current_user.get("name", "사용자")
    user_id = current_user["id"]

    # 역할별 컨텍스트 빌드
    if role == "SELLER":
        context = await ai_context_builder.build_seller_context(user_id)
        system_prompt = SELLER_SYSTEM_PROMPT.format(
            company_name=company, user_name=name, context=context
        )
    else:
        context = await ai_context_builder.build_buyer_context(user_id)
        system_prompt = BUYER_SYSTEM_PROMPT.format(
            company_name=company, user_name=name, context=context
        )

    collected_response = []

    async def generate():
        async with client.messages.stream(
            model="claude-3-5-sonnet-20241022",
            max_tokens=1024,
            system=system_prompt,
            messages=[{"role": "user", "content": request.prompt}],
        ) as stream:
            async for text in stream.text_stream:
                collected_response.append(text)
                yield f"data: {text}\n\n"
        yield "data: [DONE]\n\n"

        # 대화 히스토리 저장
        full_response = "".join(collected_response)
        supabase = get_supabase_client()
        supabase.table("ai_conversations").insert(
            {
                "user_id": user_id,
                "prompt": request.prompt,
                "response": full_response,
                "prompt_type": request.prompt_type,
            }
        ).execute()

    return StreamingResponse(
        generate(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


@router.post(
    "/summarize-chat",
    response_model=SuccessResponse[AISummarizeResponse],
)
async def summarize_chat(
    request: AISummarizeChatRequest,
    current_user: dict = Depends(get_current_user),
):
    """채팅 대화 AI 요약"""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    context_info = request.context or "농산물 유통 거래 채팅"

    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=512,
        system=(
            "당신은 농산물 유통업 B2B 플랫폼의 대화 요약 도우미입니다.\n"
            "아래 채팅 대화를 읽고 핵심 내용을 한국어로 간결하게 요약해주세요.\n"
            "주요 합의 사항, 가격, 수량, 납품일 등 중요한 정보를 빠짐없이 포함하세요."
        ),
        messages=[
            {
                "role": "user",
                "content": f"[{context_info}]\n\n{request.messages}\n\n위 대화를 요약해주세요.",
            }
        ],
    )

    summary_text = response.content[0].text
    return {"data": {"summary": summary_text}}


@router.post(
    "/daily-summary",
    response_model=SuccessResponse[dict],
)
async def daily_summary(
    current_user: dict = Depends(get_current_user),
):
    """오늘의 업무 자동 요약"""
    from anthropic import AsyncAnthropic

    client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

    role = current_user.get("role", "BUYER")
    user_id = current_user["id"]

    if role == "SELLER":
        context = await ai_context_builder.build_seller_context(user_id)
    else:
        context = await ai_context_builder.build_buyer_context(user_id)

    response = await client.messages.create(
        model="claude-3-5-sonnet-20241022",
        max_tokens=512,
        system="농산물 유통 플랫폼의 업무 요약 도우미입니다. 한국어로 간결하게 요약하세요.",
        messages=[
            {
                "role": "user",
                "content": (
                    f"다음 업무 현황을 바탕으로 오늘의 업무 요약과 우선순위를 알려주세요:\n\n{context}"
                ),
            }
        ],
    )

    return {"data": {"summary": response.content[0].text}}


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

    기존 /chat과 달리 Claude가 DB를 직접 조회/수정하는 tool을 선택해서
    실시간 데이터를 바탕으로 답변한다.

    응답에 response(최종 텍스트)와 tools_used(사용한 tool 목록)를 포함한다.
    """
    user_id = current_user["id"]
    role = current_user.get("role", "BUYER")

    # ---------------------------
    # DB 조회해서 LLM이 대화 이력 확인하도록 하는 부분 

    # DB에서 최근 대화 10개 조회 (최신순)
    supabase = get_supabase_client()
    history_result = (
        supabase.table("ai_conversations")
        .select("prompt, response")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(10)
        .execute()
    )

    # 최신순 → 오래된순으로 변환 후 user/assistant 쌍으로 변환
    history = []
    for row in reversed(history_result.data or []):
        history.append({"role": "user", "content": row["prompt"]})
        history.append({"role": "assistant", "content": row["response"]})

    # ---------------------------

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
    )

    # 대화 기록 저장
    supabase = get_supabase_client()
    supabase.table("ai_conversations").insert(
        {
            "user_id": user_id,
            "prompt": request.prompt,
            "response": result["response"],
            "prompt_type": (
                ",".join(result["tools_used"]) if result["tools_used"] else request.prompt_type
            ),
        }
    ).execute()

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
