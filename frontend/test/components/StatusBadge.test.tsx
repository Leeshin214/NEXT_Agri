import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import StatusBadge from '@/components/common/StatusBadge';

describe('StatusBadge', () => {
  it('NORMAL 상태를 올바르게 표시한다', () => {
    render(<StatusBadge status="NORMAL" />);
    expect(screen.getByText('정상')).toBeInTheDocument();
  });

  it('LOW_STOCK 상태에 올바른 스타일이 적용된다', () => {
    const { container } = render(<StatusBadge status="LOW_STOCK" />);
    expect(screen.getByText('재고부족')).toBeInTheDocument();
    expect(container.firstChild).toHaveClass('bg-yellow-100');
  });

  it('QUOTE_REQUESTED 상태를 견적대기로 표시한다', () => {
    render(<StatusBadge status="QUOTE_REQUESTED" />);
    expect(screen.getByText('견적대기')).toBeInTheDocument();
  });

  it('SHIPPING 상태를 배송중으로 표시한다', () => {
    render(<StatusBadge status="SHIPPING" />);
    expect(screen.getByText('배송중')).toBeInTheDocument();
  });

  it('COMPLETED 상태를 완료로 표시한다', () => {
    render(<StatusBadge status="COMPLETED" />);
    expect(screen.getByText('완료')).toBeInTheDocument();
  });

  it('CANCELLED 상태를 취소로 표시한다', () => {
    const { container } = render(<StatusBadge status="CANCELLED" />);
    expect(screen.getByText('취소')).toBeInTheDocument();
    expect(container.firstChild).toHaveClass('bg-red-100');
  });

  it('알 수 없는 상태는 원본 문자열을 표시한다', () => {
    render(<StatusBadge status="UNKNOWN_STATUS" />);
    expect(screen.getByText('UNKNOWN_STATUS')).toBeInTheDocument();
  });

  it('커스텀 className이 적용된다', () => {
    const { container } = render(
      <StatusBadge status="NORMAL" className="extra-class" />
    );
    expect(container.firstChild).toHaveClass('extra-class');
  });
});
