/** Signed session cookies: `<userId>.<expiresAt>.<hmac>`. Web Crypto only, so proxy.ts can use it too. */

export const SESSION_COOKIE = "privato_session";
export const LOGIN_NONCE_COOKIE = "privato_login";
export const LOGIN_NEXT_COOKIE = "privato_next";
/** Where to land after connecting an account, when it isn't Accounts (e.g. the setup guide). */
export const CONNECT_BACK_COOKIE = "privato_connect_back";

/** Only same-site paths, so a crafted link can't bounce a fresh login to another site. */
export function safeNext(next: string | null | undefined): string | null {
  return next && next.startsWith("/") && !next.startsWith("//") && !next.startsWith("/\\") ? next : null;
}
export const SESSION_MAX_AGE_S = 60 * 60 * 24 * 30;

async function hmac(message: string): Promise<string> {
  const secret = process.env.PRIVATO_SESSION_SECRET || process.env.NONCE_SESSION_SECRET || process.env.PRIVATY_SESSION_SECRET || process.env.PRIVATO_ADMIN_TOKEN || process.env.NONCE_ADMIN_TOKEN || process.env.PRIVATY_ADMIN_TOKEN;
  if (!secret) throw new Error("Set PRIVATO_SESSION_SECRET (or PRIVATO_ADMIN_TOKEN) to sign sessions");
  const key = await crypto.subtle.importKey("raw", new TextEncoder().encode(`privato-session:${secret}`), { name: "HMAC", hash: "SHA-256" }, false, ["sign"]);
  const sig = await crypto.subtle.sign("HMAC", key, new TextEncoder().encode(message));
  return Array.from(new Uint8Array(sig), (b) => b.toString(16).padStart(2, "0")).join("");
}

function sameString(a: string, b: string): boolean {
  if (a.length !== b.length) return false;
  let diff = 0;
  for (let i = 0; i < a.length; i++) diff |= a.charCodeAt(i) ^ b.charCodeAt(i);
  return diff === 0;
}

export async function sealSession(userId: string): Promise<string> {
  const payload = `${userId}.${Math.floor(Date.now() / 1000) + SESSION_MAX_AGE_S}`;
  return `${payload}.${await hmac(payload)}`;
}

export async function openSession(value: string | undefined): Promise<string | null> {
  const [userId, expires, sig] = value?.split(".") ?? [];
  if (!userId || !expires || !sig || Number(expires) * 1000 < Date.now()) return null;
  return sameString(sig, await hmac(`${userId}.${expires}`)) ? userId : null;
}

export const sessionCookieOptions = {
  httpOnly: true,
  sameSite: "lax" as const,
  secure: process.env.NODE_ENV === "production",
  path: "/",
  maxAge: SESSION_MAX_AGE_S,
};
