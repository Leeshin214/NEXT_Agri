'use client';

import { Package, MessageSquare } from 'lucide-react';
import type { ChatRoom } from '@/types';
import { cn } from '@/lib/utils';

interface ChatRoomItemProps {
  room: ChatRoom;
  selected: boolean;
  onSelect: (roomId: string) => void;
  /** 그룹 내 들여쓰기/연결선 표시 여부 */
  nested?: boolean;
}

/**
 * 채팅 리스트의 단일 방 카드.
 *
 * 그룹 내부에서 사용될 때(nested=true)는 좌측 보더 + 들여쓰기로 종속 관계를 표현한다.
 * order_id 가 있으면 패키지 아이콘, 없으면 일반 대화 아이콘으로 구분.
 */
export default function ChatRoomItem({
  room,
  selected,
  onSelect,
  nested = false,
}: ChatRoomItemProps) {
  const isOrderRoom = !!room.order_id;
  const Icon = isOrderRoom ? Package : MessageSquare;
  const subLabel = isOrderRoom ? '주문 채팅' : '일반 대화';

  return (
    <button
      onClick={() => onSelect(room.id)}
      className={cn(
        'w-full border-b border-gray-100 text-left hover:bg-gray-50 transition-colors',
        nested ? 'pl-8 pr-3 py-2.5' : 'p-4',
        nested && 'border-l-2 border-l-transparent',
        selected && 'bg-primary-50',
        selected && nested && 'border-l-primary-400'
      )}
    >
      <div className="flex items-center justify-between gap-2">
        <div className="flex min-w-0 flex-1 items-center gap-2">
          <Icon
            className={cn(
              'h-3.5 w-3.5 flex-shrink-0',
              isOrderRoom ? 'text-primary-500' : 'text-gray-400'
            )}
            aria-hidden="true"
          />
          <p className="truncate text-xs font-medium text-gray-700">
            {subLabel}
          </p>
        </div>
        {room.unread_count > 0 && (
          <span className="flex h-5 min-w-[20px] flex-shrink-0 items-center justify-center rounded-full bg-primary-600 px-1.5 text-[10px] font-bold text-white">
            {room.unread_count}
          </span>
        )}
      </div>
      {room.last_message ? (
        <p className="mt-1 truncate text-xs text-gray-400">
          {room.last_message}
        </p>
      ) : (
        <p className="mt-1 truncate text-xs text-gray-300">
          아직 메시지가 없습니다.
        </p>
      )}
    </button>
  );
}
