'use client';

import { useState } from 'react';
import { Plus, Pencil, Trash2 } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import DataTable, { type Column } from '@/components/common/DataTable';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import StatusBadge from '@/components/common/StatusBadge';
import ProductFormModal from '@/components/products/ProductFormModal';
import { useProducts, useDeleteProduct } from '@/hooks/useProducts';
import { CATEGORY_OPTIONS, PRODUCT_STATUS_OPTIONS } from '@/constants/options';
import type { Product } from '@/types';

export default function SellerProductsPage() {
  const [search, setSearch] = useState('');
  const [categoryFilter, setCategoryFilter] = useState('');
  const [statusFilter, setStatusFilter] = useState('');
  const [showCreateModal, setShowCreateModal] = useState(false);
  const [editingProduct, setEditingProduct] = useState<Product | null>(null);

  const { data, isLoading } = useProducts({
    category: categoryFilter || undefined,
    product_status: statusFilter || undefined,
    search: search || undefined,
  });
  const deleteProduct = useDeleteProduct();
  const products = data?.data ?? [];

  const handleDelete = async (product: Product) => {
    if (deleteProduct.isPending) return;
    if (!confirm(`'${product.name}' 상품을 삭제하시겠습니까?`)) return;
    await deleteProduct.mutateAsync(product.id);
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
    {
      key: 'actions',
      header: '관리',
      className: 'w-32',
      render: (item) => (
        <div className="flex items-center gap-1">
          <button
            onClick={(e) => {
              e.stopPropagation();
              setEditingProduct(item);
            }}
            title="상품 수정"
            aria-label="상품 수정"
            className="inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white p-1.5 text-gray-500 hover:border-primary-300 hover:bg-primary-50 hover:text-primary-700"
          >
            <Pencil className="h-3.5 w-3.5" />
          </button>
          <button
            onClick={(e) => {
              e.stopPropagation();
              handleDelete(item);
            }}
            disabled={deleteProduct.isPending}
            title="상품 삭제"
            aria-label="상품 삭제"
            className="inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white p-1.5 text-gray-400 hover:border-red-300 hover:bg-red-50 hover:text-red-600 disabled:opacity-50"
          >
            <Trash2 className="h-3.5 w-3.5" />
          </button>
        </div>
      ),
    },
  ];

  return (
    <div>
      <PageHeader
        title="상품/재고 관리"
        description="상품 등록 및 재고를 관리하세요"
        action={
          <button
            onClick={() => setShowCreateModal(true)}
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
      <ProductFormModal
        mode="create"
        isOpen={showCreateModal}
        onClose={() => setShowCreateModal(false)}
      />

      {/* 상품 수정 모달 — editingProduct 가 truthy 일 때만 열림 */}
      <ProductFormModal
        mode="edit"
        isOpen={!!editingProduct}
        product={editingProduct}
        onClose={() => setEditingProduct(null)}
      />
    </div>
  );
}
