'use client';

import { useState } from 'react';
import { useParams, useRouter } from 'next/navigation';
import {
  ArrowLeft,
  FileText,
  MessageCircle,
  Package,
  ShoppingBag,
  UserPlus,
} from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import StatusBadge from '@/components/common/StatusBadge';
import CreateOrderModal from '@/components/buyer/CreateOrderModal';
import { useProductDetail } from '@/hooks/useProducts';
import { useCreateChatRoom } from '@/hooks/useChat';
import { useAuthStore } from '@/store/authStore';
import { CATEGORY_OPTIONS } from '@/constants/options';
import { cn } from '@/lib/utils';
import type {
  PartnerRelationshipStatus,
  Product,
  ProductDetailResponse,
  ProductMinimal,
} from '@/types';

// 거래처 관계 상태 → 사람이 읽는 라벨 + 색상 클래스
function partnerStatusBadge(status: PartnerRelationshipStatus | null) {
  switch (status) {
    case 'ACTIVE':
      return { label: '거래 중', cls: 'bg-primary-100 text-primary-700' };
    case 'PENDING_OUTGOING':
      return { label: '신청 대기', cls: 'bg-yellow-100 text-yellow-700' };
    case 'PENDING_INCOMING':
      return { label: '신청 받음', cls: 'bg-blue-100 text-blue-700' };
    case 'INACTIVE':
      return { label: '비활성', cls: 'bg-gray-100 text-gray-500' };
    case null:
    default:
      return { label: '신규', cls: 'bg-gray-100 text-gray-600' };
  }
}

function categoryLabel(category: string) {
  return (
    CATEGORY_OPTIONS.find((c) => c.value === category)?.label || category
  );
}

export default function BuyerProductDetailPage() {
  const params = useParams<{ productId: string }>();
  const productId = params?.productId ?? '';
  const router = useRouter();
  const { user } = useAuthStore();

  const { data, isLoading, error } = useProductDetail(productId);
  const product = data?.data;

  const createChatRoom = useCreateChatRoom();
  const [isInquiryLoading, setIsInquiryLoading] = useState(false);
  const [orderModalProduct, setOrderModalProduct] =
    useState<Product | null>(null);

  const handleInquiry = async () => {
    if (!product || !user || isInquiryLoading) return;
    setIsInquiryLoading(true);
    try {
      const res = await createChatRoom.mutateAsync({
        partner_user_id: product.seller_id,
        inquiry_product_id: product.id,
      });
      router.push(`/buyer/chat?room_id=${res.data.id}`);
    } catch (e) {
      console.error('[buyer/browse/detail] 문의 채팅방 생성 실패:', e);
    } finally {
      setIsInquiryLoading(false);
    }
  };

  const handleQuoteRequest = () => {
    if (!product) return;
    setOrderModalProduct(product);
  };

  if (isLoading) {
    return (
      <div>
        <PageHeader title="상품 상세" />
        <div className="rounded-xl bg-white p-12 text-center text-sm text-gray-400 shadow-sm">
          상품 정보를 불러오는 중...
        </div>
      </div>
    );
  }

  if (error || !product) {
    return (
      <div>
        <PageHeader title="상품 상세" />
        <div className="rounded-xl bg-white p-12 text-center shadow-sm">
          <Package className="mx-auto mb-3 h-12 w-12 text-gray-300" />
          <p className="text-sm text-gray-500">
            상품을 찾을 수 없거나 접근할 수 없습니다.
          </p>
          <button
            onClick={() => router.push('/buyer/browse')}
            className="mt-4 inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            상품 목록으로
          </button>
        </div>
      </div>
    );
  }

  const isOutOfStock = product.stock_quantity === 0;
  const partnerStatusMeta = partnerStatusBadge(
    product.partner_relationship_status
  );

  return (
    <div>
      {/* 상단 — 뒤로가기 + PageHeader */}
      <div className="mb-3">
        <button
          onClick={() => router.push('/buyer/browse')}
          className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-700"
        >
          <ArrowLeft className="h-3.5 w-3.5" />
          상품 목록으로
        </button>
      </div>

      <PageHeader title={product.name} description="상품 상세 정보" />

      {/* Hero 영역 — 좁은 화면에선 column 스택, lg 이상은 2단 그리드 */}
      <div className="mb-6 grid grid-cols-1 gap-6 rounded-xl bg-white p-4 shadow-sm md:p-6 lg:grid-cols-2">
        {/* 좌측 — 큰 이미지 */}
        <div className="flex aspect-square w-full items-center justify-center overflow-hidden rounded-lg bg-gray-50">
          {product.image_url ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={product.image_url}
              alt={product.name}
              className="h-full w-full object-cover"
            />
          ) : (
            <Package className="h-24 w-24 text-gray-300" />
          )}
        </div>

        {/* 우측 — 상품 핵심 정보 */}
        <div className="flex flex-col">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-700">
              {categoryLabel(product.category)}
            </span>
            {product.origin && (
              <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-700">
                원산지 {product.origin}
              </span>
            )}
            {product.spec && (
              <span className="inline-flex items-center rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-700">
                {product.spec}
              </span>
            )}
            <StatusBadge status={product.status} />
          </div>

          <h2 className="mb-2 text-xl font-semibold text-gray-900 sm:text-2xl">
            {product.name}
          </h2>

          <div className="mb-4 flex items-baseline gap-1">
            <span className="text-2xl font-bold text-gray-900">
              {product.price_per_unit.toLocaleString()}원
            </span>
            <span className="text-sm text-gray-500">/ {product.unit}</span>
          </div>

          <div className="mb-4 grid grid-cols-2 gap-2 text-xs">
            <div className="rounded-lg bg-gray-50 px-3 py-2">
              <p className="text-[11px] text-gray-500">재고</p>
              <p
                className={cn(
                  'mt-0.5 text-sm font-medium',
                  product.stock_quantity > 0
                    ? 'text-gray-900'
                    : 'text-red-500'
                )}
              >
                {product.stock_quantity.toLocaleString()} {product.unit}
              </p>
            </div>
            <div className="rounded-lg bg-gray-50 px-3 py-2">
              <p className="text-[11px] text-gray-500">최소 주문 수량</p>
              <p className="mt-0.5 text-sm font-medium text-gray-900">
                {product.min_order_qty?.toLocaleString() ?? 1} {product.unit}
              </p>
            </div>
          </div>

          {/* 액션 버튼 */}
          <div className="mt-auto flex flex-col gap-2 sm:flex-row">
            <button
              onClick={handleInquiry}
              disabled={isOutOfStock || isInquiryLoading}
              className={cn(
                'flex flex-1 items-center justify-center gap-1.5 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors',
                isOutOfStock
                  ? 'cursor-not-allowed bg-gray-100 text-gray-400'
                  : isInquiryLoading
                    ? 'cursor-wait bg-gray-100 text-gray-500'
                    : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
              )}
            >
              <MessageCircle className="h-4 w-4" />
              {isInquiryLoading ? '연결 중...' : '문의하기'}
            </button>
            <button
              onClick={handleQuoteRequest}
              disabled={isOutOfStock}
              className={cn(
                'flex flex-1 items-center justify-center gap-1.5 rounded-lg px-4 py-2.5 text-sm font-medium transition-colors',
                isOutOfStock
                  ? 'cursor-not-allowed bg-gray-100 text-gray-400'
                  : 'bg-primary-600 text-white hover:bg-primary-700'
              )}
            >
              <FileText className="h-4 w-4" />
              견적 요청
            </button>
          </div>

          {/* 거래처 등록 안내 — 신규(거래 이력 없음)일 때만 노출 */}
          {product.partner_relationship_status === null && (
            <button
              onClick={() => router.push('/buyer/partners')}
              className="mt-3 inline-flex items-center gap-1 text-xs font-medium text-primary-700 hover:underline"
            >
              <UserPlus className="h-3.5 w-3.5" />
              이 판매자를 거래처로 등록하시겠어요?
            </button>
          )}
        </div>
      </div>

      {/* 상품 정보 그리드 (라벨/값) */}
      <div className="mb-6 rounded-xl bg-white p-4 shadow-sm md:p-6">
        <h3 className="mb-3 text-sm font-semibold text-gray-900">상품 정보</h3>
        <dl className="grid grid-cols-2 gap-x-4 gap-y-3 text-sm sm:grid-cols-4">
          <InfoCell label="카테고리" value={categoryLabel(product.category)} />
          <InfoCell label="원산지" value={product.origin || '-'} />
          <InfoCell label="규격" value={product.spec || '-'} />
          <InfoCell label="단위" value={product.unit} />
          <InfoCell
            label="단가"
            value={`${product.price_per_unit.toLocaleString()}원 / ${product.unit}`}
          />
          <InfoCell
            label="재고"
            value={`${product.stock_quantity.toLocaleString()} ${product.unit}`}
          />
          <InfoCell
            label="최소 주문 수량"
            value={`${(product.min_order_qty ?? 1).toLocaleString()} ${product.unit}`}
          />
          <InfoCell
            label="상태"
            value={<StatusBadge status={product.status} />}
          />
        </dl>
      </div>

      {/* 판매자 정보 카드 */}
      <div className="mb-6 rounded-xl bg-white p-4 shadow-sm md:p-6">
        <h3 className="mb-3 text-sm font-semibold text-gray-900">판매자 정보</h3>
        <div className="flex flex-col gap-2 sm:flex-row sm:items-center sm:justify-between">
          <div>
            <p className="text-base font-semibold text-gray-900">
              {product.seller_company || '회사명 미등록'}
            </p>
            <p className="mt-0.5 text-xs text-gray-500">
              담당자 {product.seller_name || '미등록'}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-2">
            <span
              className={cn(
                'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
                partnerStatusMeta.cls
              )}
            >
              {partnerStatusMeta.label}
            </span>
            {product.previous_order_count > 0 && (
              <span className="inline-flex items-center gap-1 rounded-full bg-gray-100 px-2.5 py-0.5 text-xs text-gray-700">
                <ShoppingBag className="h-3 w-3" />총 {product.previous_order_count}건 거래
              </span>
            )}
          </div>
        </div>
      </div>

      {/* 상세 설명 */}
      <div className="mb-6 rounded-xl bg-white p-4 shadow-sm md:p-6">
        <h3 className="mb-3 text-sm font-semibold text-gray-900">상세 설명</h3>
        {product.description ? (
          <p className="whitespace-pre-wrap text-sm leading-relaxed text-gray-700">
            {product.description}
          </p>
        ) : (
          <p className="text-sm text-gray-400">상세 설명이 없습니다.</p>
        )}
      </div>

      {/* 같은 판매자의 다른 상품 */}
      {product.other_seller_products.length > 0 && (
        <div className="mb-6 rounded-xl bg-white p-4 shadow-sm md:p-6">
          <h3 className="mb-3 text-sm font-semibold text-gray-900">
            이 판매자의 다른 상품
          </h3>
          <OtherProductsGrid
            products={product.other_seller_products}
            onSelect={(p) => router.push(`/buyer/browse/${p.id}`)}
          />
        </div>
      )}

      {/* 견적 요청 모달 */}
      <CreateOrderModal
        isOpen={!!orderModalProduct}
        onClose={() => setOrderModalProduct(null)}
        initialSellerId={orderModalProduct?.seller_id}
        initialItem={
          orderModalProduct
            ? {
                product_id: orderModalProduct.id,
                quantity: 1,
                unit_price: orderModalProduct.price_per_unit,
              }
            : undefined
        }
      />
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────

function InfoCell({
  label,
  value,
}: {
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div>
      <dt className="text-[11px] text-gray-500">{label}</dt>
      <dd className="mt-0.5 text-sm font-medium text-gray-900">{value}</dd>
    </div>
  );
}

function OtherProductsGrid({
  products,
  onSelect,
}: {
  products: ProductMinimal[];
  onSelect: (p: ProductMinimal) => void;
}) {
  return (
    <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
      {products.map((p) => (
        <button
          key={p.id}
          onClick={() => onSelect(p)}
          className="group overflow-hidden rounded-lg border border-gray-100 bg-white text-left shadow-sm transition-shadow hover:shadow-md"
        >
          <div className="flex h-24 items-center justify-center bg-gray-50">
            {p.image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={p.image_url}
                alt={p.name}
                className="h-full w-full object-cover"
              />
            ) : (
              <Package className="h-8 w-8 text-gray-300" />
            )}
          </div>
          <div className="p-2.5">
            <p className="mb-0.5 truncate text-xs font-semibold text-gray-900">
              {p.name}
            </p>
            <p className="text-[11px] text-gray-500">
              {categoryLabel(p.category)}
            </p>
            <div className="mt-1 flex items-baseline gap-0.5">
              <span className="text-sm font-bold text-gray-900">
                {p.price_per_unit.toLocaleString()}원
              </span>
              <span className="text-[11px] text-gray-500">/ {p.unit}</span>
            </div>
          </div>
        </button>
      ))}
    </div>
  );
}
