export type Ready = { status: string; checks: Record<string, string> };
export type SelfCheck = { worker: string; db_write: string; db_read: string; latency_ms: number };

async function request<T>(path: string, init?: RequestInit): Promise<{ status: number; data: T | null }> {
  const res = await fetch(path, {
    ...init,
    credentials: "same-origin",
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
  });
  const text = await res.text();
  return { status: res.status, data: text ? (JSON.parse(text) as T) : null };
}

export const api = {
  me: () => request<{ user: string }>("/api/auth/me"),
  login: (username: string, password: string, totp?: string) =>
    request<null>("/api/auth/login", {
      method: "POST",
      body: JSON.stringify({ username, password, totp: totp || null }),
    }),
  logout: () => request<null>("/api/auth/logout", { method: "POST" }),
  ready: () => request<Ready>("/api/health/ready"),
  selfcheck: () => request<SelfCheck>("/api/system/selfcheck", { method: "POST" }),
};
