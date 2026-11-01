"use client";

import { useEffect, useState, type ReactNode } from "react";
import { useFormStatus } from "react-dom";
import { AppAvatar, Button } from "@/components/ui";

/** A ticket: the app's colored stub, a perforated tear line, and the body. */
export function Pass({
  color,
  kind,
  name,
  label,
  children,
}: {
  color: string;
  kind?: string | null;
  name?: string | null;
  label: string;
  children: ReactNode;
}) {
  return (
    <div className="pass-in relative flex overflow-hidden rounded-2xl bg-white shadow-[0_1px_0_rgba(60,40,20,0.05),0_10px_28px_-16px_rgba(60,40,20,0.35)] ring-1 ring-line">
      <div
        className="flex w-[52px] shrink-0 flex-col items-center gap-3 py-4"
        style={{ background: `linear-gradient(165deg, color-mix(in oklab, ${color} 88%, white), ${color} 55%, color-mix(in oklab, ${color} 80%, black))` }}
      >
        <span className="rounded-[10px] bg-white/95 p-0.5 shadow-sm">
          <AppAvatar kind={kind} name={name} size={30} />
        </span>
        <span className="text-[10px] font-semibold tracking-[0.22em] text-white/85 uppercase [writing-mode:vertical-rl] rotate-180">{label}</span>
      </div>
      <div className="relative w-0 border-l-2 border-dashed border-line" aria-hidden>
        <span className="absolute -top-2 -left-[9px] size-4 rounded-full bg-canvas ring-1 ring-line" />
        <span className="absolute -bottom-2 -left-[9px] size-4 rounded-full bg-canvas ring-1 ring-line" />
      </div>
      <div className="min-w-0 flex-1 px-4 py-4">{children}</div>
    </div>
  );
}

const STAMP_MS = 380;

/** A form's submit button that presses a stamp onto the pass, then sends the answer. */
export function StampButton({
  children,
  stamp,
  tone,
  variant = "secondary",
}: {
  children: ReactNode;
  stamp: string;
  tone: "good" | "bad";
  variant?: "primary" | "secondary" | "danger";
}) {
  const { pending } = useFormStatus();
  const [stamped, setStamped] = useState(false);
  const ink = tone === "good" ? "text-emerald-700 border-emerald-700" : "text-red-700 border-red-700";
  return (
    <>
      <Button
        variant={variant}
        disabled={pending || stamped}
        onClick={(e) => {
          // Land the stamp first; the answer goes out once it has.
          e.preventDefault();
          const form = e.currentTarget.form;
          setStamped(true);
          setTimeout(() => form?.requestSubmit(), STAMP_MS);
        }}
      >
        {children}
      </Button>
      {(pending || stamped) && (
        <span className="pointer-events-none absolute inset-0 z-10 grid place-items-center" aria-live="polite">
          <span className={`stamp-mark rounded-lg border-[3px] px-4 py-1 font-display text-[30px] tracking-[0.08em] uppercase ${ink}`}>{stamp}</span>
        </span>
      )}
    </>
  );
}

function clock(s: number): string {
  if (s >= 3600) return `${Math.floor(s / 3600)}h ${Math.floor((s % 3600) / 60)}m`;
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
}

/** Time left on a pass, as a fuse burning down. Turns amber in the last minute. */
export function Fuse({ start, until, color }: { start: number; until: number; color: string }) {
  const [now, setNow] = useState<number | null>(null);
  useEffect(() => {
    const tick = () => setNow(Date.now() / 1000);
    tick();
    const id = setInterval(tick, 1000);
    return () => clearInterval(id);
  }, []);
  const t = now ?? start;
  const left = Math.max(0, Math.round(until - t));
  const frac = until > start ? Math.min(1, left / (until - start)) : 0;
  const hue = left < 60 ? "#e0912b" : color;
  return (
    <div className="flex items-center gap-3">
      <div className="relative h-1.5 flex-1 rounded-full bg-[#efe8dc]">
        <div className="absolute inset-y-0 left-0 rounded-full transition-[width] duration-1000 ease-linear" style={{ width: `${frac * 100}%`, background: hue }} />
        {left > 0 && (
          <span
            className="spark absolute top-1/2 size-2.5 rounded-full transition-[left] duration-1000 ease-linear"
            style={{ left: `${frac * 100}%`, background: hue, boxShadow: `0 0 0 3px color-mix(in oklab, ${hue} 25%, transparent), 0 0 12px ${hue}` }}
          />
        )}
      </div>
      <span className="w-14 shrink-0 text-right text-[12px] font-medium text-muted tabular-nums">{left ? clock(left) : "Ending…"}</span>
    </div>
  );
}
