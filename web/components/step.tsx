"use client";

import { Check, ChevronRight, X } from "lucide-react";
import { type ReactNode, useEffect, useRef, useState } from "react";
import { AppAvatar } from "@/components/ui";
import type { AccessEvent } from "@/lib/api";
import { describeDuration, describeFilter, reasons, source } from "@/lib/humanize";

const OUTCOME: Record<string, [string, string]> = {
  allow: ["Allowed", "bg-emerald-50 text-emerald-700"],
  warn: ["Allowed, flagged", "bg-amber-50 text-amber-800"],
  ask: ["Asked you", "bg-amber-50 text-amber-800"],
  redact: ["Hidden from the app", "bg-amber-50 text-amber-800"],
  deny: ["Blocked", "bg-red-50 text-red-700"],
  revoke: ["Stopped", "bg-red-50 text-red-700"],
};

/** The detector's yes/no signals (backend/privato/signals.py), phrased so "yes" is the good answer except injection. */
const CHECKS: [key: string, label: string, goodWhenYes: boolean][] = [
  ["user_initiated", "You asked for this", true],
  ["consistent", "Its reason matches your question", true],
  ["scope_fits", "Its filter only reaches what's needed", true],
  ["serves", "The search fits what you asked", true],
  ["familiar", "Like things you've asked before", true],
  ["injection", "Text tried to instruct the AI", false],
];
const SCOPE_WORDS: Record<string, string> = { metadata: "Titles, senders and dates", body: "Full text", details: "Full details", content: "Full text" };
const scopeWords = (scope: string, connector: boolean) => (connector ? scope : (SCOPE_WORDS[scope.split(".")[1]] ?? scope));
const CRAWL = ["A few specific items", "One narrow topic", "A broad category or long period", "Everything of a kind"];

function Field({ label, children, mono = false }: { label: string; children: ReactNode; mono?: boolean }) {
  return (
    <div className="py-2.5">
      <dt className="text-[12px] text-faint">{label}</dt>
      <dd className={`mt-0.5 break-words text-ink ${mono ? "font-mono text-[12px] whitespace-pre-wrap" : "text-[14px]"}`}>{children}</dd>
    </div>
  );
}

function Checks({ signals }: { signals: AccessEvent["signals"] }) {
  const s = signals ?? {};
  const rows = CHECKS.filter(([k]) => typeof s[k] === "number");
  const crawl = typeof s.crawl === "number" ? CRAWL[Math.min(3, Math.max(0, Math.round(s.crawl)))] : null;
  const category = typeof s.category === "string" && s.category !== "other" ? s.category : null;
  if (!rows.length && !crawl && !category && typeof s.closest !== "string") return null;
  return (
    <section className="mt-5">
      <h3 className="text-[12px] font-medium tracking-[0.08em] text-faint uppercase">Privato&apos;s checks</h3>
      <ul className="mt-2 divide-y divide-line rounded-xl border border-line text-[13px]">
        {rows.map(([k, label, goodWhenYes]) => {
          const p = s[k] as number;
          const yes = p >= 0.5;
          const good = yes === goodWhenYes;
          return (
            <li key={k} className="flex items-center gap-2.5 px-3 py-2">
              <span className={`grid size-5 shrink-0 place-items-center rounded-full ${good ? "bg-emerald-50 text-emerald-600" : "bg-amber-50 text-amber-600"}`}>
                {good ? <Check size={12} strokeWidth={2.5} /> : <X size={12} strokeWidth={2.5} />}
              </span>
              <span className="flex-1 text-ink">
                {yes ? label : `Not: ${label.charAt(0).toLowerCase()}${label.slice(1)}`}
              </span>
              <span className="text-[12px] text-faint tabular-nums">{Math.round((yes ? p : 1 - p) * 100)}% sure</span>
            </li>
          );
        })}
        {crawl && (
          <li className="flex items-center justify-between gap-3 px-3 py-2">
            <span className="text-muted">How much it reaches for</span>
            <span className="text-right text-ink">{crawl}</span>
          </li>
        )}
        {category && (
          <li className="flex items-center justify-between gap-3 px-3 py-2">
            <span className="text-muted">Kind of data</span>
            <span className="text-ink capitalize">{category}</span>
          </li>
        )}
        {typeof s.closest === "string" && (
          <li className="px-3 py-2">
            <span className="text-muted">Closest thing you&apos;ve asked</span>
            <p className="mt-0.5 text-ink">“{s.closest}”</p>
          </li>
        )}
      </ul>
    </section>
  );
}

function Detail({ e, title }: { e: AccessEvent; title: ReactNode }) {
  const d = e.detail ?? {};
  const str = (v: unknown) => (typeof v === "string" && v.trim() ? v : null);
  const [kind, verb] = e.action.split(".");
  const sourceId = str(d.source) ?? e.source ?? (verb === "search" || verb === "read" ? kind : null);
  const src = sourceId ? source(sourceId, str(d.connector) ?? str(d.account) ?? e.account) : null;
  const asked = str(d.user_request) ?? e.user_request;
  const filter = str(d.query) && e.action === "access.request" ? str(d.query) : e.query_constraint;
  const [outcome, outcomeTone] = OUTCOME[e.decision] ?? [e.decision, "bg-sidebar text-muted"];
  const why = reasons(e.reason).filter((r) => !/^approved by|^denied by/.test(r));
  const when = new Date(e.ts * 1000).toLocaleString(undefined, { weekday: "short", month: "short", day: "numeric", hour: "numeric", minute: "2-digit", second: "2-digit" });
  const scopes = Array.isArray(d.scopes) ? (d.scopes as string[]) : null;
  const args = d.arguments && typeof d.arguments === "object" && Object.keys(d.arguments).length ? JSON.stringify(d.arguments, null, 2) : null;
  const count = typeof d.result_count === "number" ? d.result_count : null;

  return (
    <>
      <div className="flex items-start gap-3">
        <AppAvatar kind={e.agent_kind} name={e.agent_name} size={36} />
        <div className="min-w-0 flex-1 pr-9">
          <p className="text-[15px] leading-snug text-muted">{title}</p>
          <p className="mt-1 text-[12px] text-faint">{when}</p>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        <span className={`rounded-full px-2.5 py-1 text-[12px] font-medium ${outcomeTone}`}>{outcome}</span>
        {e.latency_ms != null && <span className="text-[12px] text-faint">Checked in {e.latency_ms < 1000 ? `${e.latency_ms} ms` : `${(e.latency_ms / 1000).toFixed(1)} s`}</span>}
      </div>
      {why.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px] text-muted">
          {why.map((r) => (
            <li key={r}>· {r}</li>
          ))}
        </ul>
      )}

      <dl className="mt-4 divide-y divide-line border-y border-line">
        {asked && <Field label="You asked">“{asked}”</Field>}
        {str(d.justification) && <Field label="The app's reason">{str(d.justification)}</Field>}
        {src && <Field label="From">{src.label}{e.account && !src.label.includes(e.account) ? ` · ${e.account}` : ""}</Field>}
        {filter && sourceId && (
          <Field label={sourceId.startsWith("connector:") ? "What it said it would do" : e.action === "access.request" && e.decision !== "allow" ? "Asked to see" : "Allowed to see"}>{describeFilter(filter, sourceId)}</Field>
        )}
        {scopes && <Field label={sourceId?.startsWith("connector:") ? "Tools" : "What it can read"}>{scopes.map((sc) => scopeWords(sc, !!sourceId?.startsWith("connector:"))).join(" and ")}</Field>}
        {typeof d.ttl_s === "number" && <Field label="For">{describeDuration(d.ttl_s)}</Field>}
        {verb === "search" && <Field label="Searched for">{str(d.query) ?? "Everything it was allowed to see"}</Field>}
        {str(d.effective_query) && <Field label="Search Privato ran" mono>{str(d.effective_query)}</Field>}
        {count != null && <Field label="Found">{count === 0 ? "Nothing" : `${count} ${count === 1 ? (src?.items ?? "items").replace(/s$/, "") : (src?.items ?? "items")}`}</Field>}
        {str(d.title) && <Field label="Opened">“{str(d.title)}”</Field>}
        {str(d.tool) && <Field label="Tool">{str(d.tool)}{d.is_error ? " (returned an error)" : ""}</Field>}
        {args && <Field label="With" mono>{args}</Field>}
        {str(d.mode) && <Field label="App's mode"><span className="capitalize">{str(d.mode)}</span></Field>}
      </dl>

      <Checks signals={e.signals} />
    </>
  );
}

/** One activity step; tapping it opens everything Privato recorded about it. */
export function Step({ e, title, children }: { e: AccessEvent; title: ReactNode; children: ReactNode }) {
  const ref = useRef<HTMLDialogElement>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    const dialog = ref.current;
    if (!dialog) return;
    if (open && !dialog.open) dialog.showModal();
    if (!open && dialog.open) dialog.close();
    document.documentElement.style.overflow = open ? "hidden" : "";
    return () => {
      document.documentElement.style.overflow = "";
    };
  }, [open]);

  return (
    <>
      <button type="button" onClick={() => setOpen(true)} className="group/step flex w-full items-start text-left hover:bg-sidebar/50 active:bg-sidebar">
        <div className="min-w-0 flex-1">{children}</div>
        <ChevronRight size={13} className="mt-[15px] mr-3 -ml-2 shrink-0 text-faint/60 group-hover/step:text-faint" />
      </button>
      <dialog
        ref={ref}
        onClose={() => setOpen(false)}
        onClick={(ev) => ev.target === ev.currentTarget && setOpen(false)}
        aria-label="Step details"
        className="fixed inset-x-0 top-auto bottom-0 m-0 max-h-[88dvh] w-full max-w-none overflow-y-auto overscroll-contain rounded-t-2xl bg-white p-0 text-ink shadow-xl backdrop:bg-black/30 sm:inset-y-0 sm:right-0 sm:left-auto sm:h-dvh sm:max-h-none sm:w-[440px] sm:rounded-none sm:rounded-l-2xl"
      >
        {open && (
          <div className="relative px-5 pt-3 pb-[max(1.25rem,env(safe-area-inset-bottom))] sm:pt-6">
            <div className="mx-auto mb-4 h-1 w-10 rounded-full bg-line sm:hidden" />
            <button type="button" onClick={() => setOpen(false)} aria-label="Close" className="absolute top-5 right-3 grid size-10 place-items-center rounded-full text-faint hover:bg-sidebar hover:text-ink sm:top-4">
              <X size={16} />
            </button>
            <Detail e={e} title={title} />
          </div>
        )}
      </dialog>
    </>
  );
}
