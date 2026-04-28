'use client';

/**
 * 대시보드 상단 "오늘 할 일" 요약 위젯.
 *
 * 판매자/구매자 공통으로 다음 3개 카운트를 카드 형태로 노출하고,
 * 각 카드 클릭 시 해당 목록 페이지로 라우팅한다.
 *
 *  - 판매자: "오늘 출하 예정 N건"  | "응답 대기 견적 N건" | "미확인 메시지 N건"
 *  - 구매자: "오늘 도착 예정 N건"  | "응답 대기 견적 N건" | "미확인 메시지 N건"
 *
 * 데이터 소스:
 *  - useOrders({ status_in, limit }): 백엔드에서 다중 상태 필터 → delivery_date 가
 *    "오늘(KST)" 인 것만 클라이언트에서 카운트
 *  - useChatRooms(): 모든 채팅방의 unread_count 합산
 *
 * 새 백엔드 API 추가 없이 기존 hook 만 재사용한다 (PM 사이클 추천 작업 4 제약).
 */

import { useRouter } from 'next/navigation';
import {
  Truck,
  PackageCheck,
  FileText,
  MessageCircle,
  CheckCircle2,
  type LucideIcon,
} from 'lucide-react';
import { useOrders } from '@/hooks/useOrders';
import { useChatRooms } from '@/hooks/useChat';
import type { ChatRoom, Order, OrderStatus } from '@/types';
import { cn } from '@/lib/utils';

interface TodayTasksWidgetProps {
  role: 'seller' | 'buyer';
}

/**
 * KST(UTC+9) 기준 오늘 날짜를 'YYYY-MM-DD' 문자열로 반환.
 *
 * Order.delivery_date 는 백엔드에서 문자열(YYYY-MM-DD)로 내려주므로 문자열 비교가
 * 가장 안전하다. new Date().toISOString() 은 UTC 기준이라 한국 새벽시간대에 하루
 * 어긋날 수 있어 toLocaleDateString 의 'sv-SE' 로케일(YYYY-MM-DD 포맷)을 사용한다.
 */
function getTodayKstString(): string {
  return new Date().toLocaleDateString('sv-SE', { timeZone: 'Asia/Seoul' });
}

// 판매자/구매자 별로 "오늘 출하/도착 예정" 으로 잡을 주문 상태 집합.
// AC 요구사항:
//  - 판매자: 출하 예정 → SHIPPING (이미 출하했지만 도착 전) + PREPARING/CONFIRMED 도
//    delivery_date 가 오늘이면 출하해야 하므로 포함
//  - 구매자: 도착 예정 → CONFIRMED / PREPARING / SHIPPING 중 delivery_date 오늘
const SHIPMENT_STATUSES_SELLER: OrderStatus[] = [
  'CONFIRMED',
  'PREPARING',
  'SHIPPING',
];
const SHIPMENT_STATUSES_BUYER: OrderStatus[] = [
  'CONFIRMED',
  'PREPARING',
  'SHIPPING',
];

// "응답 대기 견적" 상태:
//  - 판매자: QUOTE_REQUESTED — 구매자가 보낸 신규 견적 (판매자가 응답해야 함)
//  - 구매자: NEGOTIATING     — 판매자가 역제안한 협상 (구매자가 수락/거절해야 함)
const PENDING_QUOTE_STATUSES_SELLER: OrderStatus[] = ['QUOTE_REQUESTED'];
const PENDING_QUOTE_STATUSES_BUYER: OrderStatus[] = ['NEGOTIATING'];

interface TaskItem {
  key: string;
  label: string;
  count: number;
  icon: LucideIcon;
  iconColor: string;
  onClick: () => void;
}

export default function TodayTasksWidget({ role }: TodayTasksWidgetProps) {
  const router = useRouter();
  const today = getTodayKstString();

  const shipmentStatuses =
    role === 'seller' ? SHIPMENT_STATUSES_SELLER : SHIPMENT_STATUSES_BUYER;
  const quoteStatuses =
    role === 'seller'
      ? PENDING_QUOTE_STATUSES_SELLER
      : PENDING_QUOTE_STATUSES_BUYER;

  // 출하/도착 예정 — status_in + delivery_date 오늘 필터 (백엔드 status_in 미지원 시
  // useOrders 가 알아서 query string repeat 으로 직렬화)
  const shipmentsQuery = useOrders({
    status_in: shipmentStatuses,
    limit: 200,
  });

  // 응답 대기 견적
  const quotesQuery = useOrders({
    status_in: quoteStatuses,
    limit: 200,
  });

  // 미확인 메시지 — 채팅방 unread_count 합산
  const roomsQuery = useChatRooms();

  const isLoading =
    shipmentsQuery.isLoading || quotesQuery.isLoading || roomsQuery.isLoading;

  const shipments: Order[] = shipmentsQuery.data?.data ?? [];
  const quotes: Order[] = quotesQuery.data?.data ?? [];
  const rooms: ChatRoom[] = roomsQuery.data?.data ?? [];

  const todayShipmentCount = shipments.filter(
    (o) => o.delivery_date === today
  ).length;
  const pendingQuoteCount = quotes.length;
  const unreadCount = rooms.reduce((sum, r) => sum + (r.unread_count ?? 0), 0);

  const ordersHref = role === 'seller' ? '/seller/orders' : '/buyer/orders';
  const chatHref = role === 'seller' ? '/seller/chat' : '/buyer/chat';

  const tasks: TaskItem[] = [
    {
      key: 'shipment',
      label: role === 'seller' ? '오늘 출하 예정' : '오늘 도착 예정',
      count: todayShipmentCount,
      icon: role === 'seller' ? Truck : PackageCheck,
      iconColor: 'text-primary-600 bg-primary-100',
      onClick: () => router.push(ordersHref),
    },
    {
      key: 'quote',
      label: '응답 대기 견적',
      count: pendingQuoteCount,
      icon: FileText,
      iconColor: 'text-orange-600 bg-orange-100',
      onClick: () => router.push(ordersHref),
    },
    {
      key: 'unread',
      label: '미확인 메시지',
      count: unreadCount,
      icon: MessageCircle,
      iconColor: 'text-blue-600 bg-blue-100',
      onClick: () => router.push(chatHref),
    },
  ];

  const totalCount = todayShipmentCount + pendingQuoteCount + unreadCount;
  const isEmpty = !isLoading && totalCount === 0;

  return (
    <section className="mb-6 rounded-xl bg-white p-6 shadow-sm">
      <div className="mb-4 flex items-center justify-between">
        <div>
          <h2 className="text-lg font-semibold text-gray-900">오늘 할 일</h2>
          <p className="mt-0.5 text-xs text-gray-500">
            {role === 'seller'
              ? '오늘 처리해야 하는 주요 업무를 확인하세요'
              : '오늘 챙겨야 하는 주문과 메시지를 확인하세요'}
          </p>
        </div>
      </div>

      {isLoading ? (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {[0, 1, 2].map((i) => (
            <div
              key={i}
              className="h-[88px] animate-pulse rounded-lg border border-gray-100 bg-gray-50"
            />
          ))}
        </div>
      ) : isEmpty ? (
        <div className="flex flex-col items-center justify-center gap-2 rounded-lg border border-dashed border-gray-200 bg-gray-50 py-8 text-center">
          <CheckCircle2 className="h-8 w-8 text-primary-500" />
          <p className="text-sm font-medium text-gray-700">
            오늘 처리할 일이 없습니다
          </p>
          <p className="text-xs text-gray-500">
            여유로운 하루 보내세요
          </p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-3 md:grid-cols-3">
          {tasks.map((task) => (
            <button
              key={task.key}
              type="button"
              onClick={task.onClick}
              className={cn(
                'flex items-center gap-3 rounded-lg border border-gray-100 p-4 text-left transition-shadow',
                'hover:bg-gray-50 hover:shadow-sm'
              )}
            >
              <div
                className={cn(
                  'flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-lg',
                  task.iconColor
                )}
              >
                <task.icon className="h-5 w-5" />
              </div>
              <div className="min-w-0 flex-1">
                <p className="truncate text-xs text-gray-500">{task.label}</p>
                <p className="mt-0.5 text-xl font-semibold text-gray-900">
                  {task.count}
                  <span className="ml-1 text-sm font-normal text-gray-500">
                    건
                  </span>
                </p>
              </div>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}
