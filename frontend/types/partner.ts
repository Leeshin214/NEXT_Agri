/**
 * V1.6 — 양방향 승인 모델.
 *
 * 백엔드 partners.status enum:
 *   - ACTIVE            : 양쪽 모두 수락된 활성 거래처
 *   - INACTIVE          : 거래 종료
 *   - PENDING_OUTGOING  : 본인이 보낸 요청 (수락 대기)
 *   - PENDING_INCOMING  : 받은 요청 (본인이 수락/거절)
 *   - PENDING           : (deprecated) V1.5 이전 데이터 호환을 위해 유지
 */
export type PartnerStatus =
  | 'ACTIVE'
  | 'INACTIVE'
  | 'PENDING'
  | 'PENDING_OUTGOING'
  | 'PENDING_INCOMING';

export interface Partner {
  id: string;
  user_id: string;
  partner_user_id: string;
  nickname: string | null;
  status: PartnerStatus;
  is_favorite: boolean;
  notes: string | null;
  created_at: string;
  updated_at: string;
  partner_name: string | null;
  partner_company: string | null;
  partner_role: string | null;
  partner_phone: string | null;
  // PM Report #8 작업 5 — 거래처 목록의 "최근 거래" 요약
  // 백엔드 GET /api/v1/partners 응답에 포함됨. 거래 없으면 null.
  last_trade_date?: string | null;   // ISO date 'YYYY-MM-DD'
  last_trade_amount?: number | null; // KRW 정수
}

export interface PartnerCreate {
  partner_user_id: string;
  nickname?: string;
  notes?: string;
}
