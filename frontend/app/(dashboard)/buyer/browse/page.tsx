'use client';

import { useState } from 'react';
import { Package, ShoppingCart } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import StatusBadge from '@/components/common/StatusBadge';
import { useProducts } from '@/hooks/useProducts';
import { CATEGORY_OPTIONS } from '@/constants/options';
import { cn } from '@/lib/utils';

export default function BuyerBrowsePage() {
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');

  const { data, isLoading } = useProducts();
  const products = data?.data ?? [];

  const filtered = products.filter((p) => {
    const matchSearch =
      !search || p.name.toLowerCase().includes(search.toLowerCase());
    const matchCategory = !categoryFilter || p.category === categoryFilter;
    return matchSearch && matchCategory;
  });

  return (
    <div>
      <PageHeader title="상품 탐색" description="공급처의 상품을 둘러보세요" />

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

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      ) : filtered.length === 0 ? (
        <div className="flex flex-col items-center justify-center py-20 text-gray-400">
          <Package className="mb-3 h-12 w-12" />
          <p className="text-sm">등록된 상품이 없습니다.</p>
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2 lg:grid-cols-3 xl:grid-cols-4">
          {filtered.map((product) => (
            <div
              key={product.id}
              className="group overflow-hidden rounded-xl border border-gray-100 bg-white shadow-sm transition-shadow hover:shadow-md"
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

                <div className="flex items-center justify-between">
                  <span
                    className={cn(
                      'text-xs',
                      product.stock_quantity > 0 ? 'text-green-600' : 'text-red-500'
                    )}
                  >
                    재고: {product.stock_quantity} {product.unit}
                  </span>
                  <button
                    className="flex items-center gap-1 rounded-lg bg-primary-50 px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-100"
                    disabled={product.stock_quantity === 0}
                  >
                    <ShoppingCart className="h-3.5 w-3.5" />
                    견적 요청
                  </button>
                </div>
              </div>
            </div>
          ))}
        </div>
      )}
    </div>
  );
}
