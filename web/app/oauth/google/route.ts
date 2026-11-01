import { NextResponse, type NextRequest } from "next/server";
import { api, ApiError, type User } from "@/lib/api";
import { finishConnect } from "@/lib/connect-return";
import { LOGIN_NEXT_COOKIE, LOGIN_NONCE_COOKIE, SESSION_COOKIE, safeNext, sealSession, sessionCookieOptions } from "@/lib/session-token";

/** Google redirects to the dashboard root; proxy.ts rewrites that hit here. `state` says which flow it was:
 *  `login.…` signs in, `gmail.…` / `calendar.…` / `drive.…` connects that account. */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  const state = params.get("state") ?? "";
  return state.startsWith("login.") ? finishSignIn(request, params, state) : finishConnect(request, params, state, state.split(".")[0]);
}

const message = (e: unknown, fallback: string) => (e instanceof ApiError ? e.message : fallback);

async function finishSignIn(request: NextRequest, params: URLSearchParams, state: string) {
  const fail = (error: string) => {
    const res = NextResponse.redirect(new URL(`/login?error=${encodeURIComponent(error)}`, request.url));
    res.cookies.delete(LOGIN_NONCE_COOKIE);
    return res;
  };
  const code = params.get("code");
  const nonce = request.cookies.get(LOGIN_NONCE_COOKIE)?.value;
  if (!code) return fail(params.get("error") === "access_denied" ? "cancelled" : "Google sign-in didn't finish");
  if (!nonce) return fail("Your sign-in took too long. Please try again.");
  let user: User & { created: boolean };
  try {
    user = await api("/admin/auth/google/complete", { method: "POST", body: JSON.stringify({ code, state, nonce }) });
  } catch (e) {
    return fail(message(e, "Couldn't sign you in"));
  }
  const next = safeNext(request.cookies.get(LOGIN_NEXT_COOKIE)?.value);
  const res = NextResponse.redirect(new URL(next ?? (user.created ? "/welcome" : "/"), request.url));
  res.cookies.set(SESSION_COOKIE, await sealSession(user.id), sessionCookieOptions);
  res.cookies.delete(LOGIN_NONCE_COOKIE);
  res.cookies.delete(LOGIN_NEXT_COOKIE);
  return res;
}
