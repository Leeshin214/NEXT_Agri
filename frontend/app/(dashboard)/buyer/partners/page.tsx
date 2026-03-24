'use client';

import { useState } from 'react';
import { Star } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import DataTable, { type Column } from '@/components/common/DataTable';
import StatusBadge from '@/components/common/StatusBadge';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import { usePartners, useUpdatePartner } from '@/hooks/usePartners';
import { PARTNER_STATUS_OPTIONS } from '@/constants/options';
import type { Partner } from '@/types';

export default function BuyerPartnersPage() {
  const [search, setSearch] = useState('');
  const [statusFilter, setStatusFilter] = useState('');

  const { data, isLoading } = usePartners();
  const updatePartner = useUpdatePartner();
  const partners = data?.data ?? [];

  const filtered = partners.filter((p) => {
    const matchSearch =
      !search ||
      p.partner_name?.toLowerCase().includes(search.toLowerCase()) ||
      p.partner_company?.toLowerCase().includes(search.toLowerCase());
    const matchStatus = !statusFilter || p.status === statusFilter;
    return matchSearch && matchStatus;
  });

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
          <Star
            className={`h-4 w-4 ${item.is_favorite ? 'fill-yellow-400 text-yellow-400' : ''}`}
          />
        </button>
      ),
    },
    {
      key: 'partner_name',
      header: '담당자명',
      render: (item) => (
        <span className="font-medium text-gray-900">{item.partner_name || '-'}</span>
      ),
    },
    {
      key: 'partner_company',
      header: '업체명',
      render: (item) => (
        <span className="text-gray-600">{item.partner_company || '-'}</span>
      ),
    },
    {
      key: 'partner_phone',
      header: '연락처',
      render: (item) => (
        <span className="text-gray-600">{item.partner_phone || '-'}</span>
      ),
    },
    {
      key: 'status',
      header: '상태',
      render: (item) => <StatusBadge status={item.status} />,
    },
    {
      key: 'notes',
      header: '메모',
      render: (item) => (
        <span className="text-sm text-gray-500 truncate max-w-[200px] inline-block">
          {item.notes || '-'}
        </span>
      ),
    },
  ];

  return (
    <div>
      <PageHeader title="거래처 목록" description="공급처를 관리하세요" />

      <SearchFilterBar
        searchValue={search}
        onSearchChange={setSearch}
        searchPlaceholder="업체명 또는 담당자명 검색..."
        filters={[
          {
            key: 'status',
            label: '전체 상태',
            value: statusFilter,
            onChange: setStatusFilter,
            options: PARTNER_STATUS_OPTIONS,
          },
        ]}
      />

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      ) : (
        <DataTable
          columns={columns}
          data={filtered}
          emptyMessage="등록된 거래처가 없습니다."
        />
      )}
    </div>
  );
}
