import { render, screen } from '@testing-library/react';
import { describe, it, expect } from 'vitest';
import PageHeader from '@/components/common/PageHeader';

describe('PageHeader', () => {
  it('제목을 렌더링한다', () => {
    render(<PageHeader title="테스트 제목" />);
    expect(screen.getByText('테스트 제목')).toBeInTheDocument();
  });

  it('제목과 설명을 함께 렌더링한다', () => {
    render(<PageHeader title="대시보드" description="현황을 확인하세요" />);
    expect(screen.getByText('대시보드')).toBeInTheDocument();
    expect(screen.getByText('현황을 확인하세요')).toBeInTheDocument();
  });

  it('액션 슬롯을 렌더링한다', () => {
    render(
      <PageHeader
        title="상품 관리"
        action={<button>상품 등록</button>}
      />
    );
    expect(screen.getByText('상품 등록')).toBeInTheDocument();
  });

  it('설명이 없으면 설명 영역을 렌더링하지 않는다', () => {
    const { container } = render(<PageHeader title="제목만" />);
    const paragraphs = container.querySelectorAll('p');
    expect(paragraphs.length).toBe(0);
  });
});
