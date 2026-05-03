import type { ChatRoom } from '@/types';

/**
 * 채팅 리스트를 거래처(파트너)별로 묶기 위한 그룹.
 *
 * - 같은 (seller_id, buyer_id) 페어가 여러 주문(order_id) 으로 N개의 채팅방을 가질 수 있다.
 * - 본인이 SELLER 면 partner_user_id 는 buyer_id, BUYER 면 seller_id 가 된다.
 * - 그룹 내 메타값은 모두 그룹에 속한 ChatRoom 들에서 직접 계산하므로 별도 fetch 가 필요 없다.
 */
export interface ChatRoomGroup {
  /** 그룹 식별자 = 파트너 user_id */
  partnerUserId: string;
  /** 표시용 파트너 이름 (가장 최근 활동 방 기준) */
  partnerName: string | null;
  /** 표시용 파트너 회사 (가장 최근 활동 방 기준) */
  partnerCompany: string | null;
  /** 그룹 내 모든 방의 unread_count 합 */
  unreadTotal: number;
  /** 그룹 내 가장 최근 메시지 시각 (ISO string) — 정렬 키. null 이면 메시지 없음 */
  lastActivityAt: string | null;
  /** 진행 중인 주문방 개수 — order_id 가 NULL 이 아닌 방 개수 */
  activeOrderCount: number;
  /** 그룹에 속한 방 목록 — 최신 활동순 정렬 */
  rooms: ChatRoom[];
}

/**
 * 채팅방 배열을 거래처별로 묶는다.
 *
 * @param rooms 백엔드 GET /chat/rooms 응답의 ChatRoom[]
 * @param myRole 'SELLER' | 'BUYER' — partner_user_id 결정 기준
 *   - SELLER: partner = buyer_id
 *   - BUYER:  partner = seller_id
 *
 * @returns 그룹 배열 — 그룹 내 lastActivityAt DESC 정렬, 그룹 자체도 lastActivityAt DESC 정렬
 */
export function groupChatRoomsByPartner(
  rooms: ChatRoom[],
  myRole: 'SELLER' | 'BUYER'
): ChatRoomGroup[] {
  // partner_user_id 기준 Map 으로 묶음
  const groupMap = new Map<string, ChatRoom[]>();

  for (const room of rooms) {
    const partnerUserId = myRole === 'SELLER' ? room.buyer_id : room.seller_id;
    if (!partnerUserId) continue; // 비정상 데이터 방어
    const arr = groupMap.get(partnerUserId);
    if (arr) {
      arr.push(room);
    } else {
      groupMap.set(partnerUserId, [room]);
    }
  }

  const groups: ChatRoomGroup[] = [];

  groupMap.forEach((groupRooms, partnerUserId) => {
    // 그룹 내부: 활동 시각 DESC (없으면 created_at fallback)
    const sortedRooms = [...groupRooms].sort((a, b) => {
      const aTime = a.last_message_at ?? a.created_at;
      const bTime = b.last_message_at ?? b.created_at;
      return bTime.localeCompare(aTime);
    });

    // 메타 계산
    const unreadTotal = sortedRooms.reduce(
      (sum, r) => sum + (r.unread_count ?? 0),
      0
    );

    // last_activity_at = MAX(last_message_at), 없으면 null
    let lastActivityAt: string | null = null;
    for (const r of sortedRooms) {
      const t = r.last_message_at;
      if (!t) continue;
      if (!lastActivityAt || t.localeCompare(lastActivityAt) > 0) {
        lastActivityAt = t;
      }
    }

    const activeOrderCount = sortedRooms.filter((r) => !!r.order_id).length;

    // 표시용 파트너 정보 — 가장 최근 활동 방 (sortedRooms[0]) 의 값을 우선 사용,
    // 비어있으면 다른 방의 값으로 fallback
    let partnerName: string | null = null;
    let partnerCompany: string | null = null;
    for (const r of sortedRooms) {
      if (!partnerName && r.partner_name) partnerName = r.partner_name;
      if (!partnerCompany && r.partner_company) partnerCompany = r.partner_company;
      if (partnerName && partnerCompany) break;
    }

    groups.push({
      partnerUserId,
      partnerName,
      partnerCompany,
      unreadTotal,
      lastActivityAt,
      activeOrderCount,
      rooms: sortedRooms,
    });
  });

  // 그룹 자체 정렬: lastActivityAt DESC (null 은 가장 뒤)
  groups.sort((a, b) => {
    if (a.lastActivityAt && b.lastActivityAt) {
      return b.lastActivityAt.localeCompare(a.lastActivityAt);
    }
    if (a.lastActivityAt) return -1;
    if (b.lastActivityAt) return 1;
    return 0;
  });

  return groups;
}
