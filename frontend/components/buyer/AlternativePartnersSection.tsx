'use client';

import { useRouter } from 'next/navigation';
import { ExternalLink, MessageCircle, Package, Sparkles } from 'lucide-react';
import { useAlternativeRecommendations } from '@/hooks/useOrders';
import type { AlternativeCandidate } from '@/types';

/**
 * 판매자가 주문을 취소했을 때, 백엔드가 자동 생성한 대체 판매자 + 자동 견적 결과 노출.
 *
 * 노출 조건:
 *   - 호출처(주문 상세 패널)에서 selectedOrder.status === 'CANCELLED' 일 때만 mount.
 *
 * 동작:
 *   - GET /orders/{id}/alternatives 로 추천 row 조회.
 *   - data == null  → 아직 백그라운드 task 가 안 끝났거나 SELLER 가 취소한 게 아님 → 안내 문구.
 *   - found_count == 0 → "같은 상품을 파는 다른 판매자를 찾지 못했습니다".
 *   - found_count > 0  → 카드 리스트. 각 카드는 자동 견적 주문 번호와 "주문 보러가기" 링크.
 */
export default function AlternativePartnersSection({
  orderId,
}: {
  orderId: string;
}) {
  const router = useRouter();
  const { data, isLoading, isError } = useAlternativeRecommendations(orderId);

  const rec = data?.data ?? null;

  if (isLoading) {
    return (
      <div className="rounded-lg border border-emerald-100 bg-emerald-50/40 p-3">
        <div className="mb-2 flex items-center gap-1.5">
          <Sparkles className="h-3.5 w-3.5 text-emerald-600" />
          <p className="text-xs font-medium text-emerald-700">
            대체 판매자 자동 추천
          </p>
        </div>
        <p className="text-xs text-gray-500">대체 판매자 정보를 불러오는 중...</p>
      </div>
    );
  }

  if (isError) {
    return (
      <div className="rounded-lg border border-amber-200 bg-amber-50 p-3">
        <p className="text-xs text-amber-700">
          대체 판매자 정보를 불러오지 못했습니다. 잠시 후 다시 시도해 주세요.
        </p>
      </div>
    );
  }

  // 추천이 아직 없는 경우 — SELLER 취소가 아니라 BUYER 가 직접 취소한 케이스이거나,
  // 백그라운드 task 가 아직 진행 중인 케이스.
  if (!rec) {
    return null;
  }

  return (
    <div className="rounded-lg border border-emerald-200 bg-emerald-50/60 p-3">
      <div className="mb-2 flex items-center gap-1.5">
        <Sparkles className="h-3.5 w-3.5 text-emerald-600" />
        <p className="text-xs font-medium text-emerald-700">
          대체 판매자 자동 추천
        </p>
      </div>

      {rec.found_count === 0 ? (
        <p className="text-xs text-gray-600">
          같은 상품을 판매하는 다른 판매자를 찾지 못했습니다. 거래처 페이지에서
          새 판매자를 직접 검색해 보세요.
        </p>
      ) : (
        <>
          <p className="mb-2 text-xs text-gray-700">
            같은 상품을 파는 판매자 {rec.found_count}곳에 자동으로 견적을
            요청해 두었습니다. 판매자가 수락하면 알림으로 안내됩니다.
          </p>
          <ul className="space-y-2">
            {rec.candidates.map((c, i) => (
              <li key={`${c.seller_id}-${i}`}>
                <CandidateCard
                  candidate={c}
                  onOpenAutoOrder={(autoOrderId) =>
                    router.push(`/buyer/orders?id=${autoOrderId}`)
                  }
                />
              </li>
            ))}
          </ul>
        </>
      )}
    </div>
  );
}

function CandidateCard({
  candidate,
  onOpenAutoOrder,
}: {
  candidate: AlternativeCandidate;
  onOpenAutoOrder: (autoOrderId: string) => void;
}) {
  const sellerLabel =
    candidate.seller_company || candidate.seller_name || '판매자';
  const subLabel =
    candidate.seller_company && candidate.seller_name
      ? candidate.seller_name
      : '';

  const priceLabel = candidate.price_per_unit
    ? `${candidate.price_per_unit.toLocaleString('ko-KR')}원/${candidate.unit || ''}`
    : '단가 정보 없음';
  const stockLabel = `재고 ${candidate.stock_quantity.toLocaleString('ko-KR')}${candidate.unit || ''}`;
  const tradeLabel =
    candidate.trade_count > 0
      ? `이전 거래 ${candidate.trade_count}회`
      : '신규 판매자';

  return (
    <div className="rounded-lg border border-gray-200 bg-white p-3 text-sm">
      <div className="mb-1 flex items-start justify-between gap-2">
        <div className="min-w-0">
          <p className="truncate font-medium text-gray-900">{sellerLabel}</p>
          {subLabel && (
            <p className="truncate text-[11px] text-gray-500">{subLabel}</p>
          )}
        </div>
        <span className="flex-shrink-0 rounded-full bg-emerald-100 px-2 py-0.5 text-[10px] font-medium text-emerald-700">
          {tradeLabel}
        </span>
      </div>

      <div className="mb-2 flex items-center gap-1.5 text-xs text-gray-700">
        <Package className="h-3.5 w-3.5 text-gray-400" />
        <span className="truncate">{candidate.product_name}</span>
        <span className="text-gray-300">·</span>
        <span>{priceLabel}</span>
        <span className="text-gray-300">·</span>
        <span>{stockLabel}</span>
      </div>

      {candidate.auto_order_id ? (
        <button
          type="button"
          onClick={() => onOpenAutoOrder(candidate.auto_order_id!)}
          className="inline-flex items-center gap-1 rounded-md border border-primary-200 bg-primary-50 px-2.5 py-1 text-[11px] font-medium text-primary-700 hover:bg-primary-100"
        >
          <ExternalLink className="h-3 w-3" />
          자동 견적 보기
          {candidate.auto_order_number && (
            <span className="text-gray-400"> · {candidate.auto_order_number}</span>
          )}
        </button>
      ) : (
        <div className="flex items-center gap-1 text-[11px] text-amber-700">
          <MessageCircle className="h-3 w-3" />
          자동 견적 생성에 실패했습니다
          {candidate.auto_order_error && (
            <span className="text-gray-400"> ({candidate.auto_order_error})</span>
          )}
        </div>
      )}
    </div>
  );
}
