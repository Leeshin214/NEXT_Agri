'use client';

import { useState } from 'react';
import { Calendar, Check, Clock, X } from 'lucide-react';
import {
  useAcceptDeliveryDateChange,
  useDeliveryDateChanges,
  useRejectDeliveryDateChange,
  useSubmitDeliveryDateChange,
} from '@/hooks/useDeliveryDateChanges';
import { useAuthStore } from '@/store/authStore';
import { cn } from '@/lib/utils';
import type {
  DeliveryDateChange,
  DeliveryDateChangeStatus,
  FromRole,
  OrderStatus,
} from '@/types';

interface DeliveryDateChangeSectionProps {
  orderId: string;
  orderStatus: OrderStatus;
  currentDeliveryDate: string | null;
}

/**
 * 납품일 변경 요청·승인 섹션.
 *
 * 위치: 주문 상세 슬라이드 패널의 NegotiationHistory 바로 아래.
 * 기능:
 *  - 현재 납품일 표시
 *  - 변경 가능 상태(QUOTE_REQUESTED/NEGOTIATING/CONFIRMED) 에서만 변경 요청 폼 노출
 *  - PREPARING 이상이면 "출하 준비 중" 안내
 *  - 변경 이력 타임라인 (시간 역순, 상태 뱃지)
 *  - 가장 최신 PENDING 이 상대방 제안이면 수락/거절 버튼 노출
 */

const CHANGEABLE_STATUSES: OrderStatus[] = [
  'QUOTE_REQUESTED',
  'NEGOTIATING',
  'CONFIRMED',
];

const statusLabel: Record<DeliveryDateChangeStatus, string> = {
  PENDING: '응답 대기',
  ACCEPTED: '수락',
  REJECTED: '거절',
  SUPERSEDED: '대체됨',
};

const statusClassName: Record<DeliveryDateChangeStatus, string> = {
  PENDING: 'bg-yellow-100 text-yellow-800',
  ACCEPTED: 'bg-green-100 text-green-800',
  REJECTED: 'bg-red-100 text-red-800',
  SUPERSEDED: 'bg-gray-100 text-gray-600',
};

const roleLabel: Record<FromRole, string> = {
  SELLER: '판매자',
  BUYER: '구매자',
};

const roleBadgeClassName: Record<FromRole, string> = {
  SELLER: 'bg-blue-50 text-blue-700',
  BUYER: 'bg-primary-50 text-primary-700',
};

function formatDate(iso: string | null | undefined): string {
  if (!iso) return '-';
  try {
    return new Date(iso).toLocaleDateString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
    });
  } catch {
    return iso;
  }
}

function formatDateTime(iso: string): string {
  try {
    return new Date(iso).toLocaleString('ko-KR', {
      year: 'numeric',
      month: '2-digit',
      day: '2-digit',
      hour: '2-digit',
      minute: '2-digit',
    });
  } catch {
    return iso;
  }
}

/** 오늘 날짜 (YYYY-MM-DD) — date input 의 min 으로 사용 */
function todayISO(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export default function DeliveryDateChangeSection({
  orderId,
  orderStatus,
  currentDeliveryDate,
}: DeliveryDateChangeSectionProps) {
  const { user } = useAuthStore();
  const { data, isLoading } = useDeliveryDateChanges(orderId);
  const submitMutation = useSubmitDeliveryDateChange(orderId);
  const acceptMutation = useAcceptDeliveryDateChange(orderId);
  const rejectMutation = useRejectDeliveryDateChange(orderId);

  const [showForm, setShowForm] = useState(false);
  const [proposedDate, setProposedDate] = useState('');
  const [notes, setNotes] = useState('');
  const [error, setError] = useState<string | null>(null);

  const changes: DeliveryDateChange[] = data?.data ?? [];
  // 백엔드가 시간 역순으로 반환하지만, 안전하게 다시 정렬
  const sorted = [...changes].sort((a, b) =>
    b.created_at.localeCompare(a.created_at)
  );

  const isChangeable = CHANGEABLE_STATUSES.includes(orderStatus);

  // 가장 최신 PENDING 이 상대방 제안이면 수락/거절 가능
  const latestPending = sorted.find((c) => c.status === 'PENDING');
  const canRespond =
    !!latestPending &&
    !!user &&
    latestPending.from_user_id !== user.id &&
    isChangeable;

  const isMine = (change: DeliveryDateChange): boolean =>
    !!user && change.from_user_id === user.id;

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!proposedDate) {
      setError('변경할 납품일을 선택하세요');
      return;
    }
    // 오늘 이전 날짜 차단 (백엔드 검증과 일치)
    if (proposedDate < todayISO()) {
      setError('오늘 이후 날짜만 선택할 수 있습니다');
      return;
    }
    if (proposedDate === currentDeliveryDate) {
      setError('현재 납품일과 다른 날짜를 선택하세요');
      return;
    }

    try {
      await submitMutation.mutateAsync({
        proposed_delivery_date: proposedDate,
        notes: notes || undefined,
      });
      setShowForm(false);
      setProposedDate('');
      setNotes('');
    } catch (err) {
      setError(
        err instanceof Error ? err.message : '납품일 변경 요청에 실패했습니다'
      );
    }
  };

  const handleAccept = (changeId: string) => {
    if (!isChangeable) return;
    acceptMutation.mutate({ changeId });
  };

  const handleReject = (changeId: string) => {
    if (!isChangeable) return;
    rejectMutation.mutate({ changeId });
  };

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <p className="text-xs font-medium text-gray-500">납품일 변경</p>
        {isChangeable && !showForm && (
          <button
            type="button"
            onClick={() => setShowForm(true)}
            className="inline-flex items-center gap-1 rounded-lg border border-primary-600 bg-white px-2.5 py-1 text-[11px] font-medium text-primary-700 hover:bg-primary-50"
          >
            <Calendar className="h-3 w-3" />
            변경 요청
          </button>
        )}
      </div>

      {/* 현재 납품일 */}
      <div className="mb-2 flex items-center justify-between rounded-lg bg-gray-50 px-3 py-2 text-xs">
        <span className="text-gray-500">현재 납품일</span>
        <span className="font-medium text-gray-900">
          {currentDeliveryDate ? formatDate(currentDeliveryDate) : '미정'}
        </span>
      </div>

      {/* PREPARING 이상 안내 */}
      {!isChangeable && (
        <p className="mb-2 rounded-lg bg-amber-50 px-3 py-2 text-[11px] text-amber-800">
          출하 준비 중이라 납품일을 변경할 수 없습니다.
        </p>
      )}

      {/* 변경 요청 폼 */}
      {showForm && isChangeable && (
        <form
          onSubmit={handleSubmit}
          className="mb-2 space-y-2 rounded-lg border border-primary-200 bg-primary-50/40 p-3"
        >
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">
              새 납품일 *
            </label>
            <input
              type="date"
              min={todayISO()}
              value={proposedDate}
              onChange={(e) => setProposedDate(e.target.value)}
              required
              className="w-full rounded-md border border-gray-300 px-3 py-1.5 text-xs focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-[11px] font-medium text-gray-700">
              메모
            </label>
            <textarea
              value={notes}
              onChange={(e) => setNotes(e.target.value)}
              rows={2}
              placeholder="변경 사유 등 (선택)"
              className="w-full resize-none rounded-md border border-gray-300 px-3 py-1.5 text-xs focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
          {error && (
            <p className="rounded-md bg-red-50 px-2 py-1 text-[11px] text-red-700">
              {error}
            </p>
          )}
          <div className="flex justify-end gap-1.5">
            <button
              type="button"
              onClick={() => {
                setShowForm(false);
                setProposedDate('');
                setNotes('');
                setError(null);
              }}
              className="rounded-md border border-gray-300 bg-white px-2.5 py-1 text-[11px] hover:bg-gray-50"
            >
              취소
            </button>
            <button
              type="submit"
              disabled={submitMutation.isPending}
              className="rounded-md bg-primary-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-primary-700 disabled:opacity-50"
            >
              {submitMutation.isPending ? '요청 중...' : '변경 요청'}
            </button>
          </div>
        </form>
      )}

      {/* 변경 이력 타임라인 */}
      {isLoading ? (
        <div className="rounded-lg bg-gray-50 p-3 text-xs text-gray-400">
          로딩 중...
        </div>
      ) : sorted.length === 0 ? (
        <div className="rounded-lg bg-gray-50 p-3 text-xs text-gray-400">
          납품일 변경 이력이 없습니다.
        </div>
      ) : (
        <ul className="space-y-2">
          {sorted.map((change) => {
            const fromRole = change.from_role;
            const showActions =
              canRespond &&
              latestPending &&
              latestPending.id === change.id &&
              !isMine(change);
            return (
              <li
                key={change.id}
                className="rounded-lg border border-gray-200 bg-white p-3"
              >
                <div className="mb-1 flex items-center justify-between gap-2">
                  <div className="flex items-center gap-2">
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                        roleBadgeClassName[fromRole]
                      )}
                    >
                      {roleLabel[fromRole]}
                    </span>
                    <span
                      className={cn(
                        'inline-flex items-center rounded-full px-2 py-0.5 text-[10px] font-medium',
                        statusClassName[change.status]
                      )}
                    >
                      {statusLabel[change.status]}
                    </span>
                  </div>
                  <span className="text-[10px] text-gray-400">
                    {formatDateTime(change.created_at)}
                  </span>
                </div>
                <p className="flex items-center gap-1.5 text-sm font-semibold text-gray-900">
                  <Calendar className="h-3.5 w-3.5 text-gray-500" />
                  {formatDate(change.proposed_delivery_date)}
                </p>
                {change.notes && (
                  <p className="mt-1 whitespace-pre-wrap text-xs text-gray-600">
                    {change.notes}
                  </p>
                )}
                {/* 액션 영역 */}
                {change.status === 'PENDING' && isMine(change) && (
                  <p className="mt-2 inline-flex items-center gap-1 text-xs text-gray-500">
                    <Clock className="h-3 w-3" />
                    상대방 응답 대기 중
                  </p>
                )}
                {showActions && (
                  <div className="mt-2 flex gap-2">
                    <button
                      onClick={() => handleAccept(change.id)}
                      disabled={
                        acceptMutation.isPending || rejectMutation.isPending
                      }
                      className="inline-flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                    >
                      <Check className="h-3 w-3" />
                      수락
                    </button>
                    <button
                      onClick={() => handleReject(change.id)}
                      disabled={
                        acceptMutation.isPending || rejectMutation.isPending
                      }
                      className="inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:opacity-50"
                    >
                      <X className="h-3 w-3" />
                      거절
                    </button>
                  </div>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}
