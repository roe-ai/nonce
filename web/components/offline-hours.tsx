"use client";

import { Moon, Sun } from "lucide-react";
import { useMemo, useState, useTransition } from "react";
import { setOfflineHours } from "@/app/actions";
import { Button } from "@/components/ui";
import { hourLabel } from "@/lib/humanize";

const PRESETS = [
  { label: "Night", start: 23, end: 7 },
  { label: "Late night", start: 0, end: 6 },
  { label: "Work focus", start: 9, end: 17 },
  { label: "Never", start: 0, end: 0 },
];

const offlineAt = (h: number, start: number, end: number) => start !== end && (start < end ? h >= start && h < end : h >= start || h < end);

/** 24 hour cells: click when you go offline, then when you're back. */
export function OfflineHours({ start, end, timezone }: { start: number; end: number; timezone: string }) {
  const [range, setRange] = useState({ start, end });
  const [picking, setPicking] = useState<number | null>(null);
  const [saving, startSaving] = useTransition();
  const [saved, setSaved] = useState({ start, end });
  const browserTz = useMemo(() => Intl.DateTimeFormat().resolvedOptions().timeZone, []);
  const tz = browserTz || timezone;
  const dirty = range.start !== saved.start || range.end !== saved.end || tz !== timezone;
  const never = range.start === range.end;
  const hours = never ? 0 : (range.end - range.start + 24) % 24;

  const click = (h: number) => {
    if (picking === null) {
      setPicking(h);
      setRange({ start: h, end: (h + 1) % 24 });
    } else {
      setRange({ start: picking, end: (h + 1) % 24 });
      setPicking(null);
    }
  };

  const save = () =>
    startSaving(async () => {
      await setOfflineHours(range.start, range.end, tz);
      setSaved(range);
    });

  return (
    <div className="px-4 py-4">
      <div className="mb-4 flex items-start gap-3.5">
        <span className="grid size-9 shrink-0 place-items-center rounded-lg bg-indigo-950 text-indigo-100">
          <Moon size={16} strokeWidth={1.8} />
        </span>
        <div className="min-w-0 flex-1">
          <p className="font-medium">
            {never ? "You're always reachable" : `Offline ${hourLabel(range.start)} – ${hourLabel(range.end)}`}
            {!never && <span className="ml-2 text-[12px] font-normal text-faint">{hours} hours</span>}
          </p>
          <p className="mt-0.5 text-[13px] text-muted">
            While you&apos;re offline nothing goes through on its own and we won&apos;t text you. Requests wait here until you&apos;re back.
          </p>
        </div>
      </div>

      <div className="relative">
        <div className="grid gap-[3px]" style={{ gridTemplateColumns: "repeat(24, minmax(0, 1fr))" }}>
          {Array.from({ length: 24 }, (_, h) => {
            const off = offlineAt(h, range.start, range.end);
            const edge = h === picking;
            return (
              <button
                key={h}
                type="button"
                onClick={() => click(h)}
                title={`${hourLabel(h)}–${hourLabel((h + 1) % 24)}`}
                className={`h-10 rounded-[5px] transition-all duration-200 hover:-translate-y-0.5 ${
                  off ? "bg-gradient-to-b from-indigo-900 to-indigo-700 shadow-[inset_0_1px_0_rgba(255,255,255,0.12)]" : "bg-amber-100/70 hover:bg-amber-200/80"
                } ${edge ? "ring-2 ring-indigo-400 ring-offset-1" : ""}`}
              >
                {off && h === range.start && <Moon size={11} className="mx-auto text-indigo-200" />}
                {!off && h === 12 && <Sun size={11} className="mx-auto text-amber-500" />}
              </button>
            );
          })}
        </div>
        <div className="mt-1.5 flex justify-between text-[11px] text-faint tabular-nums">
          {[0, 6, 12, 18].map((h) => (
            <span key={h}>{hourLabel(h)}</span>
          ))}
          <span>{hourLabel(0)}</span>
        </div>
      </div>

      <div className="mt-4 flex flex-wrap items-center gap-2">
        {PRESETS.map((p) => {
          const on = range.start === p.start && range.end === p.end;
          return (
            <button
              key={p.label}
              type="button"
              onClick={() => {
                setRange({ start: p.start, end: p.end });
                setPicking(null);
              }}
              className={`h-9 rounded-full border px-3.5 text-[13px] font-medium transition-colors sm:h-7 sm:px-3 sm:text-[12px] ${
                on ? "border-indigo-900 bg-indigo-950 text-white" : "border-line text-muted hover:bg-sidebar hover:text-ink"
              }`}
            >
              {p.label}
            </button>
          );
        })}
        <span className="ml-auto text-[12px] text-faint">{picking !== null ? "Now click when you're back" : `Times in ${tz.replace(/_/g, " ")}`}</span>
        {dirty && (
          <Button variant="primary" onClick={save} disabled={saving}>
            {saving ? "Saving…" : "Save"}
          </Button>
        )}
      </div>
    </div>
  );
}
