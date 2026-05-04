'use client';

import { useEffect, useState } from 'react';
import { useRouter, useSearchParams } from 'next/navigation';
import { Package, MessageCircle, FileText, X } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import StatusBadge from '@/components/common/StatusBadge';
import CreateOrderModal from '@/components/buyer/CreateOrderModal';
import { useProducts } from '@/hooks/useProducts';
import { useCreateChatRoom, useSendMessage } from '@/hooks/useChat';
import { useAuthStore } from '@/store/authStore';
import { CATEGORY_OPTIONS } from '@/constants/options';
import { cn } from '@/lib/utils';
import type { Product } from '@/types';

export default function BuyerBrowsePage() {
  const router = useRouter();
  const searchParams = useSearchParams();
  const { user } = useAuthStore();
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [maxPrice, setMaxPrice] = useState('');
  const [minStock, setMinStock] = useState('');
  // 거래처 페이지에서 "주문 작성" 클릭 시 ?seller_id=... 로 진입 → 해당 판매자 상품만 필터
  const [sellerFilter, setSellerFilter] = useState<string | null>(null);
  // 채팅 문의 처리 중 상품 ID 추적 (중복 클릭 방지)
  const [chatRequestingId, setChatRequestingId] = useState<string | null>(null);
  // 견적 요청 모달에 띄울 상품
  const [orderModalProduct, setOrderModalProduct] = useState<Product | null>(
    null
  );

  // URL 쿼리 → seller_id 동기화 (거래처 페이지의 빠른 액션에서 진입)
  useEffect(() => {
    const sid = searchParams.get('seller_id');
    setSellerFilter(sid);
  }, [searchParams]);

  const clearSellerFilter = () => {
    setSellerFilter(null);
    router.replace('/buyer/browse');
  };

  const { data, isLoading } = useProducts({
    search: search || undefined,
    category: categoryFilter || undefined,
    max_price: maxPrice ? Number(maxPrice) : undefined,
    min_stock: minStock ? Number(minStock) : undefined,
    seller_id: sellerFilter || undefined,
  });
  const createChatRoom = useCreateChatRoom();
  const sendMessage = useSendMessage();

  const filtered = data?.data ?? [];

  const handleChatInquiry = async (product: Product) => {
    if (!user || chatRequestingId) return;
    setChatRequestingId(product.id);

    try {
      // 1. 채팅방 생성 (seller_id = product.seller_id)
      //    inquiry_product_id 를 함께 보내면, 백엔드가 새 채팅방인 경우 첫 시스템 메시지의
      //    metadata 에 {kind: 'product_inquiry', inquiry_product_id} 를 자동 저장한다.
      //    채팅 페이지 진입 시 헤더 미니카드 렌더에 사용됨.
      const roomRes = await createChatRoom.mutateAsync({
        partner_user_id: product.seller_id,
        inquiry_product_id: product.id,
      });
      const roomId = roomRes.data.id;

      // 2. 사용자 평문 첫 메시지 — 백엔드 시스템 메시지와 별개로 사용자 인사 1건 보냄
      //    (기존 UX 유지). last_message 도 이 텍스트로 갱신됨.
      const categoryLabel =
        CATEGORY_OPTIONS.find((c) => c.value === product.category)?.label ||
        product.category;
      await sendMessage.mutateAsync({
        roomId,
        content: `[상품 문의] 상품: ${product.name} (${categoryLabel}) / 단가: ${product.price_per_unit.toLocaleString()}원/${product.unit}`,
      });

      // 3. 채팅 페이지로 이동 (room_id 쿼리스트링)
      router.push(`/buyer/chat?room_id=${roomId}`);
    } catch {
      // 에러 시 상태만 초기화 (별도 토스트 없이 버튼 복원)
    } finally {
      setChatRequestingId(null);
    }
  };

  // 카드 자체 클릭 → 상세 페이지로
  const handleCardClick = (product: Product) => {
    router.push(`/buyer/browse/${product.id}`);
  };

  const handleQuoteRequest = (product: Product) => {
    setOrderModalProduct(product);
  };

  return (
    <div>
      <PageHeader title="상품 탐색" description="공급처의 상품을 둘러보세요" />

      {/* 거래처에서 진입한 경우 — 어떤 판매자로 좁혀졌는지 표시 + 해제 버튼 */}
      {sellerFilter && (
        <div className="mb-4 flex items-center justify-between gap-3 rounded-lg border border-primary-200 bg-primary-50 px-4 py-2.5">
          <p className="text-sm text-primary-700">
            특정 거래처의 상품만 표시 중입니다.
          </p>
          <button
            onClick={clearSellerFilter}
            className="inline-flex items-center gap-1 rounded-md px-2 py-1 text-xs font-medium text-primary-700 hover:bg-primary-100"
          >
            <X className="h-3.5 w-3.5" />
            전체 보기
          </button>
        </div>
      )}

      <SearchFilterBar
        searchValue={search}
        onSearchChange={setSearch}
        searchPlaceholder="상품명 검색..."
        filters={[
          {
            key: 'category',
            label: '전체 품목',
            value: categoryFilter,
            onChange: setCategoryFilter,
            options: CATEGORY_OPTIONS,
          },
        ]}
      />

      {/* 최대 단가 / 최소 재고 필터 */}
      <div className="mb-4 flex flex-wrap gap-3">
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-500 whitespace-nowrap">최대 단가</label>
          <input
            type="number"
            min={0}
            value={maxPrice}
            onChange={(e) => setMaxPrice(e.target.value)}
            placeholder="예: 50000"
            className="w-32 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
          <span className="text-sm text-gray-400">원</span>
        </div>
        <div className="flex items-center gap-2">
          <label className="text-sm text-gray-500 whitespace-nowrap">최소 재고</label>
          <input
            type="number"
            min={0}
            value={minStock}
            onChange={(e) => setMinStock(e.target.value)}
            placeholder="예: 10"
            className="w-24 rounded-lg border border-gray-300 px-3 py-1.5 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <Package className="mb-3 h-12 w-12" />
          <p className="text-sm">등록된 상품이 없습니다.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((product) => {
            const isChatRequesting = chatRequestingId === product.id;
            const isOutOfStock = product.stock_quantity === 0;

            return (
              <div
                key={product.id}
                onClick={() => handleCardClick(product)}
                role="button"
                tabIndex={0}
                onKeyDown={(e) => {
                  if (e.key === 'Enter' || e.key === ' ') {
                    e.preventDefault();
                    handleCardClick(product);
                  }
                }}
                className="group cursor-pointer overflow-hidden rounded-xl border border-gray-100 bg-white shadow-sm transition-shadow hover:shadow-md focus:outline-none focus:ring-2 focus:ring-primary-500"
              >
                {/* 이미지 영역 */}
                <div className="flex h-40 items-center justify-center bg-gray-50">
                  {product.image_url ? (
                    <img
                      src={product.image_url}
                      alt={product.name}
                      className="h-full w-full object-cover"
                    />
                  ) : (
                    <Package className="h-12 w-12 text-gray-300" />
                  )}
                </div>

                {/* 상품 정보 */}
                <div className="p-4">
                  <div className="mb-2 flex items-start justify-between">
                    <h3 className="text-sm font-semibold text-gray-900">
                      {product.name}
                    </h3>
                    <StatusBadge status={product.status} />
                  </div>

                  <p className="mb-1 text-xs text-gray-500">
                    {CATEGORY_OPTIONS.find((c) => c.value === product.category)?.label || product.category}
                  </p>

                  <div className="mb-3 flex items-baseline gap-1">
                    <span className="text-lg font-bold text-gray-900">
                      {product.price_per_unit.toLocaleString()}원
                    </span>
                    <span className="text-xs text-gray-500">/ {product.unit}</span>
                  </div>

                  <div className="mb-3 flex items-center justify-between">
                    <span
                      className={cn(
                        'text-xs',
                        product.stock_quantity > 0 ? 'text-green-600' : 'text-red-500'
                      )}
                    >
                      재고: {product.stock_quantity} {product.unit}
                    </span>
                  </div>

                  {/* 액션 버튼 — 문의(채팅) + 견적 요청(모달).
                      카드 자체 클릭이 상세 라우팅이므로 버튼 클릭은 stopPropagation 으로
                      카드 클릭과 충돌 방지. */}
                  <div className="flex gap-2">
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleChatInquiry(product);
                      }}
                      disabled={isOutOfStock || !!chatRequestingId}
                      className={cn(
                        'flex flex-1 items-center justify-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors',
                        isOutOfStock
                          ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                          : isChatRequesting
                            ? 'bg-gray-100 text-gray-500 cursor-wait'
                            : 'border border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
                      )}
                    >
                      <MessageCircle className="h-3.5 w-3.5" />
                      {isChatRequesting ? '연결 중...' : '문의'}
                    </button>
                    <button
                      onClick={(e) => {
                        e.stopPropagation();
                        handleQuoteRequest(product);
                      }}
                      disabled={isOutOfStock}
                      className={cn(
                        'flex flex-1 items-center justify-center gap-1 rounded-lg px-2 py-1.5 text-xs font-medium transition-colors',
                        isOutOfStock
                          ? 'bg-gray-100 text-gray-400 cursor-not-allowed'
                          : 'bg-primary-600 text-white hover:bg-primary-700'
                      )}
                    >
                      <FileText className="h-3.5 w-3.5" />
                      견적 요청
                    </button>
                  </div>
                </div>
              </div>
            );
          })}
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
