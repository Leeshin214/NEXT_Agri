"""도메인별 도구 모듈을 모두 import 하여 ToolRegistry 등록을 트리거.

각 모듈의 top-level 에서 @tool 데코레이터가 실행되며 registry 에 등록된다.
새 도메인 모듈 추가 시 이 파일에 import 한 줄만 추가하면 자동 노출됨.

PR 0 — 인프라만, 도메인 모듈 0 개. 다음 PR 들에서 추가 예정:
- product (6 개)
- order (6 개)
- chat (4 개)
- calendar (4 개)
- partner (7 개)
- subscription (4 개)
- negotiation (6 개)
- user (3 개)
"""
# 도메인 모듈 import — 다음 PR 에서 채움
# from . import product  # noqa: F401
# from . import order    # noqa: F401
# from . import chat     # noqa: F401
# ... 등
