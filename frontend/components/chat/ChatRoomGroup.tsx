'use client';

import { useState } from 'react';
import { ChevronDown, ChevronRight, Package } from 'lucide-react';
import type { ChatRoomGroup as ChatRoomGroupType } from '@/lib/chatGrouping';
import ChatRoomItem from './ChatRoomItem';
import { cn } from '@/lib/utils';

interface ChatRoomGroupProps {
  group: ChatRoomGroupType;
  selectedRoomId: string | null;
  onSelectRoom: (roomId: string) => void;
  /** 기본 펼침 여부 — 보통 true */
  defaultExpanded?: boolean;
}

/**
 * 거래처 단위 그룹 카드.
 *
 * - 헤더: 거래처 이름/회사 + 미읽 합계 + 진행 주문 개수 + 최근 활동 시각 + 펼침 화살표
 * - 본문: 펼쳐졌을 때 그룹 내 ChatRoom 들을 ChatRoomItem 으로 렌더 (nested=true)
 */
export default function ChatRoomGroup({
  group,
  selectedRoomId,
  onSelectRoom,
  defaultExpanded = true,
}: ChatRoomGroupProps) {
  const [expanded, setExpanded] = useState(defaultExpanded);

  // 그룹 안에 선택된 방이 있으면 강제 펼침 — 사용자가 접어둔 그룹의 방으로
  // 다른 화면에서 라우팅됐을 때 자동으로 보이게 한다.
  const containsSelected = group.rooms.some((r) => r.id === selectedRoomId);
  const isExpanded = expanded || containsSelected;

  const Chevron = isExpanded ? ChevronDown : ChevronRight;
  const displayName = group.partnerName ?? '거래처';
  const lastActivityLabel = formatRelativeTime(group.lastActivityAt);

  return (
    <div className="border-b border-gray-200 last:border-b-0">
      {/* 그룹 헤더 */}
      <button
        type="button"
        onClick={() => setExpanded((v) => !v)}
        className={cn(
          'w-full px-4 py-3 text-left hover:bg-gray-50 transition-colors',
          isExpanded && 'bg-gray-50/60'
        )}
        aria-expanded={isExpanded}
      >
        <div className="flex items-center gap-2">
          <Chevron className="h-4 w-4 flex-shrink-0 text-gray-400" aria-hidden="true" />
          <div className="min-w-0 flex-1">
            <div className="flex items-center justify-between gap-2">
              <p className="truncate text-sm font-semibold text-gray-900">
                {displayName}
              </p>
              {group.unreadTotal > 0 && (
                <span className="flex h-5 min-w-[20px] flex-shrink-0 items-center justify-center rounded-full bg-primary-600 px-1.5 text-[10px] font-bold text-white">
                  {group.unreadTotal}
                </span>
              )}
            </div>
            <div className="mt-0.5 flex items-center gap-2 text-[11px] text-gray-500">
              {group.partnerCompany && (
                <span className="truncate">{group.partnerCompany}</span>
              )}
              {group.activeOrderCount > 0 && (
                <span className="flex items-center gap-0.5 flex-shrink-0">
                  <Package className="h-3 w-3" aria-hidden="true" />
                  주문 {group.activeOrderCount}
                </span>
              )}
              {lastActivityLabel && (
                <span className="ml-auto flex-shrink-0">{lastActivityLabel}</span>
              )}
            </div>
          </div>
        </div>
      </button>

      {/* 그룹 본문 — 하위 채팅방 카드들 */}
      {isExpanded && (
        <div>
          {group.rooms.map((room) => (
            <ChatRoomItem
              key={room.id}
              room={room}
              selected={selectedRoomId === room.id}
              onSelect={onSelectRoom}
              nested
            />
          ))}
        </div>
      )}
    </div>
  );
}

/**
 * "방금 전" / "N분 전" / "N시간 전" / "N일 전" 형식 상대 시각.
 * NegotiationHistory 와 동일 패턴.
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
  // 일주일 이상은 짧은 날짜 (MM.DD)
  const d = new Date(iso);
  return `${d.getMonth() + 1}.${d.getDate()}`;
}
