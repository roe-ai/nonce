import type { NextRequest } from "next/server";
import { finishConnect } from "@/lib/connect-return";

/** Slack redirects here ({DASHBOARD_URL}/oauth/slack) after the user approves Privato in their workspace. */
export async function GET(request: NextRequest) {
  const params = request.nextUrl.searchParams;
  return finishConnect(request, params, params.get("state") ?? "", "slack");
}
