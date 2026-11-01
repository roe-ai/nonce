import { sessionUserId } from "./session";

const API_URL = process.env.NONCE_API_URL ?? process.env.PRIVATY_API_URL ?? "http://localhost:8000";

export type Signals = Record<string, number | string | boolean | string[]>;

export type SourceId = "gmail" | "calendar" | "drive" | "slack";
export type ModeName = "cautious" | "standard" | "relaxed";

export interface Overview {
  active_grants: number;
  pending: number;
  events_24h: number;
  blocked_24h: number;
  open_alerts: number;
  agents: number;
  connections: number;
}

export interface Agent {
  id: string;
  name: string;
  kind: string;
  key_prefix: string;
  status: string;
  mode: ModeName;
  created_at: number;
  last_seen_at: number | null;
  active_grants: number;
  blocked: number;
}

export interface Connection {
  id: string;
  provider: SourceId;
  mode: "google" | "slack";
  account: string;
  status: "active" | "paused";
  created_at: number;
}

export type ToolRule = "auto" | "ask" | "off";

export interface ConnectorTool {
  name: string;
  description: string;
  read_only: boolean;
  suspicious: boolean;
  rule: ToolRule;
}

/** An MCP server or HTTP API the user added; nonce holds its key and makes every call. */
export interface Connector {
  id: string;
  source: string;
  name: string;
  kind: "mcp" | "http";
  url: string;
  auth_header: string | null;
  status: "active" | "paused";
  tools: ConnectorTool[];
  error: string | null;
  created_at: number;
  updated_at: number;
}

export interface Grant {
  id: string;
  agent_id: string;
  agent_name: string;
  agent_kind: string;
  source: string;
  account: string | null;
  /** The accounts it reads; null means every active account of its kind. */
  account_ids?: string[] | null;
  status: "pending" | "active" | "denied" | "revoked" | "expired";
  scopes: string[];
  query_constraint: string;
  justification: string;
  user_request: string;
  category: string | null;
  ttl_s: number;
  max_calls: number;
  calls_used: number;
  decided_by: string | null;
  reason: string | null;
  signals: Signals | null;
  created_at: number;
  activated_at: number | null;
  expires_at: number | null;
  ended_at: number | null;
  task_id: string | null;
  task_title: string | null;
}

/** Pending requests an app made for one task; one answer covers them all. */
export interface RequestGroup {
  id: string;
  title: string | null;
  grants: Grant[];
}

export interface AccessEvent {
  id: string;
  ts: number;
  agent_id: string | null;
  agent_name: string | null;
  agent_kind: string | null;
  grant_id: string | null;
  user_request: string | null;
  query_constraint: string | null;
  source: string | null;
  account: string | null;
  task_id: string | null;
  task_title: string | null;
  action: string;
  decision: string;
  reason: string | null;
  detail: Record<string, unknown>;
  signals: Signals | null;
  latency_ms: number | null;
}

export interface Alert {
  id: string;
  ts: number;
  agent_id: string | null;
  agent_name: string | null;
  grant_id: string | null;
  grant_status: string | null;
  severity: "info" | "warning" | "critical";
  kind: string;
  title: string;
  body: string | null;
  needs_approval: number;
  status: "open" | "resolved";
}

export interface User {
  id: string;
  email: string;
  name: string | null;
  picture: string | null;
  phone: string | null;
  phone_verified_at: number | null;
  offline_start: number;
  offline_end: number;
  timezone: string;
  created_at: number;
}

export interface ModePreview {
  days: number;
  requests: number;
  modes: Record<ModeName, { allow: number; ask: number; deny: number }>;
}

export interface DailyActivity {
  today: string;
  days: { day: string; total: number; blocked: number; asked: number }[];
}

export class ApiError extends Error {
  constructor(
    public status: number,
    message: string,
  ) {
    super(message);
  }
}

/** Server-side only: carries the admin token, which never reaches the browser, and names the signed-in user. */
export async function api<T>(path: string, init: RequestInit = {}): Promise<T> {
  const userId = await sessionUserId();
  const res = await fetch(`${API_URL}${path}`, {
    ...init,
    cache: "no-store",
    headers: {
      "content-type": "application/json",
      authorization: `Bearer ${process.env.NONCE_ADMIN_TOKEN ?? process.env.PRIVATY_ADMIN_TOKEN ?? ""}`,
      ...(userId ? { "x-nonce-user": userId } : {}),
      ...init.headers,
    },
  });
  if (!res.ok) {
    const body = await res.json().catch(() => ({}));
    throw new ApiError(res.status, body.message ?? res.statusText);
  }
  return res.json() as Promise<T>;
}

export const apiUrl = API_URL;
/** The address AI apps connect to; the public API address when the dashboard reaches the API privately. */
export const mcpUrl = `${process.env.NONCE_PUBLIC_API_URL ?? process.env.PRIVATY_PUBLIC_API_URL ?? API_URL}/mcp`;
