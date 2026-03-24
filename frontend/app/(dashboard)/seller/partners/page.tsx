'use client';

import { useState } from 'react';
import { Star, StarOff } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import DataTable, { type Column } from '@/components/common/DataTable';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import StatusBadge from '@/components/common/StatusBadge';
import { usePartners, useUpdatePartner } from '@/hooks/usePartners';
import { PARTNER_STATUS_OPTIONS } from '@/constants/options';
import type { Partner } from '@/types';

export default function SellerPartnersPage() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const { data, isLoading } = usePartners({
    partner_status: statusFilter || undefined,
    search: search || undefined,
  });
  const updatePartner = useUpdatePartner();
  const partners = data?.data ?? [];

  const toggleFavorite = (partner: Partner) => {
    updatePartner.mutate({
      id: partner.id,
      data: { is_favorite: !partner.is_favorite },
    });
  };

  const columns: Column<Partner>[] = [
    {
      key: 'is_favorite',
      header: '',
      className: 'w-10',
      render: (item) => (
        <button
          onClick={(e) => { e.stopPropagation(); toggleFavorite(item); }}
          className="text-gray-300 hover:text-yellow-400"
        >
          {item.is_favorite ? (
            <Star className="h-4 w-4 fill-yellow-400 text-yellow-400" />
          ) : (
            <StarOff className="h-4 w-4" />
          )}
        </button>
      ),
    },
    {
      key: 'partner_company',
      header: '업체명',
      render: (item) => (
        <div>
          <p className="font-medium text-gray-900">
            {item.partner_company || '-'}
          </p>
          <p className="text-xs text-gray-500">{item.partner_name}</p>
        </div>
      ),
    },
    {
      key: 'nickname',
      header: '별칭',
      render: (item) => (
        <span className="text-gray-600">{item.nickname || '-'}</span>
      ),
    },
    {
      key: 'partner_role',
      header: '유형',
      render: (item) => (
        <span className="text-xs text-gray-500">
          {item.partner_role === 'BUYER' ? '구매자' : '판매자'}
        </span>
      ),
    },
    {
      key: 'status',
      header: '상태',
      render: (item) => <StatusBadge status={item.status} />,
    },
  ];

  return (
    <div>
      <PageHeader
        title="거래처 목록"
        description="바이어 거래처를 관리하세요"
      />

      <SearchFilterBar
        searchValue={search}
        onSearchChange={setSearch}
        searchPlaceholder="거래처명 검색..."
        filters={[
          {
            key: 'status',
            label: '전체 상태',
            options: PARTNER_STATUS_OPTIONS,
            value: statusFilter,
            onChange: setStatusFilter,
          },
        ]}
      />

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">
          로딩 중...
        </div>
      ) : (
        <DataTable
          columns={columns}
          data={partners}
          emptyMessage="등록된 거래처가 없습니다."
        />
      )}
    </div>
  );
}
