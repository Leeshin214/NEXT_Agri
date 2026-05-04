import OrderDetailView from '@/components/orders/OrderDetailView';

interface PageProps {
  params: { id: string };
}

/**
 * 구매자 주문 상세 페이지.
 *
 * 진입 경로:
 * - 캘린더 → "주문 상세 보기" 버튼 (EventDetailModal)
 * - 알림 클릭 → /buyer/orders/{id}
 * - 직접 URL 입력
 *
 * Next.js App Router 의 동적 세그먼트 `[id]` 는 params.id 로 전달된다.
 */
export default function BuyerOrderDetailPage({ params }: PageProps) {
  return <OrderDetailView orderId={params.id} myRole="BUYER" />;
}
