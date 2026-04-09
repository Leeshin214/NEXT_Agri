'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { MessageCircle, User, Phone, Building2, Calendar } from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import SearchFilterBar from '@/components/common/SearchFilterBar';
import Modal from '@/components/common/Modal';
import { useMembers, useMemberProfile } from '@/hooks/useMembers';
import { useCreateChatRoom } from '@/hooks/useChat';
import type { UserPublicProfile } from '@/types';

type SearchRole = 'BUYER' | 'SELLER';

const ROLE_LABEL: Record<string, string> = {
  SELLER: '판매자',
  BUYER: '구매자',
  ADMIN: '관리자',
};

const ROLE_BADGE_CLASS: Record<string, string> = {
  SELLER: 'bg-primary-100 text-primary-700',
  BUYER: 'bg-blue-100 text-blue-700',
  ADMIN: 'bg-gray-100 text-gray-700',
};

function formatDate(iso: string) {
  return new Date(iso).toLocaleDateString('ko-KR', {
    year: 'numeric',
    month: '2-digit',
    day: '2-digit',
  });
}

// ─── 탭바 ───

interface RoleTabBarProps {
  selected: SearchRole;
  onChange: (role: SearchRole) => void;
}

function RoleTabBar({ selected, onChange }: RoleTabBarProps) {
  const tabs: { role: SearchRole; label: string }[] = [
    { role: 'BUYER', label: '구매자' },
    { role: 'SELLER', label: '판매자' },
  ];

  return (
    <div className="mb-6 inline-flex rounded-lg border border-gray-200 bg-gray-100 p-1">
      {tabs.map(({ role, label }) => (
        <button
          key={role}
          onClick={() => onChange(role)}
          className={`rounded-md px-5 py-2 text-sm font-medium transition-all ${
            selected === role
              ? 'bg-white text-primary-700 shadow-sm'
              : 'text-gray-500 hover:text-gray-700'
          }`}
        >
          {label}
        </button>
      ))}
    </div>
  );
}

// ─── 회원 카드 ───

interface MemberCardProps {
  member: UserPublicProfile;
  onCardClick: (userId: string) => void;
  onChat: (userId: string) => void;
  isChatPending: boolean;
}

function MemberCard({ member, onCardClick, onChat, isChatPending }: MemberCardProps) {
  return (
    <div
      onClick={() => onCardClick(member.id)}
      className="flex cursor-pointer flex-col gap-4 rounded-xl bg-white p-5 shadow-sm transition-shadow hover:shadow-md"
    >
      {/* 상단: 아바타 + 이름 + 역할 배지 */}
      <div className="flex items-center gap-3">
        {member.profile_image ? (
          <img
            src={member.profile_image}
            alt={member.name}
            className="h-12 w-12 rounded-full object-cover"
          />
        ) : (
          <div className="flex h-12 w-12 flex-shrink-0 items-center justify-center rounded-full bg-primary-100 text-primary-700 text-lg font-semibold">
            {member.name.charAt(0)}
          </div>
        )}
        <div className="min-w-0">
          <p className="truncate font-semibold text-gray-900">{member.name}</p>
          <span
            className={`mt-0.5 inline-block rounded-full px-2 py-0.5 text-xs font-medium ${ROLE_BADGE_CLASS[member.role] ?? 'bg-gray-100 text-gray-700'}`}
          >
            {ROLE_LABEL[member.role] ?? member.role}
          </span>
        </div>
      </div>

      {/* 중간: 상세 정보 */}
      <div className="space-y-2 text-sm text-gray-600">
        {member.company_name && (
          <div className="flex items-center gap-2">
            <Building2 className="h-4 w-4 flex-shrink-0 text-gray-400" />
            <span className="truncate">{member.company_name}</span>
          </div>
        )}
        {member.phone ? (
          <div className="flex items-center gap-2">
            <Phone className="h-4 w-4 flex-shrink-0 text-gray-400" />
            <span>{member.phone}</span>
          </div>
        ) : (
          <div className="flex items-center gap-2">
            <Phone className="h-4 w-4 flex-shrink-0 text-gray-400" />
            <span className="text-gray-400">연락처 없음</span>
          </div>
        )}
        <div className="flex items-center gap-2">
          <Calendar className="h-4 w-4 flex-shrink-0 text-gray-400" />
          <span>가입 {formatDate(member.created_at)}</span>
        </div>
      </div>

      {/* 하단: 채팅하기 버튼 */}
      <button
        onClick={(e) => {
          e.stopPropagation();
          onChat(member.id);
        }}
        disabled={isChatPending}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary-600 px-4 py-2 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
      >
        <MessageCircle className="h-4 w-4" />
        채팅하기
      </button>
    </div>
  );
}

// ─── 프로필 모달 내용 ───

function ProfileModalContent({
  userId,
  onChat,
  isChatPending,
}: {
  userId: string;
  onChat: (userId: string) => void;
  isChatPending: boolean;
}) {
  const { data, isLoading } = useMemberProfile(userId);
  const profile = data?.data;

  if (isLoading) {
    return (
      <div className="py-8 text-center text-sm text-gray-400">로딩 중...</div>
    );
  }

  if (!profile) {
    return (
      <div className="py-8 text-center text-sm text-gray-400">
        프로필을 불러올 수 없습니다.
      </div>
    );
  }

  return (
    <div className="space-y-5">
      {/* 프로필 이미지 + 이름 */}
      <div className="flex flex-col items-center gap-3">
        {profile.profile_image ? (
          <img
            src={profile.profile_image}
            alt={profile.name}
            className="h-20 w-20 rounded-full object-cover"
          />
        ) : (
          <div className="flex h-20 w-20 items-center justify-center rounded-full bg-primary-100 text-primary-700 text-3xl font-semibold">
            {profile.name.charAt(0)}
          </div>
        )}
        <div className="text-center">
          <p className="text-lg font-semibold text-gray-900">{profile.name}</p>
          <span
            className={`mt-1 inline-block rounded-full px-2.5 py-0.5 text-xs font-medium ${ROLE_BADGE_CLASS[profile.role] ?? 'bg-gray-100 text-gray-700'}`}
          >
            {ROLE_LABEL[profile.role] ?? profile.role}
          </span>
        </div>
      </div>

      {/* 상세 정보 (이메일 제외) */}
      <dl className="divide-y divide-gray-100 rounded-lg border border-gray-200">
        {profile.company_name && (
          <div className="flex px-4 py-3">
            <dt className="w-24 flex-shrink-0 text-sm text-gray-500">업체명</dt>
            <dd className="text-sm font-medium text-gray-900">
              {profile.company_name}
            </dd>
          </div>
        )}
        {profile.phone && (
          <div className="flex px-4 py-3">
            <dt className="w-24 flex-shrink-0 text-sm text-gray-500">연락처</dt>
            <dd className="text-sm text-gray-900">{profile.phone}</dd>
          </div>
        )}
        <div className="flex px-4 py-3">
          <dt className="w-24 flex-shrink-0 text-sm text-gray-500">가입일</dt>
          <dd className="text-sm text-gray-900">{formatDate(profile.created_at)}</dd>
        </div>
      </dl>

      {/* 채팅하기 버튼 */}
      <button
        onClick={() => onChat(profile.id)}
        disabled={isChatPending}
        className="flex w-full items-center justify-center gap-2 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-medium text-white hover:bg-primary-700 disabled:opacity-50 transition-colors"
      >
        <MessageCircle className="h-4 w-4" />
        {isChatPending ? '채팅방 생성 중...' : '채팅하기'}
      </button>
    </div>
  );
}

// ─── 페이지 ───

export default function SellerMembersPage() {
  const router = useRouter();
  const [search, setSearch] = useState('');
  const [selectedRole, setSelectedRole] = useState<SearchRole>('BUYER');
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);

  const { data, isLoading } = useMembers({
    search: search || undefined,
    role: selectedRole,
  });
  const members = data?.data ?? [];

  const createChatRoom = useCreateChatRoom();

  const handleChat = (userId: string) => {
    createChatRoom.mutate(
      { partner_user_id: userId },
      {
        onSuccess: () => {
          setSelectedUserId(null);
          router.push('/seller/chat');
        },
      }
    );
  };

  const handleRoleChange = (role: SearchRole) => {
    setSelectedRole(role);
    setSearch('');
  };

  return (
    <div>
      <PageHeader title="회원 검색" />

      <RoleTabBar selected={selectedRole} onChange={handleRoleChange} />

      <SearchFilterBar
        searchValue={search}
        onSearchChange={setSearch}
        searchPlaceholder="이름, 업체명으로 검색..."
      />

      {isLoading ? (
        <div className="py-12 text-center text-sm text-gray-400">로딩 중...</div>
      ) : members.length === 0 ? (
        <div className="py-12 text-center text-sm text-gray-400">
          검색 결과가 없습니다.
        </div>
      ) : (
        <div className="grid grid-cols-1 gap-4 md:grid-cols-2 lg:grid-cols-3">
          {members.map((member) => (
            <MemberCard
              key={member.id}
              member={member}
              onCardClick={setSelectedUserId}
              onChat={handleChat}
              isChatPending={createChatRoom.isPending}
            />
          ))}
        </div>
      )}

      {/* 프로필 상세 모달 */}
      <Modal
        isOpen={!!selectedUserId}
        onClose={() => setSelectedUserId(null)}
        title="회원 프로필"
        size="sm"
      >
        {selectedUserId && (
          <ProfileModalContent
            userId={selectedUserId}
            onChat={handleChat}
            isChatPending={createChatRoom.isPending}
          />
        )}
      </Modal>
    </div>
  );
}
