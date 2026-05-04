'use client';

import { useMemo } from 'react';
import { useRouter } from 'next/navigation';
import { Package, MessageSquare, MessageCircle } from 'lucide-react';
import { useChatRooms } from '@/hooks/useChat';
import { useOrders } from '@/hooks/useOrders';
import { ORDER_STATUS_CONFIG } from '@/constants/status';
import type { ChatRoom, Order, OrderStatus } from '@/types';

interface PartnerChatRoomsProps {
  /** 거래처 user_id — Partner.partner_user_id 와 동일 */
  partnerUserId: string;
  /** 본인 역할 — partner_user_id 가 ChatRoom.seller_id / buyer_id 중 어느 쪽과 매칭될지 결정 */
  myRole: 'SELLER' | 'BUYER';
  /** 카드 클릭 시 부모 모달을 닫고 싶을 때 사용 (PartnerDetailModal 내부에서 사용) */
  onNavigate?: () => void;
}

/**
 * US-3 — 거래처 상세에서 보이는 "진행 중 채팅" 카드 리스트.
 *
 * 데이터 흐름 (옵션 A — 클라이언트 필터):
 * - useChatRooms() 로 전체 채팅방을 받아 partner_user_id 로 필터한다.
 * - 각 카드의 주문 요약(품목·수량·상태) 은 useOrders({ partner_user_id }) 로 같이 가져와
 *   room.order_id 와 매칭한다. 채팅방 N 이 커지기 전까진 충분히 가볍다.
 * - 카드 클릭 → /{role}/chat?room_id={id} 로 이동. onNavigate(부모 모달 닫기) 도 호출한다.
 *
 * 정렬 / 라벨:
 * - 진행 중인 주문 채팅을 위로, 일반 대화를 아래로 — 그 안에서 last_message_at DESC.
 * - 주문 상태가 COMPLETED/CANCELLED 인 방은 "진행 중" 정의에 부합하지 않으므로 노출하지 않는다
 *   (단, order_id 가 없는 일반 대화방은 항상 노출).
 */
export default function PartnerChatRooms({
  partnerUserId,
  myRole,
  onNavigate,
}: PartnerChatRoomsProps) {
  const router = useRouter();
  const chatRoomsQuery = useChatRooms();
  // 거래처 단위로 좁힌 주문 목록 (status 무관) — room.order_id 매칭 용도
  const ordersQuery = useOrders({ partner_user_id: partnerUserId, limit: 200 });

  const allRooms: ChatRoom[] = chatRoomsQuery.data?.data ?? [];
  const allOrders: Order[] = ordersQuery.data?.data ?? [];

  const orderById = useMemo(() => {
    const map = new Map<string, Order>();
    for (const o of allOrders) map.set(o.id, o);
    return map;
  }, [allOrders]);

  // 1) 본인 role 기반 partner 매칭. SELLER → buyer_id, BUYER → seller_id.
  // 2) order_id 가 있으면 주문 상태로 한 번 더 거르고(완료/취소 제외), 없으면 그대로 노출.
  // 3) last_message_at DESC, order 채팅 우선.
  const visibleRooms = useMemo(() => {
    const matched = allRooms.filter((r) => {
      const otherUserId = myRole === 'SELLER' ? r.buyer_id : r.seller_id;
      return otherUserId === partnerUserId;
    });

    const inProgress = matched.filter((r) => {
      if (!r.order_id) return true;
      const order = orderById.get(r.order_id);
      // 주문 정보를 못 찾으면(아직 로딩 중이거나 다른 거래처 row) 일단 노출 — 채팅방이 거래처 매칭된 시점에 이미 검증됨.
      if (!order) return true;
      return order.status !== 'COMPLETED' && order.status !== 'CANCELLED';
    });

    return inProgress.sort((a, b) => {
      // 주문 채팅 우선
      const aHasOrder = a.order_id ? 1 : 0;
      const bHasOrder = b.order_id ? 1 : 0;
      if (aHasOrder !== bHasOrder) return bHasOrder - aHasOrder;

      const aTime = a.last_message_at ?? a.created_at;
      const bTime = b.last_message_at ?? b.created_at;
      return bTime.localeCompare(aTime);
    });
  }, [allRooms, orderById, myRole, partnerUserId]);

  const handleSelect = (roomId: string) => {
    const path =
      myRole === 'SELLER'
        ? `/seller/chat?room_id=${roomId}`
        : `/buyer/chat?room_id=${roomId}`;
    router.push(path);
    onNavigate?.();
  };

  // 로딩 — 채팅방 또는 주문이 아직 로딩 중일 때
  if (chatRoomsQuery.isLoading) {
    return (
      <p className="rounded-lg border border-gray-200 p-4 text-center text-sm text-gray-400">
        로딩 중...
      </p>
    );
  }

  if (visibleRooms.length === 0) {
    return (
      <p className="rounded-lg border border-dashed border-gray-300 bg-gray-50 p-4 text-center text-sm text-gray-500">
        이 거래처와 진행 중인 채팅이 없어요.
        <br />
        <span className="text-xs text-gray-400">
          새 주문이 들어오면 자동으로 채팅방이 열려요.
        </span>
      </p>
    );
  }

  return (
    <ul className="space-y-2">
      {visibleRooms.map((room) => (
        <PartnerChatRoomCard
          key={room.id}
          room={room}
          order={room.order_id ? orderById.get(room.order_id) : undefined}
          onSelect={handleSelect}
        />
      ))}
    </ul>
  );
}

interface PartnerChatRoomCardProps {
  room: ChatRoom;
  order: Order | undefined;
  onSelect: (roomId: string) => void;
}

function PartnerChatRoomCard({ room, order, onSelect }: PartnerChatRoomCardProps) {
  const isOrderRoom = !!room.order_id;
  const Icon = isOrderRoom ? Package : MessageSquare;
  const lastActivityLabel = formatRelativeTime(
    room.last_message_at ?? room.created_at
  );

  // 주문 요약 — 품목/수량 (백엔드 product_summary 우선)
  const orderSummary = isOrderRoom ? buildOrderSummary(order) : '일반 대화';
  const orderStatusCfg =
    isOrderRoom && order ? ORDER_STATUS_CONFIG[order.status as OrderStatus] : null;

  return (
    <li>
      <button
        type="button"
        onClick={() => onSelect(room.id)}
        className="group flex w-full flex-col gap-2 rounded-lg border border-gray-200 bg-white p-3 text-left transition-colors hover:border-primary-300 hover:bg-primary-50/40 sm:flex-row sm:items-start sm:justify-between"
      >
        {/* 좌측 — 라벨 + 메시지 */}
        <div className="min-w-0 flex-1 space-y-1">
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={`inline-flex items-center gap-1 text-xs font-medium ${
                isOrderRoom ? 'text-primary-700' : 'text-gray-500'
              }`}
            >
              <Icon className="h-3.5 w-3.5" aria-hidden="true" />
              {isOrderRoom ? '주문 채팅' : '일반 대화'}
            </span>
            {orderStatusCfg && (
              <span
                className={`inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium ${orderStatusCfg.className}`}
              >
                {orderStatusCfg.label}
              </span>
            )}
            {room.unread_count > 0 && (
              <span className="inline-flex h-5 min-w-[20px] items-center justify-center rounded-full bg-primary-600 px-1.5 text-[10px] font-bold text-white">
                {room.unread_count}
              </span>
            )}
          </div>
          <p className="truncate text-sm font-medium text-gray-900">
            {orderSummary}
          </p>
          {room.last_message ? (
            <p className="truncate text-xs text-gray-500">{room.last_message}</p>
          ) : (
            <p className="truncate text-xs text-gray-400">아직 메시지가 없습니다.</p>
          )}
        </div>

        {/* 우측 — 메타 (시각 + CTA 아이콘) */}
        <div className="flex flex-shrink-0 items-center gap-2 text-xs text-gray-400 sm:flex-col sm:items-end sm:gap-1">
          {lastActivityLabel && <span>{lastActivityLabel}</span>}
          <span className="inline-flex items-center gap-1 text-[11px] text-gray-500 group-hover:text-primary-700">
            <MessageCircle className="h-3 w-3" aria-hidden="true" />
            바로가기
          </span>
        </div>
      </button>
    </li>
  );
}

/**
 * 주문 요약 라벨. 백엔드가 product_summary 를 채워주면 그대로 쓰고, 없으면 첫 항목 + "외 N건" 폴백.
 * 주문이 아직 로딩 중이라 undefined 면 "주문 정보 불러오는 중...".
 */
function buildOrderSummary(order: Order | undefined): string {
  if (!order) return '주문 정보 불러오는 중...';
  if (order.product_summary) return order.product_summary;
  const first = order.items?.[0];
  if (!first) return '상품 정보 없음';
  const name = first.product_name ?? '상품 정보 없음';
  const unit = first.product_unit ?? '';
  const qty = `${first.quantity}${unit}`;
  const extra = order.items.length > 1 ? ` 외 ${order.items.length - 1}건` : '';
  return `${name} ${qty}${extra}`;
}

/**
 * 채팅 그룹 헤더와 동일한 상대 시각 포맷 ("방금 전" / "N분 전" / "N시간 전" / "N일 전" / "M.D").
 * components/chat/ChatRoomGroup.tsx 와 키를 맞췄다.
 */
function formatRelativeTime(iso: string | null): string {
  if (!iso) return '';
  const t = new Date(iso).getTime();
  if (Number.isNaN(t)) return '';
  const diffSec = Math.floor((Date.now() - t) / 1000);
  if (diffSec < 60) return '방금 전';
  if (diffSec < 3600) return `${Math.floor(diffSec / 60)}분 전`;
  if (diffSec < 86400) return `${Math.floor(diffSec / 3600)}시간 전`;
  if (diffSec < 86400 * 7) return `${Math.floor(diffSec / 86400)}일 전`;
  const d = new Date(iso);
  return `${d.getMonth() + 1}.${d.getDate()}`;
}
