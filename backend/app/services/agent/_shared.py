"""cross-domain 공통 헬퍼.

여기에는 여러 도메인 도구가 공유하는 유틸 (UUID 검증, async runner,
공통 응답 빌더 등) 만 둔다. 도메인 특정 helper 는 해당 도메인 모듈
안에 둔다 (예: tools/product.py 내부에 _find_product_by_name).

PR 0 에서는 비어있고, 다음 PR 들에서 agent_tools.py 의 cross-domain
helper (`_run_async_in_thread` 등) 를 점진 이동한다.
"""
# 의도적으로 비워둠 — 다음 PR 에서 채울 예정
