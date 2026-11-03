import { ArrowLeftRight, BellRing, KeyRound, ListChecks } from "lucide-react";
import { decideConnection } from "@/app/actions";
import { api, ApiError, type User } from "@/lib/api";
import { requireUser } from "@/lib/session";
import { AppAvatar, BrandMark } from "@/components/ui";

interface ConnectRequest {
  client_name: string;
  kind: string;
  redirect_host: string | null;
}

export default async function ConnectPage({ searchParams }: { searchParams: Promise<{ request?: string }> }) {
  await requireUser();
  const { request: requestId } = await searchParams;
  const me = await api<User>("/admin/me");
  const request = requestId
    ? await api<ConnectRequest>(`/admin/oauth/requests/${encodeURIComponent(requestId)}`).catch((e) => {
        if (e instanceof ApiError && e.status < 500) return null;
        throw e;
      })
    : null;

  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-[380px]">
        {!request || !requestId ? (
          <div className="text-center">
            <BrandMark height={24} className="mx-auto mb-6" />
            <h1 className="text-[18px] font-semibold">This link has expired</h1>
            <p className="mt-1.5 text-[13px] text-muted">Go back to the app and connect Privato again. Links only last a few minutes.</p>
          </div>
        ) : (
          <>
            <div className="mb-6 flex items-center justify-center gap-3">
              <AppAvatar kind={request.kind} name={request.client_name} size={48} />
              <ArrowLeftRight size={16} className="text-faint" />
              <span className="grid size-12 place-items-center rounded-lg border border-line bg-white">
                <BrandMark height={22} />
              </span>
            </div>
            <h1 className="text-center text-[18px] font-semibold tracking-[-0.01em]">Connect {request.client_name} to Privato?</h1>
            <p className="mt-1.5 text-center text-[13px] text-muted">
              Signed in as <span className="text-ink">{me.email}</span>
            </p>

            <ul className="mt-6 space-y-3 rounded-xl border border-line bg-white p-4 text-[13px]">
              <li className="flex gap-3">
                <ListChecks size={16} className="mt-0.5 shrink-0 text-muted" />
                <span>It starts with no access. It can ask to look at specific emails, events, files or messages when you ask it for help.</span>
              </li>
              <li className="flex gap-3">
                <BellRing size={16} className="mt-0.5 shrink-0 text-muted" />
                <span>Privato checks every request and asks you first when something looks off.</span>
              </li>
              <li className="flex gap-3">
                <KeyRound size={16} className="mt-0.5 shrink-0 text-muted" />
                <span>It never gets your Google password. Remove it any time from AI apps.</span>
              </li>
            </ul>

            <div className="mt-5 grid grid-cols-2 gap-2">
              <form action={decideConnection.bind(null, requestId, "deny")}>
                <button className="h-10 w-full rounded-lg border border-line bg-white text-[14px] font-medium hover:bg-sidebar">Cancel</button>
              </form>
              <form action={decideConnection.bind(null, requestId, "approve")}>
                <button className="h-10 w-full rounded-lg bg-ink text-[14px] font-medium text-white hover:bg-black">Allow</button>
              </form>
            </div>
            {request.redirect_host && (
              <p className="mt-4 text-center text-[12px] text-faint">You&apos;ll be sent back to {request.redirect_host}.</p>
            )}
          </>
        )}
      </div>
    </div>
  );
}
