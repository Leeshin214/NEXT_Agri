import { describe, it, expect } from 'vitest';
import { sellerQuickPrompts, buyerQuickPrompts } from '@/constants/aiPrompts';

describe('AI Quick Prompts', () => {
  it('판매자 프롬프트가 4개 있다', () => {
    expect(sellerQuickPrompts).toHaveLength(4);
  });

  it('구매자 프롬프트가 4개 있다', () => {
    expect(buyerQuickPrompts).toHaveLength(4);
  });

  it('각 프롬프트에 필수 필드가 있다', () => {
    for (const qp of [...sellerQuickPrompts, ...buyerQuickPrompts]) {
      expect(qp).toHaveProperty('label');
      expect(qp).toHaveProperty('prompt');
      expect(qp).toHaveProperty('type');
      expect(qp.label.length).toBeGreaterThan(0);
      expect(qp.prompt.length).toBeGreaterThan(0);
      expect(qp.type.length).toBeGreaterThan(0);
    }
  });

  it('판매자 프롬프트에 출하 관련 항목이 있다', () => {
    const hasShipment = sellerQuickPrompts.some(
      (p) => p.type === 'SHIPMENT_SUMMARY'
    );
    expect(hasShipment).toBe(true);
  });

  it('구매자 프롬프트에 납품 관련 항목이 있다', () => {
    const hasDelivery = buyerQuickPrompts.some(
      (p) => p.type === 'DELIVERY_SUMMARY'
    );
    expect(hasDelivery).toBe(true);
  });
});
