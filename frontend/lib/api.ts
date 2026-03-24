import { createClient } from '@/lib/supabase/client';

const BASE_URL = process.env.NEXT_PUBLIC_API_URL || 'http://localhost:8000';

async function getAuthHeader(): Promise<Record<string, string>> {
  const supabase = createClient();
  const { data } = await supabase.auth.getSession();
  return data.session?.access_token
    ? { Authorization: `Bearer ${data.session.access_token}` }
    : {};
}

async function request<T>(
  path: string,
  options: RequestInit = {}
): Promise<T> {
  const authHeader = await getAuthHeader();
  const res = await fetch(`${BASE_URL}/api/v1${path}`, {
    ...options,
    headers: {
      'Content-Type': 'application/json',
      ...authHeader,
      ...options.headers,
    },
  });

  if (!res.ok) {
    const error = await res.json().catch(() => ({ error: res.statusText }));
    throw new Error(error.error || res.statusText);
  }

  if (res.status === 204) return undefined as T;
  return res.json();
}

export const api = {
  get<T>(path: string, params?: Record<string, unknown>): Promise<T> {
    let url = path;
    if (params) {
      const searchParams = new URLSearchParams();
      Object.entries(params).forEach(([k, v]) => {
        if (v != null) searchParams.set(k, String(v));
      });
      const qs = searchParams.toString();
      if (qs) url += `?${qs}`;
    }
    return request<T>(url);
  },

  post<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'POST',
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  patch<T>(path: string, body?: unknown): Promise<T> {
    return request<T>(path, {
      method: 'PATCH',
      body: body ? JSON.stringify(body) : undefined,
    });
  },

  delete<T>(path: string): Promise<T> {
    return request<T>(path, { method: 'DELETE' });
  },
};
