import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import { ShoppingCart, Truck } from 'lucide-react';
import SummaryCard from '@/components/common/SummaryCard';

describe('SummaryCard', () => {
  it('제목과 값을 렌더링한다', () => {
    render(
      <SummaryCard title="진행 중 주문" value={5} icon={ShoppingCart} />
    );
    expect(screen.getByText('진행 중 주문')).toBeInTheDocument();
    expect(screen.getByText('5')).toBeInTheDocument();
  });

  it('부제목을 렌더링한다', () => {
    render(
      <SummaryCard
        title="배송 중"
        value={3}
        subtitle="입고 예정"
        icon={Truck}
      />
    );
    expect(screen.getByText('입고 예정')).toBeInTheDocument();
  });

  it('문자열 값을 렌더링한다', () => {
    render(
      <SummaryCard title="매출" value="1,250,000원" icon={ShoppingCart} />
    );
    expect(screen.getByText('1,250,000원')).toBeInTheDocument();
  });

  it('onClick 핸들러가 호출된다', () => {
    const onClick = vi.fn();
    render(
      <SummaryCard
        title="클릭 테스트"
        value={10}
        icon={ShoppingCart}
        onClick={onClick}
      />
    );
    const card = screen.getByText('클릭 테스트').closest('div[class*="rounded"]');
    if (card) fireEvent.click(card);
    expect(onClick).toHaveBeenCalledTimes(1);
  });

  it('onClick이 있으면 cursor-pointer 클래스가 적용된다', () => {
    const { container } = render(
      <SummaryCard
        title="커서 테스트"
        value={0}
        icon={ShoppingCart}
        onClick={() => {}}
      />
    );
    expect(container.firstChild).toHaveClass('cursor-pointer');
  });

  it('onClick이 없으면 cursor-pointer가 적용되지 않는다', () => {
    const { container } = render(
      <SummaryCard title="커서 없음" value={0} icon={ShoppingCart} />
    );
    expect(container.firstChild).not.toHaveClass('cursor-pointer');
  });

  it('양수 트렌드를 초록색으로 표시한다', () => {
    render(
      <SummaryCard
        title="트렌드 테스트"
        value={100}
        icon={ShoppingCart}
        trend={{ value: 12, label: '지난주 대비' }}
      />
    );
    const trendText = screen.getByText(/\+12%/);
    expect(trendText).toBeInTheDocument();
    expect(trendText).toHaveClass('text-green-600');
  });

  it('음수 트렌드를 빨간색으로 표시한다', () => {
    render(
      <SummaryCard
        title="하락 테스트"
        value={50}
        icon={ShoppingCart}
        trend={{ value: -5, label: '전월 대비' }}
      />
    );
    const trendText = screen.getByText(/-5%/);
    expect(trendText).toBeInTheDocument();
    expect(trendText).toHaveClass('text-red-600');
  });
});
