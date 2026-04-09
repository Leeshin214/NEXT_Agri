'use client';

import { useQuery } from '@tanstack/react-query';
import { api } from '@/lib/api';
import type { UserPublicProfile } from '@/types';
import type { SuccessResponse } from '@/types';

interface MemberFilters {
  search?: string;
  page?: number;
  limit?: number;
  role?: string;
}

export function useMembers(filters?: MemberFilters) {
  return useQuery({
    queryKey: ['members', filters],
    queryFn: () =>
      api.get<SuccessResponse<UserPublicProfile[]>>(
        '/users/search',
        filters as Record<string, unknown>
      ),
  });
}

export function useMemberProfile(userId: string | null) {
  return useQuery({
    queryKey: ['memberProfile', userId],
    queryFn: () =>
      api.get<SuccessResponse<UserPublicProfile>>(`/users/${userId}/profile`),
    enabled: !!userId,
  });
}
