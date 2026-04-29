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

    # Supabase 클라이언트는 한 번만 가져와 재사용 (이전: 두 번 호출했음)
    supabase = get_supabase_client()

    # DB에서 최근 대화 10개 조회 (최신순)
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

    # 대화 기록 저장 (위에서 만든 supabase 클라이언트 재사용)
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
