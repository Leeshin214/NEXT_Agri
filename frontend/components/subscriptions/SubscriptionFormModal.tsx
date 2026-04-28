'use client';

import { useEffect, useMemo, useState } from 'react';
import { Plus, Trash2 } from 'lucide-react';
import Modal from '@/components/common/Modal';
import { useProducts } from '@/hooks/useProducts';
import { useCreateSubscription } from '@/hooks/useSubscriptions';
import type {
  Partner,
  Product,
  SubscriptionFrequency,
  SubscriptionItemCreate,
} from '@/types';

interface SubscriptionFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  partner: Partner;
  myRole: 'SELLER' | 'BUYER';
}

interface ItemDraft {
  product_id: string;
  quantity: number;
  unit_price: number;
  unit: string;
}

const emptyItem: ItemDraft = {
  product_id: '',
  quantity: 1,
  unit_price: 0,
  unit: 'kg',
};

const FREQUENCY_OPTIONS: { value: SubscriptionFrequency; label: string }[] = [
  { value: 'WEEKLY', label: '매주' },
  { value: 'BIWEEKLY', label: '격주' },
  { value: 'MONTHLY', label: '매월' },
];

const DAY_OF_WEEK_OPTIONS: { value: number; label: string }[] = [
  { value: 0, label: '일' },
  { value: 1, label: '월' },
  { value: 2, label: '화' },
  { value: 3, label: '수' },
  { value: 4, label: '목' },
  { value: 5, label: '금' },
  { value: 6, label: '토' },
];

function defaultStartDate(): string {
  const d = new Date();
  d.setDate(d.getDate() + 7);
  // KST 기준 timezone-safe 날짜 문자열
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

function todayStr(): string {
  const d = new Date();
  const y = d.getFullYear();
  const m = String(d.getMonth() + 1).padStart(2, '0');
  const day = String(d.getDate()).padStart(2, '0');
  return `${y}-${m}-${day}`;
}

export default function SubscriptionFormModal({
  isOpen,
  onClose,
  partner,
  myRole,
}: SubscriptionFormModalProps) {
  const [frequency, setFrequency] = useState<SubscriptionFrequency>('WEEKLY');
  const [dayOfWeek, setDayOfWeek] = useState<number>(1);
  const [dayOfMonth, setDayOfMonth] = useState<number>(1);
  const [startDate, setStartDate] = useState<string>(defaultStartDate());
  const [endDate, setEndDate] = useState<string>('');
  const [deliveryAddress, setDeliveryAddress] = useState<string>('');
  const [notes, setNotes] = useState<string>('');
  const [items, setItems] = useState<ItemDraft[]>([{ ...emptyItem }]);
  const [error, setError] = useState<string | null>(null);

  // 모달 열릴 때마다 폼 초기화
  useEffect(() => {
    if (isOpen) {
      setFrequency('WEEKLY');
      setDayOfWeek(1);
      setDayOfMonth(1);
      setStartDate(defaultStartDate());
      setEndDate('');
      setDeliveryAddress('');
      setNotes('');
      setItems([{ ...emptyItem }]);
      setError(null);
    }
  }, [isOpen]);

  // 상품 목록 — myRole 에 따라 다른 사용자의 상품을 조회
  // - SELLER가 만들 때: 본인(partner.user_id) 상품 → useProducts({ seller_id: partner.user_id })
  // - BUYER가 만들 때: 거래처 판매자(partner.partner_user_id) 상품
  const sellerIdForProducts =
    myRole === 'SELLER' ? partner.user_id : partner.partner_user_id;
  const productsQuery = useProducts({
    seller_id: sellerIdForProducts,
    limit: 200,
  });
  const products: Product[] = productsQuery.data?.data ?? [];

  const createSubscription = useCreateSubscription();

  const totalAmount = useMemo(
    () =>
      items.reduce(
        (sum, it) => sum + (it.quantity || 0) * (it.unit_price || 0),
        0
      ),
    [items]
  );

  const updateItem = (idx: number, patch: Partial<ItemDraft>) => {
    setItems((prev) =>
      prev.map((it, i) => (i === idx ? { ...it, ...patch } : it))
    );
  };

  const handleProductChange = (idx: number, productId: string) => {
    const product = products.find((p) => p.id === productId);
    if (!product) {
      updateItem(idx, { product_id: productId });
      return;
    }
    updateItem(idx, {
      product_id: productId,
      unit: product.unit,
      // 단가가 0이면 상품 가격으로 prefill, 사용자가 이미 입력한 단가는 유지
      unit_price:
        items[idx].unit_price > 0 ? items[idx].unit_price : product.price_per_unit,
    });
  };

  const addItem = () => setItems((prev) => [...prev, { ...emptyItem }]);

  const removeItem = (idx: number) => {
    setItems((prev) =>
      prev.length === 1 ? prev : prev.filter((_, i) => i !== idx)
    );
  };

  const handleSubmit = async () => {
    setError(null);

    // 검증
    if (items.some((it) => !it.product_id)) {
      setError('모든 항목에서 상품을 선택하세요.');
      return;
    }
    if (items.some((it) => it.quantity <= 0)) {
      setError('수량은 1 이상이어야 합니다.');
      return;
    }
    if (items.some((it) => it.unit_price < 0)) {
      setError('단가는 0 이상이어야 합니다.');
      return;
    }
    if (!startDate) {
      setError('시작일을 입력하세요.');
      return;
    }
    if (startDate < todayStr()) {
      setError('시작일은 오늘 이후로 설정하세요.');
      return;
    }
    if (frequency === 'MONTHLY' && (dayOfMonth < 1 || dayOfMonth > 31)) {
      setError('매월 결제일은 1~31 사이여야 합니다.');
      return;
    }
    if (
      (frequency === 'WEEKLY' || frequency === 'BIWEEKLY') &&
      (dayOfWeek < 0 || dayOfWeek > 6)
    ) {
      setError('요일을 선택하세요.');
      return;
    }
    if (endDate && endDate < startDate) {
      setError('종료일은 시작일 이후여야 합니다.');
      return;
    }

    // seller_id / buyer_id 매핑
    const seller_id =
      myRole === 'SELLER' ? partner.user_id : partner.partner_user_id;
    const buyer_id =
      myRole === 'BUYER' ? partner.user_id : partner.partner_user_id;

    const itemsPayload: SubscriptionItemCreate[] = items.map((it) => ({
      product_id: it.product_id,
      quantity: it.quantity,
      unit_price: it.unit_price,
      unit: it.unit,
    }));

    try {
      await createSubscription.mutateAsync({
        seller_id,
        buyer_id,
        partner_id: partner.id,
        frequency,
        day_of_week: frequency === 'MONTHLY' ? null : dayOfWeek,
        day_of_month: frequency === 'MONTHLY' ? dayOfMonth : null,
        start_date: startDate,
        end_date: endDate || null,
        delivery_address: deliveryAddress || null,
        notes: notes || null,
        items: itemsPayload,
      });
      onClose();
    } catch (e) {
      const msg = e instanceof Error ? e.message : '정기배송 생성에 실패했습니다.';
      setError(msg);
    }
  };

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title="새 정기배송 등록"
      size="xl"
      footer={
        <>
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
          >
            취소
          </button>
          <button
            type="button"
            onClick={handleSubmit}
            disabled={createSubscription.isPending}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {createSubscription.isPending ? '등록 중...' : '등록'}
          </button>
        </>
      }
    >
      <div className="space-y-5">
        {/* 주기 */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            주기
          </label>
          <div className="flex gap-2">
            {FREQUENCY_OPTIONS.map((opt) => (
              <button
                key={opt.value}
                type="button"
                onClick={() => setFrequency(opt.value)}
                className={`rounded-lg border px-4 py-2 text-sm font-medium transition-colors ${
                  frequency === opt.value
                    ? 'border-primary-600 bg-primary-50 text-primary-700'
                    : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
                }`}
              >
                {opt.label}
              </button>
            ))}
          </div>
        </div>

        {/* 요일 또는 결제일 */}
        {frequency === 'MONTHLY' ? (
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              매월 결제일 (1~31)
            </label>
            <input
              type="number"
              min={1}
              max={31}
              value={dayOfMonth}
              onChange={(e) => setDayOfMonth(Number(e.target.value) || 1)}
              className="w-32 rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
            <p className="mt-1 text-xs text-gray-500">
              해당 월에 그 일자가 없으면 월말로 자동 조정됩니다 (예: 31일 → 2월 28/29일)
            </p>
          </div>
        ) : (
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              요일
            </label>
            <div className="flex gap-1">
              {DAY_OF_WEEK_OPTIONS.map((opt) => (
                <button
                  key={opt.value}
                  type="button"
                  onClick={() => setDayOfWeek(opt.value)}
                  className={`h-10 w-10 rounded-lg border text-sm font-medium transition-colors ${
                    dayOfWeek === opt.value
                      ? 'border-primary-600 bg-primary-50 text-primary-700'
                      : 'border-gray-300 bg-white text-gray-700 hover:bg-gray-50'
                  }`}
                >
                  {opt.label}
                </button>
              ))}
            </div>
          </div>
        )}

        {/* 시작일 / 종료일 */}
        <div className="grid grid-cols-2 gap-3">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              시작일
            </label>
            <input
              type="date"
              value={startDate}
              min={todayStr()}
              onChange={(e) => setStartDate(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              종료일 (선택)
            </label>
            <input
              type="date"
              value={endDate}
              min={startDate}
              onChange={(e) => setEndDate(e.target.value)}
              className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
        </div>

        {/* 납품 주소 */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            납품 주소 (선택)
          </label>
          <input
            type="text"
            value={deliveryAddress}
            onChange={(e) => setDeliveryAddress(e.target.value)}
            placeholder="배송받을 주소를 입력하세요"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>

        {/* 메모 */}
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            메모 (선택)
          </label>
          <textarea
            rows={2}
            value={notes}
            onChange={(e) => setNotes(e.target.value)}
            placeholder="요청사항 등"
            className="w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
          />
        </div>

        {/* 상품 라인 */}
        <div>
          <div className="mb-2 flex items-center justify-between">
            <label className="block text-sm font-medium text-gray-700">
              상품 ({items.length})
            </label>
            <button
              type="button"
              onClick={addItem}
              className="inline-flex items-center gap-1 rounded-lg border border-primary-600 bg-white px-3 py-1.5 text-xs font-medium text-primary-700 hover:bg-primary-50"
            >
              <Plus className="h-3.5 w-3.5" />
              상품 추가
            </button>
          </div>

          {productsQuery.isLoading ? (
            <p className="py-3 text-center text-xs text-gray-400">
              상품 목록 로딩 중...
            </p>
          ) : products.length === 0 ? (
            <p className="rounded-lg bg-amber-50 p-3 text-xs text-amber-700">
              등록된 상품이 없습니다. 정기배송을 만들려면 먼저 상품이 등록되어
              있어야 합니다.
            </p>
          ) : (
            <ul className="space-y-2">
              {items.map((item, idx) => (
                <li
                  key={idx}
                  className="grid grid-cols-12 items-end gap-2 rounded-lg border border-gray-200 bg-gray-50 p-3"
                >
                  <div className="col-span-5">
                    <label className="mb-1 block text-xs font-medium text-gray-600">
                      상품
                    </label>
                    <select
                      value={item.product_id}
                      onChange={(e) =>
                        handleProductChange(idx, e.target.value)
                      }
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-xs focus:border-primary-500 focus:outline-none"
                    >
                      <option value="">선택</option>
                      {products.map((p) => (
                        <option key={p.id} value={p.id}>
                          {p.name} ({p.price_per_unit.toLocaleString()}원/{p.unit})
                        </option>
                      ))}
                    </select>
                  </div>
                  <div className="col-span-2">
                    <label className="mb-1 block text-xs font-medium text-gray-600">
                      수량
                    </label>
                    <input
                      type="number"
                      min={1}
                      value={item.quantity}
                      onChange={(e) =>
                        updateItem(idx, {
                          quantity: Number(e.target.value) || 0,
                        })
                      }
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-xs focus:border-primary-500 focus:outline-none"
                    />
                  </div>
                  <div className="col-span-1">
                    <label className="mb-1 block text-xs font-medium text-gray-600">
                      단위
                    </label>
                    <input
                      type="text"
                      value={item.unit}
                      onChange={(e) =>
                        updateItem(idx, { unit: e.target.value })
                      }
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-xs focus:border-primary-500 focus:outline-none"
                    />
                  </div>
                  <div className="col-span-3">
                    <label className="mb-1 block text-xs font-medium text-gray-600">
                      단가 (원)
                    </label>
                    <input
                      type="number"
                      min={0}
                      value={item.unit_price}
                      onChange={(e) =>
                        updateItem(idx, {
                          unit_price: Number(e.target.value) || 0,
                        })
                      }
                      className="w-full rounded-lg border border-gray-300 px-2 py-1.5 text-xs focus:border-primary-500 focus:outline-none"
                    />
                  </div>
                  <div className="col-span-1 flex items-end">
                    <button
                      type="button"
                      onClick={() => removeItem(idx)}
                      disabled={items.length === 1}
                      className="flex h-7 w-7 items-center justify-center rounded-lg text-gray-400 hover:bg-red-50 hover:text-red-600 disabled:opacity-30"
                      title="삭제"
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </div>
                </li>
              ))}
            </ul>
          )}

          <p className="mt-3 text-right text-sm text-gray-700">
            1회차 예상 금액:{' '}
            <span className="text-base font-semibold text-gray-900">
              {totalAmount.toLocaleString('ko-KR')}원
            </span>
          </p>
        </div>

        {error && (
          <div className="rounded-lg border border-red-200 bg-red-50 p-3 text-sm text-red-700">
            {error}
          </div>
        )}
      </div>
    </Modal>
  );
}
