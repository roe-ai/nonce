import { NextResponse, type NextRequest } from "next/server";
import { openSession, SESSION_COOKIE } from "./lib/session-token";

export async function proxy(request: NextRequest) {
  const { pathname, searchParams } = request.nextUrl;
  // Google's OAuth client redirects to the site root, both for signing in and for connecting Gmail.
  if (pathname === "/" && searchParams.has("state") && (searchParams.has("code") || searchParams.has("error"))) {
    const url = request.nextUrl.clone();
    url.pathname = "/oauth/google";
    return NextResponse.rewrite(url);
  }
  if (!(await openSession(request.cookies.get(SESSION_COOKIE)?.value))) {
    const login = new URL("/login", request.url);
    if (pathname !== "/") login.searchParams.set("next", `${pathname}${request.nextUrl.search}`);
    return NextResponse.redirect(login);
  }
  return NextResponse.next();
}

export const config = {
  // Everything except the login page, the OAuth return, Next internals and static files.
  matcher: ["/((?!login|oauth/google|_next/static|_next/image|.*\\.[a-z0-9]+$).*)"],
};
