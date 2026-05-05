"""도메인별 도구 모듈을 모두 import 하여 ToolRegistry 등록을 트리거.

각 모듈의 top-level 에서 @tool 데코레이터가 실행되며 registry 에 등록된다.
새 도메인 모듈 추가 시 이 파일에 import 한 줄만 추가하면 자동 노출됨.

8 개 도메인 모듈 (총 41 개 도구):
- product       (6): get_products, check_stock, update_stock, create_product, delete_product, update_product
- order         (6): get_orders, get_order_detail, update_order_status, update_order, create_order, delete_order
- partner       (7): find_alternative_partners, request_partner_registration,
                     request_partner_registration_by_name, get_partners,
                     get_incoming_partner_requests, accept_partner_request, reject_partner_request
- subscription  (5): create_subscription_request, accept_subscription_request,
                     reject_subscription_request, create_subscription_from_order,
                     get_incoming_subscription_requests
- negotiation   (6): submit/accept/reject_counter_offer, submit/accept/reject_delivery_date_change
- user          (4): get_user_profile, find_sellers_by_product, find_buyers_by_product, open_chat_room
- calendar      (4): get_calendar_events, create_calendar_event, update_calendar_event, delete_calendar_event
- chat          (3): get_chat_rooms, get_chat_messages, send_chat_message
- chat (외부)    (1): analyze_chat_consensus — chat_ws.py 직접 호출, ToolRegistry 미등록

그룹 분류:
- "inventory_order" : product 6 + order 6 + partner 7 + subscription 5 + negotiation 6 + user 4 = 34
- "calendar"        : 4
- "chat"            : 3
"""
from . import product       # noqa: F401
from . import order         # noqa: F401
from . import partner       # noqa: F401
from . import subscription  # noqa: F401
from . import negotiation   # noqa: F401
from . import user          # noqa: F401
from . import calendar      # noqa: F401
from . import chat          # noqa: F401
