'use client';

import { useEffect, useMemo, useRef, useState } from 'react';
import { Plus, Trash2, Search, X, Check } from 'lucide-react';
import Modal from '@/components/common/Modal';
import { useCreateOrder } from '@/hooks/useOrders';
import { useMembers } from '@/hooks/useMembers';
import { useProducts } from '@/hooks/useProducts';
import type { OrderItemInput, Product, UserPublicProfile } from '@/types';

interface InitialItem {
  product_id: string;
  quantity?: number;
  unit_price?: number;
}

interface CreateOrderModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 미리 지정된 판매자 ID — 상품 페이지에서 진입 시 활용 */
  initialSellerId?: string;
  /** 미리 지정된 판매자 표시명 — 검색 라벨 대용 (이름 또는 회사명) */
  initialSellerName?: string;
  /** 미리 채워둘 첫 번째 항목 — 상품 카드의 "견적 요청" 진입 시 사용 */
  initialItem?: InitialItem;
}

interface DraftItem {
  product_id: string;
  quantity: string;
  unit_price: string;
  notes: string;
}

const emptyItem: DraftItem = {
  product_id: '',
  quantity: '',
  unit_price: '',
  notes: '',
};

function buildItemsFromInitial(initialItem?: InitialItem): DraftItem[] {
  if (!initialItem) return [{ ...emptyItem }];
  return [
    {
      product_id: initialItem.product_id,
      quantity:
        initialItem.quantity !== undefined ? String(initialItem.quantity) : '',
      unit_price:
        initialItem.unit_price !== undefined
          ? String(initialItem.unit_price)
          : '',
      notes: '',
    },
  ];
}

export default function CreateOrderModal({
  isOpen,
  onClose,
  initialSellerId,
  initialSellerName,
  initialItem,
}: CreateOrderModalProps) {
  // 판매자 선택 상태
  const [sellerId, setSellerId] = useState<string>('');
  const [sellerLabel, setSellerLabel] = useState<string>('');
  // 검색 입력 상태
  const [sellerSearch, setSellerSearch] = useState<string>('');
  const [debouncedSearch, setDebouncedSearch] = useState<string>('');
  const [searchOpen, setSearchOpen] = useState<boolean>(false);
  const searchBoxRef = useRef<HTMLDivElement>(null);

  // 주문 본문
  const [deliveryDate, setDeliveryDate] = useState('');
  const [deliveryAddress, setDeliveryAddress] = useState('');
  const [notes, setNotes] = useState('');
  const [items, setItems] = useState<DraftItem[]>([{ ...emptyItem }]);
  const [error, setError] = useState<string | null>(null);

  // 디바운스 (300ms)
  useEffect(() => {
    const handle = setTimeout(() => setDebouncedSearch(sellerSearch), 300);
    return () => clearTimeout(handle);
  }, [sellerSearch]);

  // 검색 dropdown 외부 클릭 시 닫기
  useEffect(() => {
    if (!searchOpen) return;
    const handleClick = (e: MouseEvent) => {
      if (
        searchBoxRef.current &&
        !searchBoxRef.current.contains(e.target as Node)
      ) {
        setSearchOpen(false);
      }
    };
    document.addEventListener('mousedown', handleClick);
    return () => document.removeEventListener('mousedown', handleClick);
  }, [searchOpen]);

  // 판매자 검색 — 항상 활성화 (빈 문자열도 허용해서 초기 목록 fetch)
  const membersQuery = useMembers({
    role: 'SELLER',
    search: debouncedSearch || undefined,
    page: 1,
    limit: 20,
  });
  const sellerCandidates: UserPublicProfile[] = useMemo(
    () => membersQuery.data?.data ?? [],
    [membersQuery.data]
  );

  // 선택된 판매자의 상품만 조회
  const productsQuery = useProducts(
    sellerId ? { seller_id: sellerId, limit: 200 } : undefined
  );
  const products: Product[] = sellerId ? productsQuery.data?.data ?? [] : [];

  const createOrder = useCreateOrder();

  // 모달 열릴 때 초기화
  useEffect(() => {
    if (isOpen) {
      setSellerId(initialSellerId ?? '');
      setSellerLabel(
        initialSellerId ? initialSellerName ?? '선택된 판매자' : ''
      );
      setSellerSearch('');
      setDebouncedSearch('');
      setSearchOpen(false);
      setDeliveryDate('');
      setDeliveryAddress('');
      setNotes('');
      setItems(buildItemsFromInitial(initialItem));
      setError(null);
    }
    // initialItem은 의도적으로 deps에서 제외 — isOpen 토글로만 초기화
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [isOpen, initialSellerId, initialSellerName]);

  // 판매자 변경(검색에서 다른 판매자 클릭) 시 항목 초기화
  // initialItem 기반 prefill이 있던 경우라도 sellerId가 바뀌면 무조건 초기화
  // (상품은 판매자에 종속되므로 이전 product_id는 무효)
  const prevSellerIdRef = useRef<string>('');
  useEffect(() => {
    if (!isOpen) return;
    if (prevSellerIdRef.current && prevSellerIdRef.current !== sellerId) {
      setItems([{ ...emptyItem }]);
    }
    prevSellerIdRef.current = sellerId;
  }, [sellerId, isOpen]);

  const totalAmount = items.reduce((sum, it) => {
    const q = Number(it.quantity);
    const p = Number(it.unit_price);
    if (!Number.isFinite(q) || !Number.isFinite(p)) return sum;
    return sum + Math.max(0, q) * Math.max(0, p);
  }, 0);

  const handleSelectSeller = (member: UserPublicProfile) => {
    setSellerId(member.id);
    const label = member.company_name
      ? `${member.name} (${member.company_name})`
      : member.name;
    setSellerLabel(label);
    setSearchOpen(false);
    setSellerSearch('');
    setDebouncedSearch('');
  };

  const handleClearSeller = () => {
    setSellerId('');
    setSellerLabel('');
    setSellerSearch('');
    setDebouncedSearch('');
    setSearchOpen(true);
  };

  const handleItemChange = (
    index: number,
    field: keyof DraftItem,
    value: string
  ) => {
    setItems((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
      // 상품 선택 시 단가가 비어있으면 자동 채움
      if (field === 'product_id') {
        const product = products.find((p) => p.id === value);
        if (product && !next[index].unit_price) {
          next[index].unit_price = String(product.price_per_unit);
        }
      }
      return next;
    });
  };

  const handleAddItem = () => {
    setItems((prev) => [...prev, { ...emptyItem }]);
  };

  const handleRemoveItem = (index: number) => {
    setItems((prev) =>
      prev.length === 1 ? prev : prev.filter((_, i) => i !== index)
    );
  };

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    setError(null);

    if (!sellerId) {
      setError('판매자를 선택해 주세요.');
      return;
    }

    const validItems: OrderItemInput[] = [];
    for (const [idx, it] of items.entries()) {
      if (!it.product_id) {
        setError(`${idx + 1}번 항목의 상품을 선택해 주세요.`);
        return;
      }
      const q = Number(it.quantity);
      const p = Number(it.unit_price);
      if (!Number.isFinite(q) || q <= 0) {
        setError(`${idx + 1}번 항목의 수량은 1 이상이어야 합니다.`);
        return;
      }
      if (!Number.isFinite(p) || p < 0) {
        setError(`${idx + 1}번 항목의 단가는 0 이상이어야 합니다.`);
        return;
      }
      validItems.push({
        product_id: it.product_id,
        quantity: q,
        unit_price: p,
        notes: it.notes || undefined,
      });
    }

    try {
      await createOrder.mutateAsync({
        seller_id: sellerId,
        delivery_date: deliveryDate || undefined,
        delivery_address: deliveryAddress || undefined,
        notes: notes || undefined,
        items: validItems,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '견적 요청에 실패했습니다.');
    }
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="견적 요청" size="lg">
      <form onSubmit={handleSubmit} className="space-y-4">
        {/* 판매자 검색/선택 */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            판매자 *
          </label>

          {sellerId ? (
            // 선택됨 — 카드 + 변경 버튼
            <div className="flex items-center justify-between rounded-lg border border-primary-200 bg-primary-50 px-3 py-2">
              <div className="flex items-center gap-2">
                <Check className="h-4 w-4 text-primary-600" />
                <span className="text-sm font-medium text-primary-900">
                  {sellerLabel || '선택된 판매자'}
                </span>
              </div>
              <button
                type="button"
                onClick={handleClearSeller}
                className="rounded-md px-2 py-1 text-xs text-primary-700 hover:bg-primary-100"
              >
                변경
              </button>
            </div>
          ) : (
            // 미선택 — 검색 입력 + dropdown
            <div className="relative" ref={searchBoxRef}>
              <div className="relative">
                <Search className="pointer-events-none absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
                <input
                  type="text"
                  value={sellerSearch}
                  onChange={(e) => {
                    setSellerSearch(e.target.value);
                    setSearchOpen(true);
                  }}
                  onFocus={() => setSearchOpen(true)}
                  placeholder="판매자 이름/회사/이메일 검색"
                  className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-9 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
                />
                {sellerSearch && (
                  <button
                    type="button"
                    onClick={() => {
                      setSellerSearch('');
                      setDebouncedSearch('');
                    }}
                    className="absolute right-2 top-1/2 -translate-y-1/2 rounded p-1 text-gray-400 hover:bg-gray-100 hover:text-gray-600"
                    aria-label="검색어 지우기"
                  >
                    <X className="h-3.5 w-3.5" />
                  </button>
                )}
              </div>

              {searchOpen && (
                <div className="absolute z-10 mt-1 max-h-64 w-full overflow-y-auto rounded-lg border border-gray-200 bg-white shadow-lg">
                  {membersQuery.isLoading ? (
                    <div className="px-3 py-2 text-xs text-gray-400">
                      검색 중...
                    </div>
                  ) : sellerCandidates.length === 0 ? (
                    <div className="px-3 py-2 text-xs text-gray-400">
                      검색 결과가 없습니다.
                    </div>
                  ) : (
                    <ul className="py-1">
                      {sellerCandidates.map((m) => (
                        <li key={m.id}>
                          <button
                            type="button"
                            onClick={() => handleSelectSeller(m)}
                            className="flex w-full flex-col items-start gap-0.5 px-3 py-2 text-left hover:bg-primary-50"
                          >
                            <span className="text-sm font-medium text-gray-900">
                              {m.name}
                              {m.company_name ? (
                                <span className="ml-1 text-xs text-gray-500">
                                  ({m.company_name})
                                </span>
                              ) : null}
                            </span>
                            <span className="text-xs text-gray-400">
                              {m.email}
                            </span>
                          </button>
                        </li>
                      ))}
                    </ul>
                  )}
                </div>
              )}
            </div>
          )}
        </div>

        {/* 납품일 */}
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              납품 희망일
            </label>
            <input
              type="date"
              value={deliveryDate}
              onChange={(e) => setDeliveryDate(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
        </div>

        {/* 배송지 */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            배송지
          </label>
          <textarea
            value={deliveryAddress}
            onChange={(e) => setDeliveryAddress(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>

        {/* 항목 */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-gray-700">주문 항목 *</p>
            <button
              type="button"
              onClick={handleAddItem}
              disabled={!sellerId}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1 text-xs hover:bg-gray-50 disabled:opacity-40"
            >
              <Plus className="h-3 w-3" />
              상품 추가
            </button>
          </div>
          <div className="space-y-3">
            {items.map((it, idx) => (
              <div
                key={idx}
                className="rounded-lg border border-gray-200 bg-gray-50 p-3"
              >
                <div className="grid grid-cols-12 gap-2">
                  <div className="col-span-12 sm:col-span-5">
                    <label className="mb-1 block text-xs text-gray-500">
                      상품
                    </label>
                    <select
                      value={it.product_id}
                      onChange={(e) =>
                        handleItemChange(idx, 'product_id', e.target.value)
                      }
                      disabled={!sellerId}
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm disabled:bg-gray-100"
                    >
                      <option value="">선택</option>
                      {products.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name}
                          {p.spec ? ` (${p.spec})` : ''}
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="col-span-4 sm:col-span-2">
                    <label className="mb-1 block text-xs text-gray-500">
                      수량
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={it.quantity}
                      onChange={(e) =>
                        handleItemChange(idx, 'quantity', e.target.value)
                      }
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div className="col-span-6 sm:col-span-3">
                    <label className="mb-1 block text-xs text-gray-500">
                      단가(원)
                    </label>
                    <input
                      type="number"
                      min={0}
                      value={it.unit_price}
                      onChange={(e) =>
                        handleItemChange(idx, 'unit_price', e.target.value)
                      }
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
                    />
                  </div>
                  <div className="col-span-2 flex items-end justify-end">
                    <button
                      type="button"
                      onClick={() => handleRemoveItem(idx)}
                      disabled={items.length === 1}
                      className="flex h-9 w-9 items-center justify-center rounded-lg text-gray-400 hover:bg-gray-200 hover:text-red-600 disabled:opacity-30"
                      aria-label="항목 삭제"
                    >
                      <Trash2 className="h-4 w-4" />
                    </button>
                  </div>
                  <div className="col-span-12">
                    <input
                      type="text"
                      placeholder="항목 메모 (선택)"
                      value={it.notes}
                      onChange={(e) =>
                        handleItemChange(idx, 'notes', e.target.value)
                      }
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
                    />
                  </div>
                </div>
              </div>
            ))}
          </div>
        </div>

        {/* 메모 */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            메모
          </label>
          <textarea
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            rows={2}
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>

        {/* 합계 */}
        <div className="flex items-center justify-between rounded-lg bg-primary-50 px-4 py-3">
          <span className="text-sm text-gray-600">예상 합계</span>
          <span className="text-lg font-semibold text-primary-700">
            {totalAmount.toLocaleString('ko-KR')}원
          </span>
        </div>

        {error && (
          <p className="rounded-lg bg-red-50 px-3 py-2 text-xs text-red-700">
            {error}
          </p>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
          >
            취소
          </button>
          <button
            type="submit"
            disabled={createOrder.isPending}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {createOrder.isPending ? '요청 중...' : '견적 요청'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
