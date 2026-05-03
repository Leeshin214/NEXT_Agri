'use client';

import { useMemo, useState } from 'react';
import { Search, Filter } from 'lucide-react';
import type { ChatRoom } from '@/types';
import { groupChatRoomsByPartner } from '@/lib/chatGrouping';
import ChatRoomGroup from './ChatRoomGroup';
import { cn } from '@/lib/utils';

interface ChatRoomListProps {
  rooms: ChatRoom[];
  /** 본인 역할 — partner_user_id 결정용 */
  myRole: 'SELLER' | 'BUYER';
  selectedRoomId: string | null;
  onSelectRoom: (roomId: string) => void;
  isLoading?: boolean;
  error?: unknown;
  onRetry?: () => void;
}

/**
 * 거래처별 그룹핑된 채팅방 리스트.
 *
 * - 검색: 거래처 이름 / 회사명 부분일치 → 매칭되는 그룹 전체 표시
 * - 필터: "미읽만 보기" 토글 → unreadTotal > 0 인 그룹만 표시
 * - 그룹 헤더 클릭 시 펼침/접힘 (각 그룹 컴포넌트 내부 state)
 *
 * 양쪽 역할(seller/buyer) 모두 동일하게 사용된다.
 */
export default function ChatRoomList({
  rooms,
  myRole,
  selectedRoomId,
  onSelectRoom,
  isLoading,
  error,
  onRetry,
}: ChatRoomListProps) {
  const [search, setSearch] = useState('');
  const [unreadOnly, setUnreadOnly] = useState(false);

  // 그룹핑 + 검색 + 미읽 필터
  const groups = useMemo(() => {
    const all = groupChatRoomsByPartner(rooms, myRole);
    const trimmed = search.trim().toLowerCase();
    return all.filter((g) => {
      if (unreadOnly && g.unreadTotal === 0) return false;
      if (!trimmed) return true;
      const name = (g.partnerName ?? '').toLowerCase();
      const company = (g.partnerCompany ?? '').toLowerCase();
      return name.includes(trimmed) || company.includes(trimmed);
    });
  }, [rooms, myRole, search, unreadOnly]);

  // 검색 또는 필터가 적용된 상태인지 — 빈 결과 안내 메시지 분기에 사용
  const isFiltered = search.trim().length > 0 || unreadOnly;

  return (
    <div className="flex h-full flex-col">
      {/* 검색 + 필터 바 */}
      <div className="flex flex-col gap-2 border-b border-gray-200 p-3">
        <div className="relative">
          <Search
            className="absolute left-2.5 top-1/2 h-3.5 w-3.5 -translate-y-1/2 text-gray-400"
            aria-hidden="true"
          />
          <input
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="거래처 검색"
            className="w-full rounded-lg border border-gray-200 bg-gray-50 py-1.5 pl-8 pr-2 text-xs focus:border-primary-500 focus:bg-white focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>
        <button
          type="button"
          onClick={() => setUnreadOnly((v) => !v)}
          className={cn(
            'flex items-center justify-center gap-1.5 rounded-lg border px-2 py-1 text-[11px] font-medium transition-colors',
            unreadOnly
              ? 'border-primary-500 bg-primary-50 text-primary-700'
              : 'border-gray-200 bg-white text-gray-500 hover:bg-gray-50'
          )}
          aria-pressed={unreadOnly}
        >
          <Filter className="h-3 w-3" aria-hidden="true" />
          미읽만 보기
        </button>
      </div>

      {/* 본문 */}
      <div className="flex-1 overflow-y-auto">
        {isLoading ? (
          <div className="flex items-center justify-center p-8">
            <div className="h-6 w-6 animate-spin rounded-full border-2 border-primary-600 border-t-transparent" />
          </div>
        ) : error ? (
          <div className="p-4 text-sm text-red-500">
            채팅방을 불러오지 못했습니다.
            {onRetry && (
              <button
                onClick={onRetry}
                className="ml-2 text-primary-600 underline"
              >
                다시 시도
              </button>
            )}
          </div>
        ) : rooms.length === 0 ? (
          <p className="p-4 text-sm text-gray-400">채팅방이 없습니다.</p>
        ) : groups.length === 0 ? (
          <p className="p-4 text-sm text-gray-400">
            {isFiltered
              ? '조건에 맞는 거래처가 없습니다.'
              : '채팅방이 없습니다.'}
          </p>
        ) : (
          groups.map((g) => (
            <ChatRoomGroup
              key={g.partnerUserId}
              group={g}
              selectedRoomId={selectedRoomId}
              onSelectRoom={onSelectRoom}
            />
          ))
        )}
      </div>
    </div>
  );
}
