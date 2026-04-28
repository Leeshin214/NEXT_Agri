'use client';

import { useEffect, useState } from 'react';
import { Search, Plus, Check, Building2, Phone } from 'lucide-react';
import Modal from '@/components/common/Modal';
import { useMembers } from '@/hooks/useMembers';
import { useCreatePartner, usePartnerUserIdSet } from '@/hooks/usePartners';
import type { UserPublicProfile, UserRole } from '@/types';

interface AddPartnerModalProps {
  isOpen: boolean;
  onClose: () => void;
  myRole: 'SELLER' | 'BUYER'; // 본인 역할 — 검색은 반대 역할만
}

const ROLE_LABEL: Record<UserRole, string> = {
  SELLER: '판매자',
  BUYER: '구매자',
  ADMIN: '관리자',
};

const ROLE_BADGE_CLASS: Record<UserRole, string> = {
  SELLER: 'bg-primary-100 text-primary-700',
  BUYER: 'bg-blue-100 text-blue-700',
  ADMIN: 'bg-gray-100 text-gray-700',
};

export default function AddPartnerModal({
  isOpen,
  onClose,
  myRole,
}: AddPartnerModalProps) {
  const [searchInput, setSearchInput] = useState('');
  const [searchTerm, setSearchTerm] = useState('');

  // 모달 열릴 때마다 검색 입력 초기화
  useEffect(() => {
    if (isOpen) {
      setSearchInput('');
      setSearchTerm('');
    }
  }, [isOpen]);

  const oppositeRole: 'SELLER' | 'BUYER' =
    myRole === 'SELLER' ? 'BUYER' : 'SELLER';

  // 검색어 입력 후 엔터 또는 검색 버튼 클릭 시에만 실제 쿼리 실행
  const { data, isLoading, isFetching } = useMembers(
    searchTerm
      ? { search: searchTerm, role: oppositeRole }
      : { role: oppositeRole }
  );
  const allMembers = data?.data ?? [];
  // role 인자가 백엔드에서 반영되지 않을 가능성에 대비한 클라이언트 폴백 필터
  const members = allMembers.filter((m) => m.role === oppositeRole);

  const partnerUserIdSet = usePartnerUserIdSet();
  const createPartner = useCreatePartner();
  const [pendingId, setPendingId] = useState<string | null>(null);

  const handleSearch = () => {
    setSearchTerm(searchInput.trim());
  };

  const handleAdd = (member: UserPublicProfile) => {
    if (pendingId || partnerUserIdSet.has(member.id)) return;
    setPendingId(member.id);
    createPartner.mutate(
      { partner_user_id: member.id },
      {
        onSettled: () => setPendingId(null),
      }
    );
  };

  return (
    <Modal isOpen={isOpen} onClose={onClose} title="거래처 추가" size="lg">
      <div className="space-y-4">
        {/* 검색 입력 */}
        <div className="flex gap-2">
          <div className="relative flex-1">
            <Search className="absolute left-3 top-1/2 h-4 w-4 -translate-y-1/2 text-gray-400" />
            <input
              type="text"
              value={searchInput}
              onChange={(e) => setSearchInput(e.target.value)}
              onKeyDown={(e) => {
                if (e.key === 'Enter') {
                  e.preventDefault();
                  handleSearch();
                }
              }}
              placeholder={`${
                oppositeRole === 'SELLER' ? '판매자' : '구매자'
              } 회사명 또는 이름으로 검색...`}
              className="w-full rounded-lg border border-gray-300 py-2 pl-9 pr-3 text-sm focus:border-primary-500 focus:outline-none focus:ring-1 focus:ring-primary-500"
            />
          </div>
          <button
            type="button"
            onClick={handleSearch}
            className="rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700"
          >
            검색
          </button>
        </div>

        {/* 결과 영역 */}
        <div className="min-h-[200px]">
          {!searchTerm ? (
            <div className="py-12 text-center text-sm text-gray-400">
              회사명 또는 이름으로 검색하세요.
            </div>
          ) : isLoading || isFetching ? (
            <div className="py-12 text-center text-sm text-gray-400">
              검색 중...
            </div>
          ) : members.length === 0 ? (
            <div className="py-12 text-center text-sm text-gray-400">
              검색 결과가 없습니다.
            </div>
          ) : (
            <ul className="space-y-2">
              {members.map((member) => {
                const isAlreadyPartner = partnerUserIdSet.has(member.id);
                const isPending = pendingId === member.id;

                return (
                  <li
                    key={member.id}
                    className="flex items-center justify-between gap-3 rounded-lg border border-gray-200 bg-white p-3 transition-colors hover:bg-gray-50"
                  >
                    {/* 좌측: 프로필 */}
                    <div className="flex min-w-0 flex-1 items-center gap-3">
                      {member.profile_image ? (
                        <img
                          src={member.profile_image}
                          alt={member.name}
                          className="h-10 w-10 flex-shrink-0 rounded-full object-cover"
                        />
                      ) : (
                        <div className="flex h-10 w-10 flex-shrink-0 items-center justify-center rounded-full bg-primary-100 text-sm font-semibold text-primary-700">
                          {member.name.charAt(0)}
                        </div>
                      )}
                      <div className="min-w-0 flex-1">
                        <div className="flex items-center gap-2">
                          <p className="truncate font-medium text-gray-900">
                            {member.name}
                          </p>
                          <span
                            className={`flex-shrink-0 rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_BADGE_CLASS[member.role]}`}
                          >
                            {ROLE_LABEL[member.role]}
                          </span>
                        </div>
                        <div className="mt-0.5 flex items-center gap-3 text-xs text-gray-500">
                          {member.company_name && (
                            <span className="flex items-center gap-1 truncate">
                              <Building2 className="h-3 w-3 flex-shrink-0" />
                              {member.company_name}
                            </span>
                          )}
                          {member.phone && (
                            <span className="flex items-center gap-1">
                              <Phone className="h-3 w-3 flex-shrink-0" />
                              {member.phone}
                            </span>
                          )}
                        </div>
                      </div>
                    </div>

                    {/* 우측: 액션 */}
                    <div className="flex-shrink-0">
                      {isAlreadyPartner ? (
                        <span className="inline-flex items-center gap-1 rounded-lg bg-gray-100 px-3 py-1.5 text-xs font-medium text-gray-500">
                          <Check className="h-3.5 w-3.5" />
                          거래처 등록됨
                        </span>
                      ) : (
                        <button
                          type="button"
                          onClick={() => handleAdd(member)}
                          disabled={isPending || !!pendingId}
                          className="inline-flex items-center gap-1 rounded-lg bg-primary-600 px-3 py-1.5 text-xs font-medium text-white hover:bg-primary-700 disabled:opacity-50"
                        >
                          <Plus className="h-3.5 w-3.5" />
                          {isPending ? '추가 중...' : '추가'}
                        </button>
                      )}
                    </div>
                  </li>
                );
              })}
            </ul>
          )}
        </div>
      </div>
    </Modal>
  );
}
