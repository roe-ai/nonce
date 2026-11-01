"use server";

import { refresh } from "next/cache";
import { cookies } from "next/headers";
import { redirect } from "next/navigation";
import { api, ApiError, type ModeName, type ModePreview, type SourceId, type ToolRule } from "@/lib/api";
import { requireUser } from "@/lib/session";
import { CONNECT_BACK_COOKIE, LOGIN_NEXT_COOKIE, LOGIN_NONCE_COOKIE, safeNext, SESSION_COOKIE } from "@/lib/session-token";

export async function grantAction(grantId: string, action: "approve" | "deny" | "revoke") {
  await requireUser();
  await api(`/admin/grants/${grantId}/${action}`, { method: "POST" });
  refresh();
}

export async function groupAction(grantIds: string[], action: "approve" | "deny" | "revoke") {
  await requireUser();
  await api(`/admin/requests/${action}`, { method: "POST", body: JSON.stringify({ grant_ids: grantIds }) });
  refresh();
}

export interface PushSubscriptionJSON {
  endpoint: string;
  keys: { p256dh: string; auth: string };
}

export async function addPushDevice(sub: PushSubscriptionJSON, device: string): Promise<string | null> {
  await requireUser();
  try {
    await api("/admin/push", { method: "POST", body: JSON.stringify({ endpoint: sub.endpoint, keys: sub.keys, device }) });
    return null;
  } catch (e) {
    return e instanceof ApiError ? e.message : "Couldn't turn on notifications. Try again.";
  }
}

export async function removePushDevice(endpoint: string): Promise<void> {
  await requireUser();
  await api("/admin/push/remove", { method: "POST", body: JSON.stringify({ endpoint }) });
}

export async function sendTestPush(): Promise<number> {
  await requireUser();
  return (await api<{ sent: number }>("/admin/push/test", { method: "POST" })).sent;
}

export async function resolveAlert(alertId: string) {
  await requireUser();
  await api(`/admin/alerts/${alertId}/resolve`, { method: "POST" });
  refresh();
}

export type NewAgentState = { key?: string; name?: string; error?: string } | null;

export async function createAgent(_: NewAgentState, form: FormData): Promise<NewAgentState> {
  await requireUser();
  const name = String(form.get("name") ?? "").trim();
  const kind = String(form.get("kind") ?? "custom");
  if (!name) return { error: "Give the agent a name" };
  const res = await api<{ key: string; name: string }>("/admin/agents", {
    method: "POST",
    body: JSON.stringify({ name, kind }),
  });
  refresh();
  return { key: res.key, name: res.name };
}

export async function disableAgent(agentId: string) {
  await requireUser();
  await api(`/admin/agents/${agentId}/disable`, { method: "POST" });
  refresh();
}

export async function connectAccount(provider: SourceId, another = false, back?: string): Promise<{ error: string } | void> {
  await requireUser();
  let url: string;
  try {
    url = (await api<{ url: string }>(`/admin/connections/${provider}/connect${another ? "?another=true" : ""}`)).url;
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Could not start sign-in" };
  }
  const jar = await cookies();
  const to = safeNext(back);
  if (to) jar.set(CONNECT_BACK_COOKIE, to, { httpOnly: true, sameSite: "lax", secure: process.env.NODE_ENV === "production", path: "/", maxAge: 900 });
  else jar.delete(CONNECT_BACK_COOKIE);
  redirect(url);
}

export async function setAppMode(agentId: string, mode: ModeName) {
  await requireUser();
  await api(`/admin/agents/${agentId}`, { method: "PATCH", body: JSON.stringify({ mode }) });
  refresh();
}

export async function previewModes(agentId: string): Promise<ModePreview> {
  await requireUser();
  return api<ModePreview>(`/admin/agents/${agentId}/modes`);
}

export async function setOfflineHours(start: number, end: number, timezone: string) {
  await requireUser();
  await api("/admin/me/offline", { method: "PUT", body: JSON.stringify({ start, end, timezone }) });
  refresh();
}

export async function removeConnection(connectionId: string) {
  await requireUser();
  await api(`/admin/connections/${connectionId}`, { method: "DELETE" });
  refresh();
}

export async function chooseAccounts(grantId: string, connectionIds: string[]) {
  await requireUser();
  await api(`/admin/grants/${grantId}/accounts`, { method: "PUT", body: JSON.stringify({ connection_ids: connectionIds }) });
  refresh();
}

export async function pauseAccount(connectionId: string, pause: boolean) {
  await requireUser();
  await api(`/admin/connections/${connectionId}/${pause ? "pause" : "resume"}`, { method: "POST" });
  refresh();
}

export type ConnectorFormState = { error?: string; added?: string } | null;

export async function addConnector(_: ConnectorFormState, form: FormData): Promise<ConnectorFormState> {
  await requireUser();
  const field = (k: string) => String(form.get(k) ?? "").trim();
  const header = field("auth_header");
  const value = String(form.get("auth_value") ?? "");
  if (!field("name") || !field("url")) return { error: "Give it a name and a URL" };
  try {
    const res = await api<{ name: string }>("/admin/connectors", {
      method: "POST",
      body: JSON.stringify({
        name: field("name"),
        kind: field("kind") === "http" ? "http" : "mcp",
        url: field("url"),
        auth_header: value ? header || "Authorization" : null,
        auth_value: value || null,
      }),
    });
    refresh();
    return { added: res.name };
  } catch (e) {
    return { error: e instanceof ApiError ? e.message : "Couldn't add that connector" };
  }
}

export async function refreshConnector(connectorId: string): Promise<void> {
  await requireUser();
  await api(`/admin/connectors/${connectorId}/refresh`, { method: "POST" }).catch(() => null);
  refresh();
}

export async function setToolRule(connectorId: string, tool: string, rule: ToolRule) {
  await requireUser();
  await api(`/admin/connectors/${connectorId}/tools/${encodeURIComponent(tool)}`, { method: "PUT", body: JSON.stringify({ rule }) });
  refresh();
}

export async function pauseConnector(connectorId: string, pause: boolean) {
  await requireUser();
  await api(`/admin/connectors/${connectorId}/${pause ? "pause" : "resume"}`, { method: "POST" });
  refresh();
}

export async function removeConnector(connectorId: string) {
  await requireUser();
  await api(`/admin/connectors/${connectorId}`, { method: "DELETE" });
  refresh();
}

export async function signInWithGoogle(form: FormData): Promise<void> {
  const nonce = crypto.randomUUID().replaceAll("-", "");
  const { url } = await api<{ url: string }>(`/admin/auth/google?nonce=${nonce}`);
  const jar = await cookies();
  const short = { httpOnly: true, sameSite: "lax" as const, secure: process.env.NODE_ENV === "production", path: "/", maxAge: 15 * 60 };
  jar.set(LOGIN_NONCE_COOKIE, nonce, short);
  const next = safeNext(String(form.get("next") ?? ""));
  if (next) jar.set(LOGIN_NEXT_COOKIE, next, short);
  else jar.delete(LOGIN_NEXT_COOKIE);
  redirect(url);
}

export async function decideConnection(requestId: string, decision: "approve" | "deny"): Promise<void> {
  await requireUser();
  const { redirect_to } = await api<{ redirect_to: string }>(`/admin/oauth/requests/${encodeURIComponent(requestId)}/${decision}`, {
    method: "POST",
  });
  redirect(redirect_to);
}

export async function signOut(): Promise<void> {
  (await cookies()).delete(SESSION_COOKIE);
  redirect("/login");
}

export type PhoneState = { step: "number" | "code" | "done"; phone?: string; error?: string };

export async function sendPhoneCode(_: PhoneState, form: FormData): Promise<PhoneState> {
  await requireUser();
  const phone = String(form.get("phone") ?? "");
  try {
    const res = await api<{ phone: string }>("/admin/me/phone", { method: "POST", body: JSON.stringify({ phone }) });
    return { step: "code", phone: res.phone };
  } catch (e) {
    return { step: "number", phone, error: e instanceof ApiError ? e.message : "Couldn't send the code" };
  }
}

export async function verifyPhoneCode(prev: PhoneState, form: FormData): Promise<PhoneState> {
  await requireUser();
  if (form.get("intent") === "resend") return sendPhoneCode(prev, form);
  try {
    await api("/admin/me/phone/verify", { method: "POST", body: JSON.stringify({ code: String(form.get("code") ?? "") }) });
  } catch (e) {
    return { ...prev, error: e instanceof ApiError ? e.message : "That code didn't work" };
  }
  refresh();
  return { step: "done" };
}

export async function removePhone() {
  await requireUser();
  await api("/admin/me/phone", { method: "DELETE" });
  refresh();
}
