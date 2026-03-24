export interface QuickPrompt {
  label: string;
  prompt: string;
  type: string;
}

export const sellerQuickPrompts: QuickPrompt[] = [
  {
    label: '오늘 출하 일정 요약',
    prompt: '오늘 출하 예정인 일정을 모두 요약해줘. 품목, 수량, 거래처를 포함해서 알려줘.',
    type: 'SHIPMENT_SUMMARY',
  },
  {
    label: '미응답 견적 정리',
    prompt: '현재 미응답 상태인 견적 요청을 정리해줘. 우선순위와 함께 알려줘.',
    type: 'PENDING_QUOTES',
  },
  {
    label: '재고 부족 품목 확인',
    prompt: '재고가 부족하거나 소진된 품목을 알려주고, 보충이 필요한 수량을 추천해줘.',
    type: 'INVENTORY_ALERT',
  },
  {
    label: '구매자 답장 초안 작성',
    prompt: '가장 최근 견적 요청에 대한 정중하고 전문적인 답변 초안을 작성해줘.',
    type: 'DRAFT_REPLY',
  },
];

export const buyerQuickPrompts: QuickPrompt[] = [
  {
    label: '이번 주 납품 일정 정리',
    prompt: '이번 주 납품 예정인 일정을 모두 정리해줘. 공급처와 품목을 포함해서 알려줘.',
    type: 'DELIVERY_SUMMARY',
  },
  {
    label: '단가 비교 요약',
    prompt: '현재 거래 중인 품목들의 단가를 공급처별로 비교 요약해줘.',
    type: 'PRICE_COMPARISON',
  },
  {
    label: '판매자 문의 메시지 초안',
    prompt: '신규 품목 견적을 요청하는 정중한 문의 메시지 초안을 작성해줘.',
    type: 'DRAFT_INQUIRY',
  },
  {
    label: '지연 가능 주문 확인',
    prompt: '납품 지연 가능성이 있는 주문을 알려주고, 대응 방법을 추천해줘.',
    type: 'DELAY_RISK',
  },
];
