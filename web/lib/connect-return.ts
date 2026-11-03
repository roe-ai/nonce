import { NextResponse, type NextRequest } from "next/server";
import { api, ApiError } from "@/lib/api";
import { sessionUserId } from "@/lib/session";
import { CONNECT_BACK_COOKIE, safeNext } from "@/lib/session-token";

/** Where Google and Slack send the user back after connecting an account: hand the code to the API, then go
 *  back where the connection started (Accounts, or the setup guide). */
export async function finishConnect(request: NextRequest, params: URLSearchParams, state: string, provider: string) {
  if (!(await sessionUserId())) return NextResponse.redirect(new URL("/login", request.url));
  const back = new URL(safeNext(request.cookies.get(CONNECT_BACK_COOKIE)?.value) ?? "/accounts", request.url);
  const go = () => {
    const res = NextResponse.redirect(back);
    res.cookies.delete(CONNECT_BACK_COOKIE);
    return res;
  };
  const code = params.get("code");
  if (!["gmail", "calendar", "drive", "slack"].includes(provider)) {
    back.searchParams.set("error", "That sign-in link wasn't for Privato.");
    return go();
  }
  if (!code) {
    back.searchParams.set("error", params.get("error") ?? "cancelled");
    back.searchParams.set("source", provider);
    return go();
  }
  try {
    await api(`/admin/connections/${provider}/complete`, { method: "POST", body: JSON.stringify({ code, state }) });
    back.searchParams.set("connected", provider);
  } catch (e) {
    back.searchParams.set("error", e instanceof ApiError ? e.message : "Could not connect that account");
  }
  return go();
}
