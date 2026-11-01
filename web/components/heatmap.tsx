"use client";

import { useRouter } from "next/navigation";
import { useEffect, useMemo, useRef, useState } from "react";
import type { DailyActivity } from "@/lib/api";

const WEEKS = 53;
const DAY_MS = 86400000;
const MONTHS = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"];
const WEEKDAYS = ["Sun", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat"];

const ACTIVITY = ["#ebe5da", "#d4d7f6", "#a9b0ee", "#7e88e2", "#5e6ad2"];
const BLOCKED = ["#fde2e2", "#f9a8a8", "#f06b6b", "#dc3c3c"];

type Day = { key: string; date: Date; total: number; blocked: number; asked: number; future: boolean };

const keyOf = (d: Date) => d.toISOString().slice(0, 10);

function colorFor(d: Day, max: number): string {
  if (d.future) return "transparent";
  if (d.blocked) return BLOCKED[d.blocked >= 7 ? 3 : d.blocked >= 4 ? 2 : d.blocked >= 2 ? 1 : 0];
  if (!d.total) return ACTIVITY[0];
  return ACTIVITY[Math.min(4, 1 + Math.floor((d.total / Math.max(max, 1)) * 3.999))];
}

function describe(d: Day): string {
  const date = `${WEEKDAYS[d.date.getUTCDay()]}, ${MONTHS[d.date.getUTCMonth()]} ${d.date.getUTCDate()}`;
  if (!d.total) return `${date} · No activity`;
  const parts = [`${d.total} action${d.total === 1 ? "" : "s"}`];
  if (d.blocked) parts.push(`${d.blocked} blocked`);
  if (d.asked) parts.push(`${d.asked} asked you`);
  return `${date} · ${parts.join(" · ")}`;
}

export function Heatmap({ data, selected }: { data: DailyActivity; selected?: string }) {
  const router = useRouter();
  const [hover, setHover] = useState<Day | null>(null);
  const scroller = useRef<HTMLDivElement>(null);

  useEffect(() => {
    scroller.current?.scrollTo({ left: scroller.current.scrollWidth });
  }, []);

  const { weeks, months, max, totals } = useMemo(() => {
    const byDay = new Map(data.days.map((d) => [d.day, d]));
    const today = new Date(`${data.today}T00:00:00Z`);
    const start = new Date(today.getTime() - (today.getUTCDay() + (WEEKS - 1) * 7) * DAY_MS);
    const weeks: Day[][] = [];
    const months = new Map<number, string>();
    let max = 0;
    const totals = { total: 0, blocked: 0 };
    for (let w = 0; w < WEEKS; w++) {
      const col: Day[] = [];
      for (let i = 0; i < 7; i++) {
        const date = new Date(start.getTime() + (w * 7 + i) * DAY_MS);
        const key = keyOf(date);
        const row = byDay.get(key);
        const day = { key, date, total: row?.total ?? 0, blocked: row?.blocked ?? 0, asked: row?.asked ?? 0, future: date > today };
        max = Math.max(max, day.total);
        totals.total += day.total;
        totals.blocked += day.blocked;
        if (date.getUTCDate() === 1 && !day.future) months.set(w, MONTHS[date.getUTCMonth()]);
        col.push(day);
      }
      weeks.push(col);
    }
    return { weeks, months, max, totals };
  }, [data]);

  const select = (d: Day) => {
    if (d.future) return;
    router.push(selected === d.key ? "/" : `/?day=${d.key}`, { scroll: false });
  };

  return (
    <div className="shrink-0 rounded-xl border border-line bg-white px-4 pt-3 pb-3">
      <p className="mb-2 text-[13px] font-medium">
        {totals.total} action{totals.total === 1 ? "" : "s"} across your accounts this year
        {totals.blocked > 0 && <span className="font-normal text-muted"> · {totals.blocked} blocked</span>}
      </p>

      <div ref={scroller} className="-mx-1 overflow-x-auto px-1 py-1">
        <div
          className="grid grid-flow-col justify-between gap-[3px] text-[10px] leading-none text-faint [--cell:18px] sm:[--cell:10px]"
          style={{ gridTemplateRows: "auto repeat(7, auto)", gridTemplateColumns: `auto repeat(${WEEKS}, minmax(var(--cell), 20px))` }}
          onMouseLeave={() => setHover(null)}
        >
          {["", "", "Mon", "", "Wed", "", "Fri", ""].map((l, i) => (
            <span key={`label-${i}`} className="flex items-center pr-1.5">
              {l}
            </span>
          ))}
          {weeks.map((col, w) => [
            <span key={`month-${w}`} className="h-4 w-0 whitespace-nowrap">
              {months.get(w)}
            </span>,
            ...col.map((d) => (
              <button
                key={d.key}
                type="button"
                disabled={d.future}
                aria-label={describe(d)}
                onMouseEnter={() => setHover(d)}
                onFocus={() => setHover(d)}
                onClick={() => select(d)}
                className={`aspect-square w-full rounded-[3px] outline-none transition-transform enabled:hover:scale-125 focus-visible:ring-2 focus-visible:ring-accent ${
                  selected === d.key ? "ring-2 ring-ink ring-offset-1" : ""
                }`}
                style={{ background: colorFor(d, max) }}
              />
            )),
          ])}
        </div>
      </div>

      <div className="mt-2 flex items-center gap-4 text-[11px] text-faint">
        <p className="mr-auto truncate text-[12px] text-muted tabular-nums">{hover ? describe(hover) : "Pick a day to see what happened"}</p>
        <span className="flex items-center gap-1">
          Less
          {ACTIVITY.map((c) => (
            <span key={c} className="size-2.5 rounded-[2px]" style={{ background: c }} />
          ))}
          More
        </span>
        <span className="flex items-center gap-1">
          <span className="size-2.5 rounded-[2px]" style={{ background: BLOCKED[2] }} /> Blocked
        </span>
      </div>
    </div>
  );
}
