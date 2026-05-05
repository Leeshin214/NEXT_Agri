'use client';

import { useParams } from 'next/navigation';
import SellerProfileView from '@/components/members/SellerProfileView';

export default function BuyerMemberDetailPage() {
  const params = useParams<{ userId: string }>();
  const userId = params?.userId ?? '';
  return <SellerProfileView userId={userId} basePath="/buyer" />;
}
