'use client';

import { useRouter } from 'next/navigation';
import { Package, ExternalLink } from 'lucide-react';
import { useProductDetail } from '@/hooks/useProducts';
import { CATEGORY_OPTIONS } from '@/constants/options';
import type { Message } from '@/types';

/**
 * 채팅방 헤더에 표시되는 "문의 상품 미니카드" (B.2/F.3, 2026-05-04).
 *
 * 진입 흐름:
 *   1. /buyer/browse 카드의 [문의] 또는 상세 페이지의 [문의하기] 클릭
 *   2. POST /chat/rooms 가 inquiry_product_id 와 함께 호출됨 → 새 채팅방이면 백엔드가
 *      자동으로 첫 시스템 메시지를 발송하고 metadata 에 {kind: 'product_inquiry', inquiry_product_id} 저장
 *   3. 채팅 페이지 진입 시 메시지 목록의 가장 오래된 시스템 메시지 metadata 에서
 *      inquiry_product_id 를 추출 → 이 컴포넌트가 해당 상품 정보를 페치해 미니카드 렌더
 *
 * 노출 가드:
 *   - props.messages 가 비어있으면 미노출
 *   - 가장 오래된 SYSTEM 메시지의 metadata.kind 가 'product_inquiry' 가 아니면 미노출
 *   - inquiry_product_id 가 없거나 무효하면 미노출
 *   - 상품 페치 실패(상품 삭제 등) 시 미노출
 *
 * 클릭:
 *   - role 에 따라 /buyer/browse/{id} 또는 /seller/products?id={id} 로 이동
 *     (현재 SELLER 측은 본인 상품만 노출되므로 라우팅 필요 시 동일하게 buyer 경로 사용 가능)
 */
interface ChatRoomInquiryProductProps {
  messages: Message[];
  /** 클릭 시 이동할 경로의 prefix — buyer 는 '/buyer/browse', seller 는 본인 상품이라 '/seller/products' 가 자연스러움 */
  role: 'buyer' | 'seller';
}

function pickInquiryProductId(messages: Message[]): string | null {
  // 가장 오래된 메시지부터 검사 — 시스템 메시지 + product_inquiry kind 이면 채택
  // (백엔드는 첫 시스템 메시지 1건만 자동 발송하므로 일반적으로 messages[0] 이 그것)
  if (!messages.length) return null;
  for (const msg of messages) {
    if (msg.message_type !== 'SYSTEM') continue;
    const meta = msg.metadata;
    if (!meta) continue;
    if (meta.kind !== 'product_inquiry') continue;
    const id = meta.inquiry_product_id;
    if (typeof id === 'string' && id.length > 0) return id;
    return null;
  }
  return null;
}

function categoryLabel(category: string) {
  return (
    CATEGORY_OPTIONS.find((c) => c.value === category)?.label || category
  );
}

export default function ChatRoomInquiryProduct({
  messages,
  role,
}: ChatRoomInquiryProductProps) {
  const router = useRouter();
  const productId = pickInquiryProductId(messages);
  const { data, isLoading, error } = useProductDetail(productId);

  // 노출 조건 모두 만족해야만 렌더 — 그 외엔 null
  if (!productId) return null;
  if (isLoading) {
    return (
      <div className="border-b border-gray-200 bg-gray-50 px-4 py-2 text-xs text-gray-500">
        문의 상품 정보를 불러오는 중...
      </div>
    );
  }
  if (error || !data?.data) return null;

  const product = data.data;
  const targetHref =
    role === 'buyer'
      ? `/buyer/browse/${product.id}`
      : `/seller/products?id=${product.id}`;

  return (
    <button
      type="button"
      onClick={() => router.push(targetHref)}
      className="flex w-full items-center gap-3 border-b border-primary-100 bg-primary-50/40 px-4 py-2.5 text-left transition-colors hover:bg-primary-50"
      aria-label={`문의 상품: ${product.name}`}
    >
      {/* 썸네일 */}
      <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-md bg-white">
        {product.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={product.image_url}
            alt={product.name}
            className="h-full w-full object-cover"
          />
        ) : (
          <Package className="h-5 w-5 text-gray-300" />
        )}
      </div>
      {/* 상품명 + 카테고리 + 단가 — 한 줄에 압축 */}
      <div className="min-w-0 flex-1">
        <p className="truncate text-xs font-medium text-gray-900">
          {product.name}
          <span className="ml-2 font-normal text-gray-500">
            {categoryLabel(product.category)}
          </span>
        </p>
        <p className="mt-0.5 truncate text-[11px] text-gray-600">
          <span className="font-medium text-gray-800">
            {product.price_per_unit.toLocaleString()}원
          </span>
          <span className="ml-0.5 text-gray-500">/ {product.unit}</span>
        </p>
      </div>
      <ExternalLink
        className="h-3.5 w-3.5 flex-shrink-0 text-primary-500"
        aria-hidden="true"
      />
    </button>
  );
}
