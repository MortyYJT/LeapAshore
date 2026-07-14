export type ApiMode = "fastapi" | "demo-fallback";

export type ApiHistoryItem = {
  run_id: string;
  created_at: string;
  workflow_version: string;
  target_field: string;
  intake: string;
  recommendation_count: number;
  summary: string;
};

export type ApiActionItem = {
  id: string;
  title: string;
  detail: string;
  priority: "P0" | "P1" | "P2";
  status: "待开始" | "进行中" | "已完成";
};

export type ApiAgentRun = {
  run_id: string;
  workflow_version: string;
  agent_mode: "deterministic-demo" | "llm-assisted";
  summary: string;
};

type LoginResponse = {
  access_token: string;
};

// Same-origin is the production default; Sites gracefully falls back when /api is absent.
const API_URL = (process.env.NEXT_PUBLIC_API_URL ?? "/api").replace(/\/$/, "");

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_URL}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...init?.headers },
  });
  if (!response.ok) {
    const body = await response.json().catch(() => null) as { detail?: string } | null;
    throw new Error(body?.detail ?? `API request failed: ${response.status}`);
  }
  return response.json() as Promise<T>;
}

export async function loginWithDemoAccount(email: string, password: string): Promise<string> {
  const response = await request<LoginResponse>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ email, password }),
  });
  return response.access_token;
}

export async function saveProfile(token: string, profile: Record<string, unknown>): Promise<void> {
  await request("/me/profile", {
    method: "PUT",
    headers: { Authorization: `Bearer ${token}` },
    body: JSON.stringify(profile),
  });
}

export async function createAgentRun(token: string): Promise<ApiAgentRun> {
  return request<ApiAgentRun>("/me/recommendation-runs", {
    method: "POST",
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function fetchHistory(token: string): Promise<ApiHistoryItem[]> {
  return request<ApiHistoryItem[]>("/me/recommendation-runs", {
    headers: { Authorization: `Bearer ${token}` },
  });
}

export async function fetchActionPlan(token: string, runId: string): Promise<ApiActionItem[]> {
  const response = await request<{ items: ApiActionItem[] }>(`/me/recommendation-runs/${runId}/action-plan`, {
    headers: { Authorization: `Bearer ${token}` },
  });
  return response.items;
}
