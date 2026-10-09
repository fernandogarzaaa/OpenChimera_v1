// src/dashboard/api/bridge.ts

export type ApiError = {
  status: number;
  message: string;
  details?: any;
};

export type ApiResponse<T> = {
  data: T | null;
  error: ApiError | null;
  loading: boolean;
};

export type Session = {
  id: string;
  user: string;
  createdAt: string;
  active: boolean;
};

export type Agent = {
  id: string;
  name: string;
  status: string;
  sessionId: string;
};

export type Model = {
  id: string;
  name: string;
  hardware: string;
  status: string;
};

const API_BASE = '/api';

function getAuthToken(): string | null {
  return localStorage.getItem('chimera_token');
}

function setAuthToken(token: string) {
  localStorage.setItem('chimera_token', token);
}

function clearAuthToken() {
  localStorage.removeItem('chimera_token');
}

async function apiFetch<T>(
  path: string,
  options: RequestInit = {},
  requireAuth = true
): Promise<ApiResponse<T>> {
  const headers: Record<string, string> = {
    'Content-Type': 'application/json',
    ...options.headers,
  };
  if (requireAuth) {
    const token = getAuthToken();
    if (token) headers['Authorization'] = `Bearer ${token}`;
  }
  let loading = true;
  try {
    const res = await fetch(`${API_BASE}${path}`, {
      ...options,
      headers,
    });
    loading = false;
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      return {
        data: null,
        error: {
          status: res.status,
          message: err.message || res.statusText,
          details: err,
        },
        loading,
      };
    }
    const data = await res.json();
    return { data, error: null, loading };
  } catch (e: any) {
    loading = false;
    return {
      data: null,
      error: {
        status: 0,
        message: e.message || 'Network error',
      },
      loading,
    };
  }
}

// --- API Methods ---

export async function login(username: string, password: string) {
  const res = await apiFetch<{ token: string }>('/auth/login', {
    method: 'POST',
    body: JSON.stringify({ username, password }),
  }, false);
  if (res.data?.token) setAuthToken(res.data.token);
  return res;
}

export function logout() {
  clearAuthToken();
}

export async function getSessions() {
  const res = await apiFetch<Session[]>('/sessions');
  // Normalize: sort by createdAt desc
  if (res.data) {
    res.data = res.data.sort((a, b) => b.createdAt.localeCompare(a.createdAt));
  }
  return res;
}

export async function getAgents(sessionId?: string) {
  const path = sessionId ? `/agents?session=${sessionId}` : '/agents';
  const res = await apiFetch<Agent[]>(path);
  // Normalize: group by sessionId
  if (res.data) {
    res.data = res.data.map(agent => ({
      ...agent,
      status: agent.status.toLowerCase(),
    }));
  }
  return res;
}

export async function getModels() {
  const res = await apiFetch<Model[]>('/models');
  // Normalize: sort by name
  if (res.data) {
    res.data = res.data.sort((a, b) => a.name.localeCompare(b.name));
  }
  return res;
}

// Add more API methods as needed (startAgent, stopAgent, etc.)
