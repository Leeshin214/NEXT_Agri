'use client';

/**
 * 상품 등록/수정 공용 폼 모달.
 *
 * 옵션 A 채택: 단일 컴포넌트가 mode 로 등록/수정을 모두 처리.
 *  - mode='create' : useCreateProduct 호출, status 필드 숨김 (백엔드 ProductCreate 에 없음)
 *  - mode='edit'   : useUpdateProduct 호출, status 필드 노출 + product 로 prefill
 *
 * 폼 필드 (백엔드 schemas/product.py 와 1:1):
 *   name, category, origin, spec, unit, price_per_unit,
 *   stock_quantity, min_order_qty, [status (edit only)], description
 *
 * 저장 성공 시 useCreate/UpdateProduct 가 ['products'] 캐시 invalidate → 목록 자동 갱신.
 */

import type { FormEvent } from 'react';
import Modal from '@/components/common/Modal';
import { useCreateProduct, useUpdateProduct } from '@/hooks/useProducts';
import {
  CATEGORY_OPTIONS,
  PRODUCT_STATUS_OPTIONS,
  UNIT_OPTIONS,
} from '@/constants/options';
import type {
  Product,
  ProductCategory,
  ProductCreate,
  ProductStatus,
  ProductUnit,
  ProductUpdate,
} from '@/types';

interface ProductFormModalProps {
  isOpen: boolean;
  onClose: () => void;
  /** 'create' = 신규 등록, 'edit' = 기존 상품 수정 */
  mode: 'create' | 'edit';
  /** mode='edit' 일 때만 필수 — 폼 prefill 에 사용 */
  product?: Product | null;
}

export default function ProductFormModal({
  isOpen,
  onClose,
  mode,
  product,
}: ProductFormModalProps) {
  const createProduct = useCreateProduct();
  const updateProduct = useUpdateProduct();

  const isEdit = mode === 'edit';
  const isPending = isEdit ? updateProduct.isPending : createProduct.isPending;

  const handleSubmit = async (e: FormEvent<HTMLFormElement>) => {
    e.preventDefault();
    const form = new FormData(e.currentTarget);

    const name = (form.get('name') as string).trim();
    const category = form.get('category') as ProductCategory;
    const origin = (form.get('origin') as string)?.trim() || undefined;
    const spec = (form.get('spec') as string)?.trim() || undefined;
    const unit = form.get('unit') as ProductUnit;
    const price_per_unit = Number(form.get('price_per_unit'));
    const stock_quantity = Number(form.get('stock_quantity')) || 0;
    const min_order_qty = Number(form.get('min_order_qty')) || 1;
    const description = (form.get('description') as string)?.trim() || undefined;

    if (isEdit) {
      if (!product) return;
      const status = form.get('status') as ProductStatus;
      const payload: ProductUpdate = {
        name,
        category,
        origin,
        spec,
        unit,
        price_per_unit,
        stock_quantity,
        min_order_qty,
        status,
        description,
      };
      await updateProduct.mutateAsync({ id: product.id, data: payload });
    } else {
      const payload: ProductCreate = {
        name,
        category,
        origin,
        spec,
        unit,
        price_per_unit,
        stock_quantity,
        min_order_qty,
        description,
      };
      await createProduct.mutateAsync(payload);
    }
    onClose();
  };

  const inputClass =
    'w-full rounded-lg border border-gray-300 px-3 py-2 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500';

  return (
    <Modal
      isOpen={isOpen}
      onClose={onClose}
      title={isEdit ? '상품 수정' : '상품 등록'}
      size="lg"
    >
      {/* mode 또는 product.id 변경 시 input defaultValue 가 다시 평가되도록 key 부여 */}
      <form
        key={isEdit ? `edit-${product?.id ?? ''}` : 'create'}
        onSubmit={handleSubmit}
        className="space-y-4"
      >
        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              품목명 *
            </label>
            <input
              name="name"
              required
              defaultValue={product?.name ?? ''}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              카테고리 *
            </label>
            <select
              name="category"
              required
              defaultValue={product?.category ?? CATEGORY_OPTIONS[0].value}
              className={inputClass}
            >
              {CATEGORY_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              원산지
            </label>
            <input
              name="origin"
              defaultValue={product?.origin ?? ''}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              규격
            </label>
            <input
              name="spec"
              placeholder="특, 상, 중"
              defaultValue={product?.spec ?? ''}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              단위 *
            </label>
            <select
              name="unit"
              required
              defaultValue={product?.unit ?? UNIT_OPTIONS[0].value}
              className={inputClass}
            >
              {UNIT_OPTIONS.map((o) => (
                <option key={o.value} value={o.value}>
                  {o.label}
                </option>
              ))}
            </select>
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              단가 (원) *
            </label>
            <input
              name="price_per_unit"
              type="number"
              required
              min={0}
              defaultValue={product?.price_per_unit ?? ''}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              재고 수량
            </label>
            <input
              name="stock_quantity"
              type="number"
              min={0}
              defaultValue={product?.stock_quantity ?? 0}
              className={inputClass}
            />
          </div>
          <div>
            <label className="mb-1 block text-sm font-medium text-gray-700">
              최소 주문 수량
            </label>
            <input
              name="min_order_qty"
              type="number"
              min={1}
              defaultValue={product?.min_order_qty ?? 1}
              className={inputClass}
            />
          </div>
          {/* status — edit 모드에서만 노출. ProductCreate 에는 status 가 없음 */}
          {isEdit && (
            <div>
              <label className="mb-1 block text-sm font-medium text-gray-700">
                상태
              </label>
              <select
                name="status"
                defaultValue={product?.status ?? 'NORMAL'}
                className={inputClass}
              >
                {PRODUCT_STATUS_OPTIONS.map((o) => (
                  <option key={o.value} value={o.value}>
                    {o.label}
                  </option>
                ))}
              </select>
            </div>
          )}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-gray-700">
            설명
          </label>
          <textarea
            name="description"
            rows={3}
            defaultValue={product?.description ?? ''}
            className={inputClass}
          />
        </div>
        <div className="flex justify-end gap-2">
          <button
            type="button"
            onClick={onClose}
            className="rounded-lg border border-gray-300 px-4 py-2 text-sm hover:bg-gray-50"
          >
            취소
          </button>
          <button
            type="submit"
            disabled={isPending}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm text-white hover:bg-primary-700 disabled:opacity-50"
          >
            {isPending
              ? isEdit
                ? '저장 중...'
                : '등록 중...'
              : isEdit
                ? '저장'
                : '등록'}
          </button>
        </div>
      </form>
    </Modal>
  );
}
