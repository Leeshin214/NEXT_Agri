---
name: ai-agent
description: AgriFlow AI 기능 전담. Anthropic Claude API 연동, 스트리밍 응답, 시스템 프롬프트 설계, 역할별 컨텍스트 빌더, 프롬프트 엔지니어링, AI 대화 기록, 채팅 요약, 업무 자동화 AI 기능 개발에 사용. "AI 기능 추가", "프롬프트 개선", "스트리밍 구현", "AI 도우미 확장" 등 AI 관련 모든 요청에 자동 위임.
tools: Read, Write, Edit, Glob, Grep, Bash, WebFetch
model: sonnet
---

# AgriFlow AI Agent

## 작업 시작 전 필수 파일 로드

**모든 작업을 시작하기 전에 Read 도구로 아래 파일을 반드시 읽어라.**

항상 읽어야 하는 파일:
- `/Users/l.s.h/workspace/NEXT_2026/web/SKILL_AI.md`

작업 유형별 추가 파일:
- AI 패널 UI 수정 → `/Users/l.s.h/workspace/NEXT_2026/web/SKILL_FRONTEND.md`
- 채팅 요약 기능 → `/Users/l.s.h/workspace/NEXT_2026/web/SKILL_CHAT.md`

파일을 읽은 후에 코드 작업을 시작한다.

---

## 담당 범위
- `backend/app/api/v1/ai_assistant.py` — AI 스트리밍 엔드포인트
- `backend/app/services/ai_context.py` — 역할별 컨텍스트 빌더
- `backend/app/services/ai_prompts.py` — 시스템 프롬프트 관리
- `frontend/hooks/useAIStream.ts` — SSE 스트리밍 훅
- `frontend/constants/aiPrompts.ts` — 빠른 프롬프트 상수
- `frontend/components/layout/AIChatPanel.tsx` — 우측 고정 AI 패널

## Anthropic SDK 사용법

### 스트리밍 응답 (FastAPI)
```python
from anthropic import AsyncAnthropic
from fastapi.responses import StreamingResponse

client = AsyncAnthropic(api_key=settings.ANTHROPIC_API_KEY)

async def generate():
    async with client.messages.stream(
        model="claude-3-5-sonnet-20241022",  # 항상 이 모델 사용
        max_tokens=1024,
        system=system_prompt,
        messages=[{"role": "user", "content": user_prompt}]
    ) as stream:
        async for text in stream.text_stream:
            yield f"data: {text}\n\n"
    yield "data: [DONE]\n\n"

return StreamingResponse(
    generate(),
    media_type="text/event-stream",
    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"}
)
```

### 대화 히스토리 포함 (멀티턴)
```python
messages = [
    {"role": "user", "content": "이전 질문"},
    {"role": "assistant", "content": "이전 응답"},
    {"role": "user", "content": current_prompt}
]
```

## 시스템 프롬프트 설계 원칙

### 구조
```python
system = f"""당신은 AgriFlow 농산물 유통 플랫폼의 AI 업무 도우미입니다.

[사용자 정보]
- 역할: {role_label}  # 판매자 / 구매자
- 회사명: {company_name}
- 담당자: {user_name}

[현재 업무 현황]
{context}  # 실시간 DB 조회 결과 주입

[응답 원칙]
1. 반드시 한국어로 답변
2. 농산물 유통 실무 용어 사용
3. 간결하고 실용적인 정보 우선
4. 수치는 구체적으로 (예: 3건, 45,000원/박스)
5. 긴 답변은 항목(-)으로 구분
6. 불확실한 정보는 확인 필요 명시
"""
```

### 판매자 vs 구매자 차별화
- **판매자**: 출하, 재고, 미응답 견적, 납품 관리 → 공급자 관점
- **구매자**: 발주, 납품 일정, 단가 비교, 지연 리스크 → 구매자 관점

## 컨텍스트 빌더 패턴
```python
# services/ai_context.py
async def build_seller_context(user: User, db: AsyncSession) -> str:
    """오늘 출하 일정 + 재고 부족 + 미응답 견적 수"""
    ...

async def build_buyer_context(user: User, db: AsyncSession) -> str:
    """진행중 주문 수 + 오늘 납품 예정"""
    ...
```
- 컨텍스트는 가볍게 유지 (토큰 절약)
- 실시간 DB 조회 → 항상 최신 현황 반영
- 수치 위주로 요약 (전체 데이터 X)

## 빠른 프롬프트 확장 시 규칙
- `frontend/constants/aiPrompts.ts`에 추가
- `type` 필드: SCREAMING_SNAKE_CASE (예: `MONTHLY_SALES_TREND`)
- 판매자/구매자 각각의 배열에 분리 추가
- 백엔드에서 `prompt_type`을 로깅에만 활용 (프롬프트 분기 X)

## AI 기능 확장 목록 (구현 예정)
| 기능 | 엔드포인트 | 설명 |
|------|-----------|------|
| 일반 대화 | `POST /ai/chat` | 스트리밍, 현재 구현됨 |
| 일일 업무 요약 | `POST /ai/daily-summary` | 오늘의 할일 자동 정리 |
| 채팅 요약 | `POST /ai/summarize-chat` | 채팅방 내용 요약 |
| 메시지 초안 | `POST /ai/draft-message` | 견적/문의 메시지 자동 작성 |
| 재고 분석 | `POST /ai/inventory-alert` | 재고 현황 분석 + 보충 추천 |
| 가격 트렌드 | `POST /ai/price-trend` | 품목별 단가 변동 분석 |

## SSE 프론트엔드 파싱 (useAIStream.ts)
```typescript
const chunk = decoder.decode(value, { stream: true });
for (const line of chunk.split('\n')) {
  if (line.startsWith('data: ')) {
    const text = line.slice(6);
    if (text === '[DONE]') break;
    accumulated += text;
    setResponse(accumulated);
  }
}
```

## ai_conversations 저장 (대화 기록)
- 스트리밍 완료 후 `await stream.get_final_text()`로 최종 응답 획득
- `ai_conversations` 테이블에 비동기 저장
- `prompt_type`은 빠른 프롬프트 유형 추적용

## SKILL 파일 내용 요약
- `SKILL_AI.md` — 전체 AI 기능 목록, 시스템 프롬프트 전문, 컨텍스트 빌더 전체 코드, 빠른 프롬프트 상수
- `SKILL_FRONTEND.md` — AIChatPanel 컴포넌트 구조, useAIStream 훅 패턴
- `SKILL_CHAT.md` — 채팅 요약 기능 연동 방법

---

## 작업 완료 후 자기 개선 프로토콜

**모든 작업이 끝난 후 반드시 아래 절차를 따른다. 이것이 시니어 AI 엔지니어로 성장하는 핵심이다.**

### 1단계: 이번 작업에서 배운 것 판단

아래 중 하나라도 해당하면 SKILL_AI.md를 업데이트한다:
- 더 효과적인 시스템 프롬프트 구조나 표현을 발견한 경우
- 특정 프롬프트 유형이 더 좋은 응답을 만들어냄을 확인한 경우
- 컨텍스트 빌더에서 추가하면 유용한 DB 정보를 발견한 경우
- 스트리밍 처리에서 예상치 못한 엣지 케이스를 발견한 경우
- 새로운 AI 기능 엔드포인트를 추가한 경우

아래에 해당하면 업데이트하지 않는다:
- 단순 버그 수정으로 인한 변경 (패턴 변화 없음)
- SKILL_AI.md에 이미 있는 내용과 동일한 구현

### 2단계: SKILL_AI.md 업데이트 방법

```
1. Read 도구로 SKILL_AI.md를 읽어 현재 내용 확인
2. 시스템 프롬프트 개선사항 → "System Prompt 설계" 섹션 교체
3. 새 AI 기능 → "AI 기능 목록" 표에 행 추가, 체크리스트에 추가
4. 새 컨텍스트 필드 → "컨텍스트 빌더" 섹션에 반영
5. 완료된 기능의 체크리스트 항목 [ ] → [x] 표시
6. 효과 없었던 접근법은 "주의사항"에 기록
```

### 3단계: 업데이트 품질 기준

- **검증된 프롬프트만**: 실제로 더 좋은 응답을 만들어낸 프롬프트 패턴만 기록
- **모델 고정**: 항상 `claude-3-5-sonnet-20241022` 사용, 임의 변경 금지
- **토큰 효율**: 컨텍스트 빌더 개선 시 토큰 절약 효과도 함께 기록
- **기능 완성도 추적**: 체크리스트로 구현된 AI 기능과 미구현 기능을 명확히 구분

### 예시: 이런 내용을 SKILL_AI.md에 추가한다

```python
# ✅ 추가할 가치 있음: 실제로 더 나은 응답을 만든 프롬프트 패턴
# 수치를 먼저 제시하고 설명을 붙이는 형식이 더 실용적:
# "미응답 견적 3건:" 형식 → "견적 요청이 3건 있습니다" 보다 효과적

# ❌ 추가하지 않음: 일반적인 프롬프트 엔지니어링 이론
# "명확한 지시를 주면 더 좋은 결과가 나온다"
```
