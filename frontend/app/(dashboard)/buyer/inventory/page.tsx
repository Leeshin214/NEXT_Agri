'use client';

import { useEffect, useMemo, useState } from 'react';
import { Boxes, Pencil, Trash2 } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import DataTable, { type Column } from '@/components/common/DataTable';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import EmptyState from '@/components/common/EmptyState';
import Modal from '@/components/common/Modal';
import {
  useBuyerInventoryList,
  useDeleteBuyerInventory,
  useUpdateBuyerInventory,
} from '@/hooks/useBuyerInventory';
import { CATEGORY_OPTIONS } from '@/constants/options';
import { cn } from '@/lib/utils';
import type {
  BuyerInventory,
  BuyerInventorySortBy,
  BuyerInventoryUpdatePayload,
} from '@/types';

const SORT_OPTIONS: { value: BuyerInventorySortBy; label: string }[] = [
  { value: 'recent', label: '최근 입고순' },
  { value: 'quantity', label: '보유 수량순' },
  { value: 'name', label: '상품명순' },
];

const PAGE_LIMIT = 20;

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

function categoryLabel(category: string | null | undefined): string {
  if (!category) return '';
  return (
    CATEGORY_OPTIONS.find((c) => c.value === category)?.label ?? category
  );
}

export default function BuyerInventoryPage() {
  const [search, setSearch] = useState('');
  const [searchInput, setSearchInput] = useState('');
  const [sortBy, setSortBy] = useState<BuyerInventorySortBy>('recent');
  const [page, setPage] = useState(1);

  const [editTarget, setEditTarget] = useState<BuyerInventory | null>(null);
  const [editQty, setEditQty] = useState<string>('');
  const [editNotes, setEditNotes] = useState<string>('');

  const [deleteTarget, setDeleteTarget] = useState<BuyerInventory | null>(null);

  // 검색 디바운스 — 입력 멈춘 뒤 300ms 후 search 적용 (페이지 1로 리셋)
  useEffect(() => {
    const t = setTimeout(() => {
      setSearch(searchInput.trim());
      setPage(1);
    }, 300);
    return () => clearTimeout(t);
  }, [searchInput]);

  // 정렬 변경 시 1페이지로
  useEffect(() => {
    setPage(1);
  }, [sortBy]);

  const { data, isLoading, isFetching } = useBuyerInventoryList({
    search: search || undefined,
    sort_by: sortBy,
    page,
    limit: PAGE_LIMIT,
  });

  const items: BuyerInventory[] = data?.data ?? [];
  const meta = data?.meta;
  const totalPages = meta?.total_pages ?? 0;
  const total = meta?.total ?? 0;

  const updateInventory = useUpdateBuyerInventory();
  const deleteInventory = useDeleteBuyerInventory();

  const openEdit = (row: BuyerInventory) => {
    setEditTarget(row);
    setEditQty(String(row.quantity));
    setEditNotes(row.notes ?? '');
  };

  const closeEdit = () => {
    setEditTarget(null);
    setEditQty('');
    setEditNotes('');
  };

  const handleSubmitEdit = async (e: React.FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    if (!editTarget) return;
    const qty = Number(editQty);
    if (Number.isNaN(qty) || qty < 0) {
      alert('수량은 0 이상의 숫자여야 합니다.');
      return;
    }
    const payload: BuyerInventoryUpdatePayload = {};
    if (qty !== editTarget.quantity) payload.quantity = qty;
    const trimmedNotes = editNotes.trim();
    const currentNotes = editTarget.notes ?? '';
    if (trimmedNotes !== currentNotes) payload.notes = trimmedNotes;

    if (Object.keys(payload).length === 0) {
      closeEdit();
      return;
    }

    try {
      await updateInventory.mutateAsync({ id: editTarget.id, data: payload });
      closeEdit();
    } catch (err) {
      console.error('[buyer/inventory] update failed:', err);
      alert('재고 수정에 실패했습니다. 잠시 후 다시 시도해주세요.');
    }
  };

  const handleConfirmDelete = async () => {
    if (!deleteTarget) return;
    try {
      await deleteInventory.mutateAsync(deleteTarget.id);
      setDeleteTarget(null);
    } catch (err) {
      console.error('[buyer/inventory] delete failed:', err);
      alert('재고 항목 숨김 처리에 실패했습니다. 잠시 후 다시 시도해주세요.');
    }
  };

  const isEmpty = !isLoading && items.length === 0 && !search;
  const isFilteredEmpty = !isLoading && items.length === 0 && !!search;

  const totalsSummary = useMemo(() => {
    if (!meta) return '';
    return ` · 전체 ${total.toLocaleString('ko-KR')}건`;
  }, [meta, total]);

  const columns: Column<BuyerInventory>[] = [
    {
      key: 'product',
      header: '상품',
      render: (item) => (
        <div className="flex items-center gap-3">
          <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center overflow-hidden rounded-lg bg-gray-100">
            {item.product_image_url ? (
              // eslint-disable-next-line @next/next/no-img-element
              <img
                src={item.product_image_url}
                alt={item.product_name ?? ''}
                className="h-full w-full object-cover"
              />
            ) : (
              <Boxes className="h-5 w-5 text-gray-300" />
            )}
          </div>
          <div className="min-w-0">
            <p className="truncate font-medium text-gray-900">
              {item.product_name ?? '상품 정보 없음'}
            </p>
            <p className="truncate text-xs text-gray-500">
              {categoryLabel(item.product_category)}
            </p>
          </div>
        </div>
      ),
    },
    {
      key: 'quantity',
      header: '보유 수량',
      render: (item) => (
        <span
          className={cn(
            'text-sm font-medium',
            item.quantity === 0 ? 'text-red-500' : 'text-gray-900'
          )}
        >
          {item.quantity.toLocaleString('ko-KR')}
          {item.unit ? ` ${item.unit}` : ''}
        </span>
      ),
    },
    {
      key: 'last_added_at',
      header: '최근 입고일',
      render: (item) => (
        <span className="text-sm text-gray-600">
          {formatDate(item.last_added_at)}
        </span>
      ),
    },
    {
      key: 'seller',
      header: '판매처',
      render: (item) => (
        <div className="flex flex-col">
          <span className="text-sm text-gray-900">
            {item.seller_company ?? item.seller_name ?? '-'}
          </span>
          {item.seller_company && item.seller_name && (
            <span className="text-xs text-gray-500">{item.seller_name}</span>
          )}
        </div>
      ),
    },
    {
      key: 'notes',
      header: '메모',
      render: (item) => (
        <span className="block max-w-[220px] truncate text-sm text-gray-600">
          {item.notes ?? '-'}
        </span>
      ),
    },
    {
      key: 'actions',
      header: '',
      className: 'text-right',
      render: (item) => (
        <div
          className="flex items-center justify-end gap-1"
          onClick={(e) => e.stopPropagation()}
        >
          <button
            type="button"
            onClick={() => openEdit(item)}
            title="수량/메모 수정"
            aria-label="수량/메모 수정"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-600 hover:bg-gray-50"
          >
            <Pencil className="h-4 w-4" />
          </button>
          <button
            type="button"
            onClick={() => setDeleteTarget(item)}
            title="재고 항목 숨기기"
            aria-label="재고 항목 숨기기"
            className="inline-flex h-8 w-8 items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-400 hover:border-red-300 hover:bg-red-50 hover:text-red-600"
          >
            <Trash2 className="h-4 w-4" />
          </button>
        </div>
      ),
    },
  ];

  return (
    <div className="space-y-4">
      <PageHeader
        title="내 재고"
        description={`주문이 배송완료되면 자동으로 누적됩니다${totalsSummary}`}
      />

      <div className="flex flex-wrap items-center gap-3">
        <div className="min-w-[240px] flex-1">
          <SearchFilterBar
            searchValue={searchInput}
            onSearchChange={setSearchInput}
            searchPlaceholder="상품명 검색..."
          />
        </div>
        <select
          value={sortBy}
          onChange={(e) => setSortBy(e.target.value as BuyerInventorySortBy)}
          className="mb-4 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
        >
          {SORT_OPTIONS.map((o) => (
            <option key={o.value} value={o.value}>
              {o.label}
            </option>
          ))}
        </select>
      </div>

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      ) : isEmpty ? (
        <EmptyState
          icon={Boxes}
          title="아직 입고된 재고가 없어요"
          description="주문이 배송완료되면 자동으로 추가됩니다."
        />
      ) : isFilteredEmpty ? (
        <EmptyState
          icon={Boxes}
          title="검색 결과가 없습니다"
          description="다른 키워드로 검색해보세요."
        />
      ) : (
        <>
          <DataTable
            columns={columns}
            data={items}
            emptyMessage="아직 입고된 재고가 없어요. 주문이 배송완료되면 자동으로 추가됩니다."
          />

          {/* 페이지네이션 */}
          {totalPages > 1 && (
            <div className="flex items-center justify-between gap-3 pt-2">
              <p className="text-xs text-gray-500">
                {page} / {totalPages} 페이지
                {isFetching ? ' · 불러오는 중...' : ''}
              </p>
              <div className="flex items-center gap-1">
                <button
                  type="button"
                  onClick={() => setPage((p) => Math.max(1, p - 1))}
                  disabled={page <= 1 || isFetching}
                  className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  이전
                </button>
                <button
                  type="button"
                  onClick={() =>
                    setPage((p) => Math.min(totalPages, p + 1))
                  }
                  disabled={page >= totalPages || isFetching}
                  className="rounded-lg border border-gray-200 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50 disabled:cursor-not-allowed disabled:opacity-40"
                >
                  다음
                </button>
              </div>
            </div>
          )}
        </>
      )}

      {/* 수정 모달 — 수량/메모 */}
      <Modal
        isOpen={!!editTarget}
        onClose={closeEdit}
        title="재고 수정"
        size="md"
      >
        {editTarget && (
          <form onSubmit={handleSubmitEdit} className="space-y-4">
            <div className="rounded-lg bg-gray-50 p-3 text-sm">
              <p className="font-medium text-gray-900">
                {editTarget.product_name ?? '상품 정보 없음'}
              </p>
              <p className="text-xs text-gray-500">
                {categoryLabel(editTarget.product_category)}
                {editTarget.seller_company
                  ? ` · ${editTarget.seller_company}`
                  : ''}
              </p>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                보유 수량 {editTarget.unit ? `(${editTarget.unit})` : ''}
              </label>
              <input
                type="number"
                min={0}
                value={editQty}
                onChange={(e) => setEditQty(e.target.value)}
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
              <p className="mt-1 text-xs text-gray-500">
                소진 처리하려면 0 으로 입력하세요.
              </p>
            </div>

            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                메모
              </label>
              <textarea
                rows={3}
                value={editNotes}
                onChange={(e) => setEditNotes(e.target.value)}
                placeholder="예: 냉장고 2번 칸에 보관 중"
                className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
              />
            </div>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={closeEdit}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
              >
                취소
              </button>
              <button
                type="submit"
                disabled={updateInventory.isPending}
                className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
              >
                {updateInventory.isPending ? '저장 중...' : '저장'}
              </button>
            </div>
          </form>
        )}
      </Modal>

      {/* 삭제 확인 모달 — soft delete */}
      <Modal
        isOpen={!!deleteTarget}
        onClose={() => setDeleteTarget(null)}
        title="재고 항목 숨기기"
        size="sm"
      >
        {deleteTarget && (
          <div className="space-y-4">
            <div className="rounded-lg bg-gray-50 p-3 text-sm">
              <p className="font-medium text-gray-900">
                {deleteTarget.product_name ?? '상품 정보 없음'}
              </p>
              <p className="text-xs text-gray-500">
                보유 수량 {deleteTarget.quantity.toLocaleString('ko-KR')}
                {deleteTarget.unit ? ` ${deleteTarget.unit}` : ''}
              </p>
            </div>

            <p className="text-sm text-gray-700">
              이 재고 항목을 목록에서 숨길까요?
            </p>
            <p className="text-xs text-gray-500">
              soft delete 처리되어 데이터는 보존됩니다. 같은 상품을 다시
              배송완료하면 새로운 재고 항목으로 자동 추가됩니다.
            </p>

            <div className="flex justify-end gap-2">
              <button
                type="button"
                onClick={() => setDeleteTarget(null)}
                className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
              >
                취소
              </button>
              <button
                type="button"
                onClick={handleConfirmDelete}
                disabled={deleteInventory.isPending}
                className="rounded-lg bg-red-600 px-4 py-2 text-sm font-medium text-white hover:bg-red-700 disabled:opacity-50"
              >
                {deleteInventory.isPending ? '처리 중...' : '숨기기'}
              </button>
            </div>
          </div>
        )}
      </Modal>
    </div>
  );
}
