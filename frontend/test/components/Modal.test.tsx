import { render, screen, fireEvent } from '@testing-library/react';
import { describe, it, expect, vi } from 'vitest';
import Modal from '@/components/common/Modal';

describe('Modal', () => {
  it('isOpen이 true일 때 내용을 렌더링한다', () => {
    render(
      <Modal isOpen={true} onClose={() => {}} title="테스트 모달">
        <p>모달 내용</p>
      </Modal>
    );
    expect(screen.getByText('테스트 모달')).toBeInTheDocument();
    expect(screen.getByText('모달 내용')).toBeInTheDocument();
  });

  it('isOpen이 false일 때 내용을 렌더링하지 않는다', () => {
    render(
      <Modal isOpen={false} onClose={() => {}} title="숨긴 모달">
        <p>숨겨진 내용</p>
      </Modal>
    );
    expect(screen.queryByText('숨긴 모달')).not.toBeInTheDocument();
  });

  it('닫기 버튼 클릭 시 onClose가 호출된다', () => {
    const onClose = vi.fn();
    render(
      <Modal isOpen={true} onClose={onClose} title="닫기 테스트">
        <p>내용</p>
      </Modal>
    );
    const closeButton = screen.getByRole('button');
    fireEvent.click(closeButton);
    expect(onClose).toHaveBeenCalledTimes(1);
  });
});
