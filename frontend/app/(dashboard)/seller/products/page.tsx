'use client';

import { useState } from 'react';
import { Plus } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import DataTable, { type Column } from '@/components/common/DataTable';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import StatusBadge from '@/components/common/StatusBadge';
import Modal from '@/components/common/Modal';
import { useProducts, useCreateProduct } from '@/hooks/useProducts';
import { CATEGORY_OPTIONS, PRODUCT_STATUS_OPTIONS, UNIT_OPTIONS } from '@/constants/options';
import type { Product, ProductCreate, ProductCategory, ProductUnit } from '@/types';

export default function SellerProductsPage() {
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showModal, setShowModal] = useState(false);

  const { data, isLoading } = useProducts({
    category: categoryFilter || undefined,
    product_status: statusFilter || undefined,
    search: search || undefined,
  });
  const createProduct = useCreateProduct();
  const products = data?.data ?? [];

  const handleCreate = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);
    const payload: ProductCreate = {
      name: form.get('name') as string,
      category: form.get('category') as ProductCategory,
      origin: (form.get('origin') as string) || undefined,
      spec: (form.get('spec') as string) || undefined,
      unit: form.get('unit') as ProductUnit,
      price_per_unit: Number(form.get('price_per_unit')),
      stock_quantity: Number(form.get('stock_quantity')) || 0,
      min_order_qty: Number(form.get('min_order_qty')) || 1,
      description: (form.get('description') as string) || undefined,
    };
    await createProduct.mutateAsync(payload);
    setShowModal(false);
  };

  const columns: Column<Product>[] = [
    {
      key: 'name',
      header: '품목명',
      render: (item) => (
        <div>
          <p className="font-medium text-gray-900">{item.name}</p>
          <p className="text-xs text-gray-500">
            {CATEGORY_OPTIONS.find((c) => c.value === item.category)?.label}
            {item.origin && ` | ${item.origin}`}
          </p>
        </div>
      ),
    },
    {
      key: 'spec',
      header: '규격',
      render: (item) => <span className="text-gray-600">{item.spec || '-'}</span>,
    },
    {
      key: 'price_per_unit',
      header: '단가',
      render: (item) => (
        <span className="text-gray-900">
          {item.price_per_unit.toLocaleString()}원/{item.unit === 'box' ? '박스' : item.unit === 'piece' ? '개' : item.unit === 'bag' ? '포대' : item.unit}
        </span>
      ),
    },
    {
      key: 'stock_quantity',
      header: '재고',
      render: (item) => (
        <span className={item.stock_quantity <= 10 ? 'font-medium text-red-600' : 'text-gray-900'}>
          {item.stock_quantity.toLocaleString()}
        </span>
      ),
    },
    {
      key: 'status',
      header: '상태',
      render: (item) => <StatusBadge status={item.status} />,
    },
  ];

  return (
    <div>
      <PageHeader
        title="상품/재고 관리"
        description="상품 등록 및 재고를 관리하세요"
        action={
          <button
            onClick={() => setShowModal(true)}
            className="flex items-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          >
            <Plus className="h-4 w-4" />
            상품 등록
          </button>
        }
      />

      <SearchFilterBar
        searchValue={search}
        onSearchChange={setSearch}
        searchPlaceholder="상품명 검색..."
        filters={[
          {
            key: 'category',
            label: '전체 카테고리',
            options: CATEGORY_OPTIONS,
            value: categoryFilter,
            onChange: setCategoryFilter,
          },
          {
            key: 'status',
            label: '전체 상태',
            options: PRODUCT_STATUS_OPTIONS,
            value: statusFilter,
            onChange: setStatusFilter,
          },
        ]}
      />

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      ) : (
        <DataTable columns={columns} data={products} emptyMessage="등록된 상품이 없습니다." />
      )}

      {/* 상품 등록 모달 */}
      <Modal isOpen={showModal} onClose={() => setShowModal(false)} title="상품 등록" size="lg">
        <form onSubmit={handleCreate} className="space-y-4">
          <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">품목명 *</label>
              <input name="name" required className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">카테고리 *</label>
              <select name="category" required className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500">
                {CATEGORY_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">원산지</label>
              <input name="origin" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">규격</label>
              <input name="spec" placeholder="특, 상, 중" className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">단위 *</label>
              <select name="unit" required className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500">
                {UNIT_OPTIONS.map((o) => <option key={o.value} value={o.value}>{o.label}</option>)}
              </select>
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">단가 (원) *</label>
              <input name="price_per_unit" type="number" required min={0} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">재고 수량</label>
              <input name="stock_quantity" type="number" defaultValue={0} min={0} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
            </div>
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">최소 주문 수량</label>
              <input name="min_order_qty" type="number" defaultValue={1} min={1} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
            </div>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">설명</label>
            <textarea name="description" rows={3} className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500" />
          </div>
          <div className="flex justify-end gap-2">
            <button type="button" onClick={() => setShowModal(false)} className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50">취소</button>
            <button type="submit" disabled={createProduct.isPending} className="rounded-lg bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700 disabled:opacity-50">
              {createProduct.isPending ? '등록 중...' : '등록'}
            </button>
          </div>
        </form>
      </Modal>
    </div>
  );
}
