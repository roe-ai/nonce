"use client";

import { useActionState } from "react";
import { connectAccount } from "@/app/actions";
import type { SourceId } from "@/lib/api";

/** Starts Google or Slack sign-in. `another` adds a second account of the same kind; `back` is where to land afterwards;
 *  `short` says just "Connect" when the row already names the account. */
export function ConnectAccountButton({
  provider,
  label,
  another = false,
  back,
  short = false,
}: {
  provider: SourceId;
  label: string;
  another?: boolean;
  back?: string;
  short?: boolean;
}) {
  const [state, action, pending] = useActionState(async () => (await connectAccount(provider, another, back)) ?? null, null);
  const by = provider === "slack" ? "Slack" : "Google";
  return (
    <form action={action} className="flex flex-col items-end gap-1.5">
      <button
        disabled={pending}
        className={`inline-flex h-9 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium whitespace-nowrap disabled:opacity-50 ${
          another ? "border border-line bg-white text-ink hover:bg-sidebar" : "bg-ink text-white shadow-sm hover:bg-black"
        }`}
      >
        {pending ? `Opening ${by}…` : another ? `+ Add ${provider === "slack" ? "workspace" : "account"}` : short ? "Connect" : `Connect ${label}`}
      </button>
      {state?.error && <p className="max-w-56 text-right text-[12px] text-red-600">{label} sign-in isn&apos;t set up on this server yet.</p>}
    </form>
  );
}
