import { cookies } from "next/headers";
import { openSession, SESSION_COOKIE } from "./session-token";

export async function sessionUserId(): Promise<string | null> {
  return openSession((await cookies()).get(SESSION_COOKIE)?.value);
}

/** Server Actions are reachable without the proxy, so each one checks the session itself. */
export async function requireUser(): Promise<string> {
  const id = await sessionUserId();
  if (!id) throw new Error("Unauthorized");
  return id;
}
