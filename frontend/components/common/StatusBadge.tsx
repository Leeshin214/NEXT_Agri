import { cn } from '@/lib/utils';

const statusConfig: Record<string, { label: string; className: string }> = {
  // 상품 상태
  NORMAL: { label: '정상', className: 'bg-green-100 text-green-800' },
  LOW_STOCK: { label: '재고부족', className: 'bg-yellow-100 text-yellow-800' },
  OUT_OF_STOCK: { label: '품절', className: 'bg-red-100 text-red-800' },
  SCHEDULED: { label: '출하예정', className: 'bg-blue-100 text-blue-800' },
  // 주문 상태
  QUOTE_REQUESTED: { label: '견적대기', className: 'bg-gray-100 text-gray-700' },
  NEGOTIATING: { label: '협상중', className: 'bg-orange-100 text-orange-800' },
  CONFIRMED: { label: '주문확정', className: 'bg-blue-100 text-blue-800' },
  PREPARING: { label: '출하준비', className: 'bg-purple-100 text-purple-800' },
  SHIPPING: { label: '배송중', className: 'bg-indigo-100 text-indigo-800' },
  COMPLETED: { label: '완료', className: 'bg-green-100 text-green-800' },
  CANCELLED: { label: '취소', className: 'bg-red-100 text-red-800' },
  // 거래처 상태
  ACTIVE: { label: '활성', className: 'bg-green-100 text-green-800' },
  INACTIVE: { label: '비활성', className: 'bg-gray-100 text-gray-600' },
  PENDING: { label: '대기', className: 'bg-yellow-100 text-yellow-800' },
};

interface StatusBadgeProps {
  status: string;
  className?: string;
}

export default function StatusBadge({ status, className }: StatusBadgeProps) {
  const config = statusConfig[status] || {
    label: status,
    className: 'bg-gray-100 text-gray-700',
  };

  return (
    <span
      className={cn(
        'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
        config.className,
        className
      )}
    >
      {config.label}
    </span>
  );
}
