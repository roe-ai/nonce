"use client";

import { Check, Plus, X } from "lucide-react";
import { useActionState, useState } from "react";
import { createAgent, type NewAgentState } from "@/app/actions";
import { CopyButton } from "@/components/live";
import { AppAvatar, KNOWN_APPS } from "@/components/ui";

const CHOICES = [
  ...["chatgpt", "claude", "gemini", "cursor", "copilot", "perplexity", "muse", "grok"].map((kind) => ({ kind, name: KNOWN_APPS[kind] })),
  { kind: "custom", name: "" },
];

function steps(kind: string, name: string): string {
  switch (kind) {
    case "chatgpt":
      return "In ChatGPT, open Settings → Apps & Connectors → Create. Paste this URL and choose OAuth.";
    case "claude":
      return "In Claude, open Settings → Connectors → Add custom connector and paste this URL.";
    case "cursor":
      return "In Cursor, open Settings → MCP → Add new MCP server and paste this URL.";
    default:
      return `Add this URL to ${name || "the app"} as a remote MCP server (connector).`;
  }
}

/** Pick an app and get the URL to paste into it (or, for apps that can't sign in, a key). `onDone` adds Done buttons. */
export function AppSetup({ mcpUrl, onDone }: { mcpUrl: string; onDone?: () => void }) {
  const [kind, setKind] = useState("chatgpt");
  const [state, action, pending] = useActionState<NewAgentState, FormData>(createAgent, null);
  const choice = CHOICES.find((c) => c.kind === kind)!;

  if (state?.key) {
    const config = JSON.stringify({ mcpServers: { nonce: { url: mcpUrl, headers: { Authorization: `Bearer ${state.key}` } } } }, null, 2);
    return (
      <div>
        <p className="flex items-center gap-2 text-muted">
          <Check size={15} className="text-emerald-600" /> Paste this into {state.name}&apos;s connector settings.
        </p>
        <div className="mt-4 rounded-lg border border-line bg-sidebar p-3">
          <div className="mb-2 flex items-center justify-between">
            <span className="text-[12px] font-medium text-muted">Connection settings</span>
            <CopyButton text={config} />
          </div>
          <pre className="overflow-x-auto font-mono text-[11px] leading-relaxed text-ink">{config}</pre>
        </div>
        <p className="mt-3 text-[12px] text-faint">This is shown once. If you lose it, just add the app again.</p>
        {onDone && (
          <button onClick={onDone} className="mt-5 h-9 w-full rounded-lg bg-ink text-[13px] font-medium text-white hover:bg-black">
            Done
          </button>
        )}
      </div>
    );
  }

  return (
    <form action={action}>
      <p className="mb-3 text-[13px] text-muted">Which app?</p>
      <div className="grid grid-cols-2 gap-2 sm:grid-cols-3">
        {CHOICES.map((c) => (
          <label
            key={c.kind}
            className={`flex cursor-pointer items-center gap-2.5 rounded-lg border p-2.5 transition-colors ${
              kind === c.kind ? "border-ink bg-sidebar" : "border-line hover:bg-sidebar"
            }`}
          >
            <input type="radio" name="kind" value={c.kind} checked={kind === c.kind} onChange={() => setKind(c.kind)} className="sr-only" />
            <AppAvatar kind={c.kind} name={c.name || "Other"} size={26} />
            <span className="truncate text-[13px] font-medium">{c.name || "Other app"}</span>
          </label>
        ))}
      </div>
      {kind === "custom" ? (
        <input
          name="name"
          placeholder="App name"
          autoFocus
          className="mt-3 h-9 w-full rounded-lg border border-line px-3 text-[13px] outline-none focus:border-ink"
        />
      ) : (
        <input type="hidden" name="name" value={choice.name} />
      )}
      <div className="mt-4 rounded-lg border border-line bg-sidebar p-3">
        <p className="text-[13px]">{steps(kind, choice.name)}</p>
        <div className="mt-2.5 flex items-center gap-2 rounded-md border border-line bg-white px-2.5 py-1.5">
          <code className="min-w-0 flex-1 truncate font-mono text-[12px]">{mcpUrl}</code>
          <CopyButton text={mcpUrl} />
        </div>
        <p className="mt-2.5 text-[12px] text-muted">It will open nonce so you can approve it. It starts with no access.</p>
      </div>
      {state?.error && <p className="mt-2 text-[12px] text-red-600">{state.error}</p>}
      {onDone && (
        <button type="button" onClick={onDone} className="mt-4 h-9 w-full rounded-lg bg-ink text-[13px] font-medium text-white hover:bg-black">
          Done
        </button>
      )}
      <button disabled={pending} className="mt-2 w-full text-center text-[12px] text-faint hover:text-ink disabled:opacity-50">
        {pending ? "Creating a key…" : "App can’t sign in? Use a key instead"}
      </button>
    </form>
  );
}

export function AddApp({ mcpUrl }: { mcpUrl: string }) {
  const [open, setOpen] = useState(false);

  if (!open) {
    return (
      <button
        onClick={() => setOpen(true)}
        className="inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg bg-ink px-3 text-[13px] font-medium whitespace-nowrap text-white shadow-sm hover:bg-black"
      >
        <Plus size={14} /> Add an app
      </button>
    );
  }

  return (
    <div className="fixed inset-0 z-50 grid place-items-center bg-black/20 p-4 backdrop-blur-[2px]" onClick={() => setOpen(false)}>
      <div className="w-full max-w-md rounded-2xl border border-line bg-white p-6 shadow-xl" onClick={(e) => e.stopPropagation()}>
        <div className="mb-5 flex items-center justify-between">
          <h2 className="text-[16px] font-semibold">Add an AI app</h2>
          <button onClick={() => setOpen(false)} className="text-faint hover:text-ink" aria-label="Close">
            <X size={16} />
          </button>
        </div>
        <AppSetup mcpUrl={mcpUrl} onDone={() => setOpen(false)} />
      </div>
    </div>
  );
}
