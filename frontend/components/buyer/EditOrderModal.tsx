'use client';

import { useEffect, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import Modal from '@/components/common/Modal';
import { useUpdateOrder } from '@/hooks/useOrders';
import { useProducts } from '@/hooks/useProducts';
import type { Order, OrderItemInput, Product } from '@/types';

interface EditOrderModalProps {
  isOpen: boolean;
  onClose: () => void;
  order: Order;
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

export default function EditOrderModal({
  isOpen,
  onClose,
  order,
}: EditOrderModalProps) {
  const [deliveryDate, setDeliveryDate] = useState('');
  const [deliveryAddress, setDeliveryAddress] = useState('');
  const [notes, setNotes] = useState('');
  const [items, setItems] = useState<DraftItem[]>([{ ...emptyItem }]);
  const [error, setError] = useState<string | null>(null);

  const productsQuery = useProducts({ seller_id: order.seller_id, limit: 200 });
  const products: Product[] = productsQuery.data?.data ?? [];

  const updateOrder = useUpdateOrder(order.id);

  // 모달 열릴 때 기존 값 prefill
  useEffect(() => {
    if (isOpen) {
      setDeliveryDate(order.delivery_date ?? '');
      setDeliveryAddress(order.delivery_address ?? '');
      setNotes(order.notes ?? '');
      setItems(
        order.items.length > 0
          ? order.items.map((it) => ({
              product_id: it.product_id,
              quantity: String(it.quantity),
              unit_price: String(it.unit_price),
              notes: it.notes ?? '',
            }))
          : [{ ...emptyItem }]
      );
      setError(null);
    }
  }, [isOpen, order]);

  const totalAmount = items.reduce((sum, it) => {
    const q = Number(it.quantity);
    const p = Number(it.unit_price);
    if (!Number.isFinite(q) || !Number.isFinite(p)) return sum;
    return sum + Math.max(0, q) * Math.max(0, p);
  }, 0);

  const handleItemChange = (
    index: number,
    field: keyof DraftItem,
    value: string
  ) => {
    setItems((prev) => {
      const next = [...prev];
      next[index] = { ...next[index], [field]: value };
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
      await updateOrder.mutateAsync({
        delivery_date: deliveryDate || undefined,
        delivery_address: deliveryAddress || undefined,
        notes: notes || undefined,
        items: validItems,
      });
      onClose();
    } catch (err) {
      setError(err instanceof Error ? err.message : '수정에 실패했습니다.');
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={`견적 수정 — ${order.order_number}`}
      size="lg"
    >
      <form onSubmit={handleSubmit} className="space-y-4">
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

        <div>
          <div className="mb-2 flex items-center justify-between">
            <p className="text-sm font-medium text-gray-700">주문 항목 *</p>
            <button
              type="button"
              onClick={handleAddItem}
              className="inline-flex items-center gap-1 rounded-lg border border-gray-300 px-3 py-1 text-xs hover:bg-gray-50"
            >
              <Plus className="h-3 w-3" />
              항목 추가
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
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-sm"
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
            disabled={updateOrder.isPending}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {updateOrder.isPending ? '저장 중...' : '저장'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
