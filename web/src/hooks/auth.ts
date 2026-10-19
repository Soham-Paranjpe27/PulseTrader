'use client';

import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query';
import { ApiError, get, post } from '@/lib/api';
import type { LoginInput, RegisterInput } from '@/lib/schemas';
import type { User } from '@/lib/types';

export const ME_KEY = ['me'] as const;

/** Current user, or null when signed out (401 is an answer here, not an error). */
export function useMe() {
  return useQuery({
    queryKey: ME_KEY,
    queryFn: async (): Promise<User | null> => {
      try {
        return (await get<{ user: User }>('/auth/me')).user;
      } catch (e) {
        if (e instanceof ApiError && e.status === 401) return null;
        throw e;
      }
    },
    staleTime: 60_000,
    retry: false,
  });
}

export function useLogin() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: (v: LoginInput) => post<{ user: User }>('/auth/login', v),
    onSuccess: (r) => {
      qc.clear();
      qc.setQueryData(ME_KEY, r.user);
    },
  });
}

export function useRegister() {
  return useMutation({
    mutationFn: (v: RegisterInput) =>
      post<{ user: User }>('/auth/register', {
        email: v.email,
        password: v.password,
        ...(v.name ? { name: v.name } : {}),
      }),
  });
}

export function useLogout() {
  const qc = useQueryClient();
  return useMutation({
    mutationFn: () => post<{ ok: boolean }>('/auth/logout'),
    onSettled: () => {
      qc.clear();
      qc.setQueryData(ME_KEY, null);
    },
  });
}
