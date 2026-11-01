"use client";

import { Plus } from "lucide-react";
import { useActionState, useState } from "react";
import { addConnector, type ConnectorFormState } from "@/app/actions";

const input =
  "h-11 w-full rounded-lg border border-line bg-white px-3 text-[15px] outline-none placeholder:text-faint focus:border-ink/40 sm:h-9 sm:text-[14px]";

/** Add an MCP server or HTTP API. nonce connects right away to list its tools. */
export function ConnectorForm() {
  const [open, setOpen] = useState(false);
  const [kind, setKind] = useState<"mcp" | "http">("mcp");
  const [state, action, pending] = useActionState<ConnectorFormState, FormData>(async (prev, form) => {
    const res = await addConnector(prev, form);
    if (res?.added) setOpen(false);
    return res;
  }, null);

  if (!open) {
    return (
      <div className="space-y-2">
        {state?.added && <p className="text-[13px] text-emerald-700">{state.added} is connected. Pick what each tool may do below.</p>}
        <button
          onClick={() => setOpen(true)}
          className="flex h-12 w-full items-center justify-center gap-2 rounded-xl border border-dashed border-line bg-white/60 text-[14px] font-medium text-ink hover:bg-white"
        >
          <Plus size={16} /> Add a connector
        </button>
      </div>
    );
  }

  return (
    <form action={action} className="space-y-4 rounded-xl border border-line bg-white p-4">
      <div className="grid grid-cols-2 gap-1 rounded-lg bg-sidebar p-1" role="radiogroup" aria-label="Type">
        {(
          [
            ["mcp", "MCP server"],
            ["http", "HTTP API"],
          ] as const
        ).map(([k, label]) => (
          <button
            key={k}
            type="button"
            role="radio"
            aria-checked={kind === k}
            onClick={() => setKind(k)}
            className={`h-9 rounded-md text-[13px] font-medium ${kind === k ? "bg-white text-ink shadow-sm" : "text-muted"}`}
          >
            {label}
          </button>
        ))}
      </div>
      <input type="hidden" name="kind" value={kind} />

      <label className="block space-y-1.5">
        <span className="text-[13px] font-medium">Name</span>
        <input name="name" required maxLength={60} placeholder={kind === "mcp" ? "Notion, Linear, my notes…" : "My shop's API"} className={input} />
      </label>
      <label className="block space-y-1.5">
        <span className="text-[13px] font-medium">{kind === "mcp" ? "Server URL" : "Base URL"}</span>
        <input
          name="url"
          type="url"
          required
          inputMode="url"
          autoCapitalize="off"
          autoCorrect="off"
          placeholder={kind === "mcp" ? "https://example.com/mcp" : "https://api.example.com/v1"}
          className={input}
        />
      </label>
      <div className="grid grid-cols-1 gap-3 sm:grid-cols-[1fr_1.4fr]">
        <label className="block space-y-1.5">
          <span className="text-[13px] font-medium">Header</span>
          <input name="auth_header" placeholder="Authorization" autoCapitalize="off" autoCorrect="off" className={input} />
        </label>
        <label className="block space-y-1.5">
          <span className="text-[13px] font-medium">Key or token</span>
          <input name="auth_value" type="password" autoComplete="off" placeholder="Bearer sk-… (optional)" className={input} />
        </label>
      </div>
      <p className="text-[12px] text-faint">
        nonce keeps the key encrypted and makes every call itself. AI apps never see it, and only reach this connector through your approvals.
      </p>
      {state?.error && <p className="text-[13px] text-red-600">{state.error}</p>}
      <div className="flex gap-2">
        <button
          disabled={pending}
          className="h-11 flex-1 rounded-lg bg-ink text-[14px] font-medium text-white disabled:opacity-60 sm:h-9 sm:flex-none sm:px-4"
        >
          {pending ? "Connecting…" : "Add connector"}
        </button>
        <button type="button" onClick={() => setOpen(false)} className="h-11 rounded-lg px-4 text-[14px] text-muted hover:bg-sidebar sm:h-9">
          Cancel
        </button>
      </div>
    </form>
  );
}
