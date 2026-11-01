"use client";

import { Coffee, Shield, ShieldCheck, Sparkles, X } from "lucide-react";
import { useEffect, useState, useTransition } from "react";
import { createPortal } from "react-dom";
import { previewModes, setAppMode } from "@/app/actions";
import { AppAvatar } from "@/components/ui";
import type { ModeName, ModePreview } from "@/lib/api";

const MODES: {
  id: ModeName;
  name: string;
  tagline: string;
  icon: typeof Shield;
  accent: string;
  soft: string;
  ring: string;
  bar: string;
  points: string[];
}[] = [
  {
    id: "cautious",
    name: "Cautious",
    tagline: "Ask me about anything new",
    icon: ShieldCheck,
    accent: "text-indigo-600",
    soft: "bg-indigo-50",
    ring: "ring-indigo-500",
    bar: "bg-indigo-500",
    points: [
      "Asks unless you've asked something like it lately. nonce's agent searches your past questions to check",
      "Asks before an app reads whole emails, files or messages",
      "Up to 15 minutes of access without asking",
    ],
  },
  {
    id: "standard",
    name: "Standard",
    tagline: "Ask when something looks off",
    icon: Shield,
    accent: "text-ink",
    soft: "bg-sidebar",
    ring: "ring-ink",
    bar: "bg-ink",
    points: [
      "Asks for money, health, and password or login data",
      "Asks when the app seems to act on its own",
      "Up to 1 hour of access without asking",
    ],
  },
  {
    id: "relaxed",
    name: "Relaxed",
    tagline: "Only stop me for the big stuff",
    icon: Coffee,
    accent: "text-emerald-600",
    soft: "bg-emerald-50",
    ring: "ring-emerald-500",
    bar: "bg-emerald-500",
    points: [
      "Lets clear questions about money and health through",
      "Still always asks for passwords and login codes",
      "Up to 4 hours of access without asking",
    ],
  },
];

export function ModeBadge({ mode }: { mode: ModeName }) {
  const m = MODES.find((x) => x.id === mode) ?? MODES[1];
  const Icon = m.icon;
  return (
    <span
      className={`inline-flex items-center gap-1 rounded-full px-2 py-0.5 text-[12px] font-medium ${m.soft} ${m.accent}`}
    >
      <Icon size={12} strokeWidth={2.2} /> {m.name}
    </span>
  );
}

function Preview({
  preview,
  selected,
}: {
  preview: ModePreview | null;
  selected: ModeName;
}) {
  if (!preview)
    return <div className="h-[92px] animate-pulse rounded-lg bg-sidebar" />;
  if (!preview.requests) {
    return (
      <p className="flex items-center gap-2 rounded-lg bg-sidebar px-3.5 py-3 text-[13px] text-muted">
        <Sparkles size={14} /> Once this app has asked for something,
        you&apos;ll see how each mode would have handled it.
      </p>
    );
  }
  const total = preview.requests;
  return (
    <div className="space-y-2">
      {MODES.map((m) => {
        const r = preview.modes[m.id];
        const pct = (n: number) => `${(n / total) * 100}%`;
        return (
          <div
            key={m.id}
            className={`flex items-center gap-3 text-[12px] ${m.id === selected ? "text-ink" : "text-muted"}`}
          >
            <span
              className={`w-16 shrink-0 ${m.id === selected ? "font-medium" : ""}`}
            >
              {m.name}
            </span>
            <div className="flex h-2 flex-1 overflow-hidden rounded-full bg-sidebar">
              <span
                className="bg-emerald-400/80 transition-all duration-500"
                style={{ width: pct(r.allow) }}
              />
              <span
                className="bg-amber-400 transition-all duration-500"
                style={{ width: pct(r.ask) }}
              />
              <span
                className="bg-red-400 transition-all duration-500"
                style={{ width: pct(r.deny) }}
              />
            </div>
            <span className="w-28 shrink-0 text-right tabular-nums">
              asks you <span className="font-medium text-ink">{r.ask}</span> of{" "}
              {total}
            </span>
          </div>
        );
      })}
      <p className="flex gap-3 pt-1 text-[11px] text-faint">
        <span className="flex items-center gap-1">
          <i className="size-2 rounded-full bg-emerald-400/80" /> goes through
        </span>
        <span className="flex items-center gap-1">
          <i className="size-2 rounded-full bg-amber-400" /> asks you
        </span>
        <span className="flex items-center gap-1">
          <i className="size-2 rounded-full bg-red-400" /> blocked
        </span>
      </p>
    </div>
  );
}

export function AppMode({
  agentId,
  name,
  kind,
  mode,
}: {
  agentId: string;
  name: string;
  kind: string;
  mode: ModeName;
}) {
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState<ModeName>(mode);
  const [preview, setPreview] = useState<ModePreview | null>(null);
  const [saving, startSaving] = useTransition();

  useEffect(() => {
    if (open && !preview)
      previewModes(agentId).then(setPreview, () =>
        setPreview({
          days: 30,
          requests: 0,
          modes: {} as ModePreview["modes"],
        }),
      );
  }, [open, preview, agentId]);

  const choose = (m: ModeName) => {
    setSelected(m);
    startSaving(() => setAppMode(agentId, m));
  };

  return (
    <>
      <button
        onClick={() => setOpen(true)}
        className="-my-2.5 rounded-full py-2.5 transition-transform hover:scale-[1.03]"
        aria-label={`Change how careful nonce is with ${name}`}
      >
        <ModeBadge mode={selected} />
      </button>
      {open &&
        createPortal(
          <div
            className="fixed inset-0 z-50 grid place-items-center bg-black/20 p-4 backdrop-blur-[2px]"
            onClick={() => setOpen(false)}
          >
            <div
              className="w-full max-w-[720px] rounded-2xl border border-line bg-white p-6 shadow-xl"
              onClick={(e) => e.stopPropagation()}
            >
              <div className="mb-5 flex items-start justify-between gap-4">
                <div className="flex items-center gap-3">
                  <AppAvatar kind={kind} name={name} size={36} />
                  <div>
                    <h2 className="text-[16px] font-semibold">
                      How careful should nonce be with {name}?
                    </h2>
                    <p className="text-[13px] text-muted">
                      {saving
                        ? "Saving…"
                        : "Changes apply to its next request."}
                    </p>
                  </div>
                </div>
                <button
                  onClick={() => setOpen(false)}
                  className="text-faint hover:text-ink"
                  aria-label="Close"
                >
                  <X size={16} />
                </button>
              </div>

              <div className="grid gap-3 sm:grid-cols-3" role="radiogroup">
                {MODES.map((m) => {
                  const Icon = m.icon;
                  const on = selected === m.id;
                  return (
                    <button
                      key={m.id}
                      role="radio"
                      aria-checked={on}
                      onClick={() => choose(m.id)}
                      className={`group relative flex flex-col rounded-xl border p-4 text-left transition-all duration-200 ${
                        on
                          ? `border-transparent ring-2 ${m.ring} ${m.soft} shadow-sm`
                          : "border-line hover:-translate-y-0.5 hover:shadow-md"
                      }`}
                    >
                      <span
                        className={`mb-3 grid size-9 place-items-center rounded-lg ${on ? "bg-white" : m.soft} ${m.accent} transition-colors`}
                      >
                        <Icon size={18} strokeWidth={2} />
                      </span>
                      <span className="font-semibold">{m.name}</span>
                      <span className="mt-0.5 text-[13px] text-muted">
                        {m.tagline}
                      </span>
                      <ul className="mt-3 space-y-1.5 text-[12px] leading-snug text-muted">
                        {m.points.map((p) => (
                          <li key={p} className="flex gap-1.5">
                            <span
                              className={`mt-[5px] size-1 shrink-0 rounded-full ${m.bar}`}
                            />
                            {p}
                          </li>
                        ))}
                      </ul>
                    </button>
                  );
                })}
              </div>

              <p className="mt-4 text-[12px] text-faint">
                In every mode, nonce still blocks grabs for everything and
                access over 24 hours, cuts off off-topic searches, and holds
                requests during your offline hours.
              </p>

              <div className="mt-5 border-t border-line pt-4">
                <h3 className="mb-3 text-[13px] font-medium">
                  With {name}&apos;s last 30 days of requests
                </h3>
                <Preview preview={preview} selected={selected} />
              </div>
            </div>
          </div>,
          document.body,
        )}
    </>
  );
}
