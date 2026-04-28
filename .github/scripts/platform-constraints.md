# AgriFlow 플랫폼 구현 조건 / 제약

> 이 파일은 PM 에이전트가 매 사이클마다 자동으로 참조합니다.
> 새 조건이 생길 때마다 아래에 추가하면 다음 사이클부터 PM이 반영합니다.
> **작성 형식**: 각 조건은 짧고 명확하게. PM이 작업 추천 시 위반하지 않을 정도로 구체적으로.

---

## 🤖 LLM / AI 아키텍처

### 1. 서브 LLM은 UI에 노출하지 않는다

- **메인 orchestrator LLM**은 사용자가 직접 대화하는 인터페이스(예: `/seller/ai-assistant`, `/buyer/ai-assistant`)에서 노출됨
- 그 외 페이지·기능에 들어있는 LLM 호출(예: 일정 추천 에이전트, 협상 분석, 카테고리 분류, 주문 의도 파악 등)은 **메인 orchestrator가 내부적으로 호출하는 서브 LLM**임
- 이 서브 LLM들은 **사용자 UI에 별도 패널/버튼/페이지로 노출하지 말 것**
- 메인 orchestrator가 사용자 의도를 파악하고 필요할 때 내부적으로 서브 LLM을 호출해 결과를 가공한 뒤 사용자에게 전달하는 구조

**예시 (서브 LLM이라 UI 노출 X)**:
- `backend/app/services/schedule_agent.py` — 일정 추천 서브 LLM. ScheduleAgentPanel 같은 UI 컴포넌트로 별도 노출 금지
- `backend/app/services/agent_tools.py` — orchestrator가 호출하는 도구 함수들
- 채팅 메시지 의도 분류, 협상 이력 요약 등 내부 추론 — 모두 백엔드 호출, UI 미노출

**예외 (UI 노출 OK)**:
- `/seller/ai-assistant`, `/buyer/ai-assistant` — 메인 orchestrator와 직접 대화하는 페이지

→ PM은 "X 페이지에 AI 분석 패널 추가" 같은 추천을 하지 말 것. 대신 메인 orchestrator가 사용자 발화에서 그 의도를 추론하고 서브 LLM을 호출하는 흐름을 강화하는 방향으로 추천.

---

## 📐 (추가 조건은 여기에 — 포맷 자유, 짧고 명확하게)

<!-- 새 조건 추가 시 위 형식 따라 ## 또는 ### 헤더 + 본문으로 작성 후 commit/push -->
<!-- 예시:
## 💳 결제·정산
### 2. 정산은 외부 PG 연동 V2 마일스톤
- V1 에서는 거래 합의·납품 기록까지만. 실 결제 흐름은 V2 에서 PortOne/토스페이먼츠 연동.
- PM 은 V1 사이클에서 "결제 화면 추가" 같은 추천 금지.
-->
