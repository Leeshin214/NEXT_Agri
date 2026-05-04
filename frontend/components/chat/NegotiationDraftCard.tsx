'use client';

import { useEffect, useMemo, useState } from 'react';
import { Lightbulb, Check, X } from 'lucide-react';
import type { NegotiationDraft } from '@/types';

interface NegotiationDraftCardProps {
  messageId: string;
  draft: NegotiationDraft;
  /** [등록] 클릭 — 부모가 PriceOfferPopover 를 prefill 한 채로 연다 */
  onAccept: (draft: NegotiationDraft) => void;
  /** [무시] 클릭 — PATCH dismiss-draft-negotiation 호출 */
  onDismiss: (messageId: string) => void;
  /** 무시 API 진행 중 (선택) */
  isDismissing?: boolean;
}

// detected_at 기준 5분 timeout — 서버는 timeout 안 함, 프론트가 시각적으로만 hide.
const TIMEOUT_MS = 5 * 60 * 1000;

/**
 * 협상 의도 감지 카드 (US-2).
 * 본인이 평문으로 협상 메시지를 보냈을 때 발신자 본인에게만 회색 박스로 노출.
 *
 * 표시 조건 (부모 MessageBubble 에서 가드):
 * - isMine === true
 * - metadata.draft_negotiation 존재
 * - dismissed_at === null
 * - 5분 안 (이 컴포넌트가 setTimeout 으로 자동 hide)
 */
export default function NegotiationDraftCard({
  messageId,
  draft,
  onAccept,
  onDismiss,
  isDismissing = false,
}: NegotiationDraftCardProps) {
  // detected_at 으로부터 5분 경과 여부 — UI 시각만, 백엔드 metadata 는 그대로 둠
  const [hidden, setHidden] = useState(false);

  useEffect(() => {
    const detected = Date.parse(draft.detected_at);
    if (!Number.isFinite(detected)) {
      // 잘못된 timestamp — 안전하게 숨김
      setHidden(true);
      return;
    }
    const remaining = detected + TIMEOUT_MS - Date.now();
    if (remaining <= 0) {
      setHidden(true);
      return;
    }
    const timer = setTimeout(() => setHidden(true), remaining);
    return () => clearTimeout(timer);
  }, [draft.detected_at]);

  // 자연어 요약 — 부분 추출도 표시 (수량만 있어도 OK)
  const summary = useMemo(() => buildSummary(draft), [draft]);

  if (hidden) return null;

  return (
    <div className="flex justify-end">
      <div className="w-full max-w-[75%] rounded-xl border border-gray-200 bg-gray-50 p-3 shadow-sm">
        <div className="mb-1.5 flex items-center gap-1.5">
          <Lightbulb className="h-3.5 w-3.5 text-amber-500" aria-hidden="true" />
          <span className="text-xs font-semibold text-gray-700">
            이 메시지를 협상 제안으로 등록할까요?
          </span>
        </div>

        {summary && (
          <p className="mb-2 text-xs text-gray-600">{summary}</p>
        )}

        <div className="flex items-center justify-end gap-2">
          <button
            type="button"
            onClick={() => onDismiss(messageId)}
            disabled={isDismissing}
            className="inline-flex items-center gap-1 rounded-md border border-gray-300 bg-white px-2.5 py-1 text-[11px] font-medium text-gray-600 hover:bg-gray-100 disabled:opacity-50"
          >
            <X className="h-3 w-3" />
            무시
          </button>
          <button
            type="button"
            onClick={() => onAccept(draft)}
            className="inline-flex items-center gap-1 rounded-md bg-primary-600 px-2.5 py-1 text-[11px] font-medium text-white hover:bg-primary-700"
          >
            <Check className="h-3 w-3" />
            등록
          </button>
        </div>
      </div>
    </div>
  );
}

// ─── helpers ─────────────────────────────────────────────────────────

function buildSummary(draft: NegotiationDraft): string | null {
  const parts: string[] = [];
  if (draft.product_name) parts.push(draft.product_name);
  if (typeof draft.quantity === 'number' && draft.quantity > 0) {
    parts.push(
      `${draft.quantity.toLocaleString('ko-KR')}${draft.unit ?? ''}`.trim()
    );
  }
  if (typeof draft.unit_price === 'number' && draft.unit_price > 0) {
    const unitSuffix = draft.unit ? `/${draft.unit}` : '';
    parts.push(
      `단가 ${draft.unit_price.toLocaleString('ko-KR')}원${unitSuffix}`
    );
  }
  if (parts.length === 0) return null;
  return parts.join(' · ');
}
