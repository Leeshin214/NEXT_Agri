'use client';

import { useMemo, useState } from 'react';
import { useRouter } from 'next/navigation';
import {
  ArrowLeft,
  Building2,
  Calendar,
  Check,
  Clock,
  Inbox,
  Mail,
  MessageCircle,
  Package,
  Phone,
  ShoppingBag,
  UserPlus,
  UserRound,
} from 'lucide-react';
import PageHeader from '@/components/common/PageHeader';
import StatusBadge from '@/components/common/StatusBadge';
import { useMemberProfile } from '@/hooks/useMembers';
import { useProducts } from '@/hooks/useProducts';
import { useCreateChatRoom } from '@/hooks/useChat';
import {
  useAcceptPartner,
  useCreatePartner,
  usePartnerStatusMap,
  usePartners,
} from '@/hooks/usePartners';
import { useAuthStore } from '@/store/authStore';
import { CATEGORY_OPTIONS } from '@/constants/options';
import { cn } from '@/lib/utils';
import type {
  PartnerStatus,
  Product,
  ProductCategory,
  UserRole,
} from '@/types';

type BasePath = '/buyer' | '/seller';

interface SellerProfileViewProps {
  userId: string;
  basePath: BasePath;
}

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

function categoryLabel(category: string) {
  return (
    CATEGORY_OPTIONS.find((c) => c.value === category)?.label || category
  );
}

export default function SellerProfileView({
  userId,
  basePath,
}: SellerProfileViewProps) {
  const router = useRouter();
  const { user } = useAuthStore();
  const myRole: UserRole | undefined = user?.role;

  const [categoryFilter, setCategoryFilter] = useState<ProductCategory | ''>('');

  const profileQuery = useMemberProfile(userId);
  const profile = profileQuery.data?.data;

  // 판매자가 등록한 상품 목록 — backend 는 SELLER 의 자기 자신 강제 매핑이 있지만
  // seller_id 가 명시되면 그대로 적용된다. BUYER 시점에서도 동일.
  const productsQuery = useProducts({
    seller_id: userId,
    category: categoryFilter || undefined,
  });
  const products = productsQuery.data?.data ?? [];

  const partnerStatusMap = usePartnerStatusMap();
  const partnersQuery = usePartners();
  const partnerIdByUserId = useMemo(() => {
    const map = new Map<string, string>();
    for (const p of partnersQuery.data?.data ?? []) {
      map.set(p.partner_user_id, p.id);
    }
    return map;
  }, [partnersQuery.data]);

  const partnerStatus = partnerStatusMap.get(userId);
  const partnerId = partnerIdByUserId.get(userId);

  const createChatRoom = useCreateChatRoom();
  const createPartner = useCreatePartner();
  const acceptPartner = useAcceptPartner();

  const handleBack = () => {
    router.push(`${basePath}/members`);
  };

  const handleChat = () => {
    if (!profile || createChatRoom.isPending) return;
    createChatRoom.mutate(
      { partner_user_id: profile.id },
      {
        onSuccess: () => {
          router.push(`${basePath}/chat`);
        },
      }
    );
  };

  const handleAddPartner = () => {
    if (!profile || createPartner.isPending) return;
    createPartner.mutate({ partner_user_id: profile.id });
  };

  const handleAcceptPartner = () => {
    if (!partnerId || acceptPartner.isPending) return;
    acceptPartner.mutate(partnerId);
  };

  // ─── 로딩 / 에러 처리 ───────────────────────────
  if (profileQuery.isLoading) {
    return (
      <div>
        <BackLink onClick={handleBack} />
        <PageHeader title="판매자 정보" />
        <div className="rounded-xl bg-white p-12 text-center text-sm text-gray-400 shadow-sm">
          판매자 정보를 불러오는 중...
        </div>
      </div>
    );
  }

  if (profileQuery.error || !profile) {
    return (
      <div>
        <BackLink onClick={handleBack} />
        <PageHeader title="판매자 정보" />
        <div className="rounded-xl bg-white p-12 text-center shadow-sm">
          <UserRound className="mx-auto mb-3 h-12 w-12 text-gray-300" />
          <p className="text-sm text-gray-500">
            판매자 정보를 찾을 수 없거나 접근할 수 없습니다.
          </p>
          <button
            onClick={handleBack}
            className="mt-4 inline-flex items-center gap-1 rounded-lg border border-gray-300 bg-white px-3 py-1.5 text-xs font-medium text-gray-700 hover:bg-gray-50"
          >
            <ArrowLeft className="h-3.5 w-3.5" />
            회원 목록으로
          </button>
        </div>
      </div>
    );
  }

  const headerTitle = profile.company_name || profile.name;
  const headerDescription = profile.company_name ? `담당자 ${profile.name}` : '';

  // 본인과 같은 역할(또는 ADMIN) 인 경우 거래처 액션 자체를 숨김
  const canActPartner =
    !!myRole && profile.role !== myRole && profile.role !== 'ADMIN';

  return (
    <div>
      <BackLink onClick={handleBack} />
      <PageHeader title={headerTitle} description={headerDescription} />

      {/* Hero 영역 — 프로필 이미지 + 핵심 정보 + 액션 */}
      <div className="mb-6 grid grid-cols-1 gap-6 rounded-xl bg-white p-4 shadow-sm md:p-6 lg:grid-cols-[240px_1fr]">
        {/* 좌측 — 프로필 이미지 */}
        <div className="flex aspect-square w-full max-w-[240px] items-center justify-center overflow-hidden rounded-xl bg-gray-50 lg:max-w-none">
          {profile.profile_image ? (
            // eslint-disable-next-line @next/next/no-img-element
            <img
              src={profile.profile_image}
              alt={profile.name}
              className="h-full w-full object-cover"
            />
          ) : (
            <div className="flex h-full w-full items-center justify-center bg-primary-50 text-6xl font-semibold text-primary-700">
              {profile.name.charAt(0)}
            </div>
          )}
        </div>

        {/* 우측 — 핵심 정보 + 액션 */}
        <div className="flex flex-col">
          <div className="mb-3 flex flex-wrap items-center gap-2">
            <span
              className={cn(
                'inline-flex items-center rounded-full px-2.5 py-0.5 text-xs font-medium',
                ROLE_BADGE_CLASS[profile.role] ?? 'bg-gray-100 text-gray-700'
              )}
            >
              {ROLE_LABEL[profile.role] ?? profile.role}
            </span>
            {canActPartner && partnerStatus && (
              <PartnerStatusBadge status={partnerStatus} />
            )}
          </div>

          <h2 className="mb-1 text-xl font-semibold text-gray-900 sm:text-2xl">
            {profile.company_name || profile.name}
          </h2>
          {profile.company_name && (
            <p className="mb-3 text-sm text-gray-500">담당자 {profile.name}</p>
          )}

          <div className="mb-5 grid grid-cols-2 gap-2 text-xs">
            <SummaryCell
              label="등록 상품"
              value={
                productsQuery.isLoading
                  ? '...'
                  : `${products.length.toLocaleString()}개`
              }
            />
            <SummaryCell label="가입일" value={formatDate(profile.created_at)} />
          </div>

          {/* 액션 버튼 */}
          <div className="mt-auto flex flex-col gap-2 sm:flex-row">
            <button
              onClick={handleChat}
              disabled={createChatRoom.isPending}
              className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-primary-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-primary-700 disabled:opacity-50"
            >
              <MessageCircle className="h-4 w-4" />
              {createChatRoom.isPending ? '연결 중...' : '채팅하기'}
            </button>
            {canActPartner && (
              <PartnerActionButton
                status={partnerStatus}
                isAdding={createPartner.isPending}
                isAccepting={acceptPartner.isPending}
                onAdd={handleAddPartner}
                onAccept={handleAcceptPartner}
              />
            )}
          </div>
        </div>
      </div>

      {/* 회사/연락처 정보 카드 */}
      <div className="mb-6 rounded-xl bg-white p-4 shadow-sm md:p-6">
        <h3 className="mb-3 text-sm font-semibold text-gray-900">회사 정보</h3>
        <dl className="grid grid-cols-1 gap-x-4 gap-y-3 text-sm sm:grid-cols-2">
          <InfoRow
            icon={<Building2 className="h-4 w-4 text-gray-400" />}
            label="업체명"
            value={profile.company_name || '미등록'}
          />
          <InfoRow
            icon={<UserRound className="h-4 w-4 text-gray-400" />}
            label="담당자"
            value={profile.name}
          />
          <InfoRow
            icon={<Phone className="h-4 w-4 text-gray-400" />}
            label="연락처"
            value={profile.phone || '미등록'}
          />
          <InfoRow
            icon={<Mail className="h-4 w-4 text-gray-400" />}
            label="이메일"
            value={profile.email}
          />
          <InfoRow
            icon={<Calendar className="h-4 w-4 text-gray-400" />}
            label="가입일"
            value={formatDate(profile.created_at)}
          />
          <InfoRow
            icon={<ShoppingBag className="h-4 w-4 text-gray-400" />}
            label="등록 상품"
            value={
              productsQuery.isLoading
                ? '불러오는 중...'
                : `${products.length.toLocaleString()}개`
            }
          />
        </dl>
      </div>

      {/* 판매 상품 섹션 */}
      <div className="rounded-xl bg-white p-4 shadow-sm md:p-6">
        <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
          <div>
            <h3 className="text-sm font-semibold text-gray-900">판매 상품</h3>
            <p className="mt-0.5 text-xs text-gray-500">
              {profile.company_name || profile.name}의 등록 상품
            </p>
          </div>
          {/* 카테고리 필터 — 상품이 1개 이상일 때만 노출 */}
          {(products.length > 0 || categoryFilter) && (
            <div className="flex flex-wrap gap-1.5">
              <FilterChip
                active={categoryFilter === ''}
                onClick={() => setCategoryFilter('')}
              >
                전체
              </FilterChip>
              {CATEGORY_OPTIONS.map((c) => (
                <FilterChip
                  key={c.value}
                  active={categoryFilter === c.value}
                  onClick={() => setCategoryFilter(c.value)}
                >
                  {c.label}
                </FilterChip>
              ))}
            </div>
          )}
        </div>

        {productsQuery.isLoading ? (
          <div className="py-12 text-center text-sm text-gray-400">
            상품 목록을 불러오는 중...
          </div>
        ) : products.length === 0 ? (
          <div className="flex flex-col items-center justify-center py-16 text-gray-400">
            <Package className="mb-3 h-10 w-10" />
            <p className="text-sm">
              {categoryFilter
                ? '해당 카테고리에 등록된 상품이 없습니다.'
                : '아직 등록된 상품이 없습니다.'}
            </p>
          </div>
        ) : (
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-3 lg:grid-cols-4">
            {products.map((product) => (
              <SellerProductCard
                key={product.id}
                product={product}
                basePath={basePath}
              />
            ))}
          </div>
        )}
      </div>
    </div>
  );
}

// ─── Sub-components ───────────────────────────────────────────

function BackLink({ onClick }: { onClick: () => void }) {
  return (
    <div className="mb-3">
      <button
        onClick={onClick}
        className="inline-flex items-center gap-1 text-xs font-medium text-gray-500 hover:text-gray-700"
      >
        <ArrowLeft className="h-3.5 w-3.5" />
        회원 목록으로
      </button>
    </div>
  );
}

function SummaryCell({ label, value }: { label: string; value: string }) {
  return (
    <div className="rounded-lg bg-gray-50 px-3 py-2">
      <p className="text-[11px] text-gray-500">{label}</p>
      <p className="mt-0.5 text-sm font-medium text-gray-900">{value}</p>
    </div>
  );
}

function InfoRow({
  icon,
  label,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  value: React.ReactNode;
}) {
  return (
    <div className="flex items-start gap-2.5">
      <span className="flex h-5 items-center">{icon}</span>
      <div className="min-w-0">
        <dt className="text-[11px] text-gray-500">{label}</dt>
        <dd className="mt-0.5 truncate text-sm font-medium text-gray-900">
          {value}
        </dd>
      </div>
    </div>
  );
}

function FilterChip({
  active,
  onClick,
  children,
}: {
  active: boolean;
  onClick: () => void;
  children: React.ReactNode;
}) {
  return (
    <button
      onClick={onClick}
      className={cn(
        'rounded-full px-3 py-1 text-xs font-medium transition-colors',
        active
          ? 'bg-primary-600 text-white'
          : 'border border-gray-200 bg-white text-gray-600 hover:bg-gray-50'
      )}
    >
      {children}
    </button>
  );
}

function PartnerStatusBadge({ status }: { status: PartnerStatus }) {
  // members/page.tsx 에서 사용하는 동일한 분기 라벨
  if (status === 'ACTIVE' || status === 'PENDING') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-primary-50 px-2.5 py-0.5 text-xs font-medium text-primary-700">
        <Check className="h-3 w-3" />
        거래처 등록됨
      </span>
    );
  }
  if (status === 'PENDING_OUTGOING') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full border border-yellow-200 bg-yellow-50 px-2.5 py-0.5 text-xs font-medium text-yellow-700">
        <Clock className="h-3 w-3" />
        요청 보냄
      </span>
    );
  }
  if (status === 'PENDING_INCOMING') {
    return (
      <span className="inline-flex items-center gap-1 rounded-full bg-blue-50 px-2.5 py-0.5 text-xs font-medium text-blue-700">
        <Inbox className="h-3 w-3" />
        받은 요청
      </span>
    );
  }
  return null;
}

function PartnerActionButton({
  status,
  isAdding,
  isAccepting,
  onAdd,
  onAccept,
}: {
  status: PartnerStatus | undefined;
  isAdding: boolean;
  isAccepting: boolean;
  onAdd: () => void;
  onAccept: () => void;
}) {
  if (status === 'ACTIVE' || status === 'PENDING') {
    return (
      <span className="flex flex-1 items-center justify-center gap-1 rounded-lg bg-gray-100 px-4 py-2.5 text-sm font-medium text-gray-500">
        <Check className="h-4 w-4" />
        거래처 등록됨
      </span>
    );
  }
  if (status === 'PENDING_OUTGOING') {
    return (
      <span className="flex flex-1 items-center justify-center gap-1 rounded-lg border border-yellow-200 bg-yellow-50 px-4 py-2.5 text-sm font-medium text-yellow-700">
        <Clock className="h-4 w-4" />
        요청 보냄
      </span>
    );
  }
  if (status === 'PENDING_INCOMING') {
    return (
      <button
        onClick={onAccept}
        disabled={isAccepting}
        className="flex flex-1 items-center justify-center gap-1.5 rounded-lg bg-blue-600 px-4 py-2.5 text-sm font-medium text-white transition-colors hover:bg-blue-700 disabled:opacity-50"
      >
        <Inbox className="h-4 w-4" />
        {isAccepting ? '수락 중...' : '요청 수락'}
      </button>
    );
  }
  // !status (신규) 또는 INACTIVE → 거래처 추가 버튼
  return (
    <button
      onClick={onAdd}
      disabled={isAdding}
      className="flex flex-1 items-center justify-center gap-1.5 rounded-lg border border-primary-600 bg-white px-4 py-2.5 text-sm font-medium text-primary-700 transition-colors hover:bg-primary-50 disabled:opacity-50"
    >
      <UserPlus className="h-4 w-4" />
      {isAdding ? '추가 중...' : '거래처 추가'}
    </button>
  );
}

function SellerProductCard({
  product,
  basePath,
}: {
  product: Product;
  basePath: BasePath;
}) {
  const router = useRouter();
  const isOutOfStock = product.stock_quantity === 0;
  // 상품 상세는 buyer 동선에만 존재 — seller 시점에선 라우팅 비활성화
  const canOpenDetail = basePath === '/buyer';

  return (
    <button
      type="button"
      onClick={() => {
        if (canOpenDetail) router.push(`${basePath}/browse/${product.id}`);
      }}
      disabled={!canOpenDetail}
      className={cn(
        'group overflow-hidden rounded-lg border border-gray-100 bg-white text-left shadow-sm transition-shadow',
        canOpenDetail
          ? 'cursor-pointer hover:shadow-md'
          : 'cursor-default'
      )}
    >
      <div className="flex h-32 items-center justify-center bg-gray-50">
        {product.image_url ? (
          // eslint-disable-next-line @next/next/no-img-element
          <img
            src={product.image_url}
            alt={product.name}
            className="h-full w-full object-cover"
          />
        ) : (
          <Package className="h-10 w-10 text-gray-300" />
        )}
      </div>
      <div className="p-3">
        <div className="mb-1 flex items-start justify-between gap-2">
          <h4 className="truncate text-sm font-semibold text-gray-900">
            {product.name}
          </h4>
          <StatusBadge status={product.status} />
        </div>
        <p className="mb-1.5 text-[11px] text-gray-500">
          {categoryLabel(product.category)}
          {product.origin ? ` · ${product.origin}` : ''}
        </p>
        <div className="flex items-baseline gap-1">
          <span className="text-base font-bold text-gray-900">
            {product.price_per_unit.toLocaleString()}원
          </span>
          <span className="text-[11px] text-gray-500">/ {product.unit}</span>
        </div>
        <p
          className={cn(
            'mt-1 text-[11px]',
            isOutOfStock ? 'text-red-500' : 'text-gray-500'
          )}
        >
          재고 {product.stock_quantity.toLocaleString()} {product.unit}
        </p>
      </div>
    </button>
  );
}
