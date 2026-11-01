import { Ban, Check, ChevronRight, EyeOff, KeyRound, Layers, Mail, Search, ShieldAlert, X } from "lucide-react";
import type { ReactNode } from "react";
import { Step } from "@/components/step";
import { AppAvatar } from "@/components/ui";
import type { AccessEvent } from "@/lib/api";
import { dayLabel, describeFilterInline, reasons, source, timeOfDay } from "@/lib/humanize";

type Tone = "neutral" | "good" | "warn" | "bad";

interface Line {
  icon: ReactNode;
  tone: Tone;
  text: ReactNode;
  sub?: string;
}

const B = ({ children }: { children: ReactNode }) => <span className="font-medium text-ink">{children}</span>;

function lineFor(e: AccessEvent): Line | null {
  const app = <B>{e.agent_name ?? "An app"}</B>;
  const d = e.detail ?? {};
  const why = reasons(e.reason)[0];
  const [kind, verb] = e.action.split(".");
  const sourceId = (d.source as string | undefined) ?? e.source ?? (verb === "search" || verb === "read" ? kind : "gmail");
  const src = source(sourceId, (d.connector as string | undefined) ?? e.account);
  const title = String(d.title ?? d.subject ?? "");
  const data = verb === "search" || verb === "read" ? `${verb}:${e.decision}` : `${e.action}:${e.decision}`;
  switch (data) {
    case "access.request:allow":
      return {
        icon: <KeyRound size={13} />,
        tone: "good",
        text: <>{app} got access to {describeFilterInline(String(d.query ?? ""), sourceId)}</>,
        sub: `You asked: “${d.user_request}”`,
      };
    case "access.request:ask":
      return { icon: <ShieldAlert size={13} />, tone: "warn", text: <>{app} asked for your permission</>, sub: why };
    case "access.request:deny":
      return { icon: <Ban size={13} />, tone: "bad", text: <>Blocked {app}</>, sub: why };
    case "access.approve:allow":
      return { icon: <Check size={13} />, tone: "good", text: <>You allowed {app}</>, sub: e.user_request ? `For “${e.user_request}”` : undefined };
    case "access.deny:deny":
      return { icon: <X size={13} />, tone: "neutral", text: <>You declined {app}</> };
    case "search:allow":
    case "search:warn": {
      const n = Number(d.result_count ?? 0);
      return {
        icon: <Search size={13} />,
        tone: e.decision === "warn" ? "warn" : "neutral",
        text: <>{app} searched your {src.label}{d.query ? <> for “{String(d.query)}”</> : null}</>,
        sub: n ? `Found ${n} ${n === 1 ? src.items.replace(/s$/, "") : src.items}` : "Nothing found",
      };
    }
    case "read:allow":
      return { icon: <Mail size={13} />, tone: "neutral", text: <>{app} opened {title ? <>“{title}”</> : `one of your ${src.items}`}</> };
    case "read:redact":
      return { icon: <EyeOff size={13} />, tone: "warn", text: <>Hid something suspicious from {app}</>, sub: `“${title}” tried to give the AI instructions` };
    case "search:revoke":
    case "read:revoke":
      return { icon: <Ban size={13} />, tone: "bad", text: <>Stopped {app}</>, sub: why };
    case "connector.call:allow":
    case "connector.call:warn":
      return {
        icon: <Layers size={13} />,
        tone: e.decision === "warn" ? "warn" : "neutral",
        text: <>{app} used {String(d.tool ?? "a tool")} in {src.label}</>,
        sub: d.is_error ? "It returned an error" : undefined,
      };
    case "connector.call:redact":
      return { icon: <EyeOff size={13} />, tone: "warn", text: <>Hid something suspicious from {app}</>, sub: `${src.label} returned text that tried to give the AI instructions` };
    case "connector.call:revoke":
      return { icon: <Ban size={13} />, tone: "bad", text: <>Stopped {app}</>, sub: why };
    case "grant.misuse:deny":
      return { icon: <Ban size={13} />, tone: "bad", text: <>Blocked {app}</>, sub: why };
    case "grant.revoke:revoke":
      return d.by === "user" ? { icon: <X size={13} />, tone: "neutral", text: <>You stopped {app}</> } : null;
    default:
      return null;
  }
}

const TONE: Record<Tone, string> = {
  neutral: "bg-sidebar text-muted",
  good: "bg-emerald-50 text-emerald-600",
  warn: "bg-amber-50 text-amber-600",
  bad: "bg-red-50 text-red-600",
};

function Row({ e, line }: { e: AccessEvent; line: Line }) {
  return (
    <div className="flex items-start gap-3.5 px-4 py-3">
      <div className="relative mt-0.5">
        <AppAvatar kind={e.agent_kind} name={e.agent_name} size={28} />
        <span className={`absolute -right-1.5 -bottom-1.5 grid size-[18px] place-items-center rounded-full ring-2 ring-white ${TONE[line.tone]}`}>{line.icon}</span>
      </div>
      <div className="min-w-0 flex-1">
        <p className="text-muted">{line.text}</p>
        {line.sub && <p className="mt-0.5 truncate text-[13px] text-faint">{line.sub}</p>}
      </div>
      <span className="shrink-0 pt-0.5 text-[12px] text-faint tabular-nums">{timeOfDay(e.ts)}</span>
    </div>
  );
}

function StepRow({ e, line }: { e: AccessEvent; line: Line }) {
  return (
    <Step e={e} title={line.text}>
      <Row e={e} line={line} />
    </Step>
  );
}

type Shown = { e: AccessEvent; line: Line };
type Item = { kind: "row"; r: Shown } | { kind: "task"; key: string; rows: Shown[] };

/** Events of one task (tasks.py on the API) fold together, placed where its latest event is. */
function byTask(rows: Shown[]): Item[] {
  const tasks = new Map<string, Extract<Item, { kind: "task" }>>();
  const out: Item[] = [];
  for (const r of rows) {
    const t = r.e.task_id;
    if (!t) {
      out.push({ kind: "row", r });
      continue;
    }
    let item = tasks.get(t);
    if (!item) {
      item = { kind: "task", key: t, rows: [] };
      tasks.set(t, item);
      out.push(item);
    }
    item.rows.push(r);
  }
  return out.map((i) => (i.kind === "task" && i.rows.length === 1 ? { kind: "row", r: i.rows[0] } : i));
}

const WORST: Tone[] = ["bad", "warn", "good", "neutral"];

function TaskGroup({ rows }: { rows: Shown[] }) {
  const latest = rows[0].e;
  const tone = WORST.find((t) => rows.some((r) => r.line.tone === t)) ?? "neutral";
  const counts = [
    [rows.filter((r) => r.line.tone === "bad").length, "blocked"],
    [rows.filter((r) => r.line.tone === "warn").length, "flagged"],
  ].filter(([n]) => n) as [number, string][];
  const sources = [...new Set(rows.filter((r) => r.e.source).map((r) => source(r.e.source, r.e.account).label))];
  return (
    <details className="group">
      <summary className="flex cursor-pointer list-none items-start gap-3.5 px-4 py-3 hover:bg-sidebar/50 [&::-webkit-details-marker]:hidden">
        <div className="relative mt-0.5">
          <AppAvatar kind={latest.agent_kind} name={latest.agent_name} size={28} />
          <span className={`absolute -right-1.5 -bottom-1.5 grid size-[18px] place-items-center rounded-full ring-2 ring-white ${TONE[tone]}`}>
            <Layers size={11} />
          </span>
        </div>
        <div className="min-w-0 flex-1">
          <p className="text-muted">
            <span className="font-medium text-ink">{latest.agent_name ?? "An app"}</span> worked on{" "}
            <span className="font-medium text-ink">{latest.task_title ?? latest.user_request ?? "a task"}</span>
          </p>
          <p className="mt-0.5 truncate text-[13px] text-faint">
            {rows.length} steps{sources.length ? ` · ${sources.join(", ")}` : ""}
            {counts.map(([n, word]) => ` · ${n} ${word}`).join("")}
          </p>
        </div>
        <span className="flex shrink-0 items-center gap-1 pt-0.5 text-[12px] text-faint tabular-nums">
          {[...new Set([timeOfDay(rows.at(-1)!.e.ts), timeOfDay(latest.ts)])].join("–")}
          <ChevronRight size={13} className="transition-transform group-open:rotate-90" />
        </span>
      </summary>
      <div className="ml-[30px] border-l border-line">
        {rows.map(({ e, line }) => (
          <StepRow key={e.id} e={e} line={line} />
        ))}
      </div>
    </details>
  );
}

function Items({ rows, box }: { rows: Shown[]; box: string }) {
  return (
    <div className={box}>
      {byTask(rows).map((i) => (i.kind === "row" ? <StepRow key={i.r.e.id} e={i.r.e} line={i.r.line} /> : <TaskGroup key={i.key} rows={i.rows} />))}
    </div>
  );
}

/** `flat` drops the card chrome so the feed can sit inside a Panel. */
export function ActivityFeed({ events, grouped = true, flat = false }: { events: AccessEvent[]; grouped?: boolean; flat?: boolean }) {
  const rows = events.map((e) => ({ e, line: lineFor(e) })).filter((r): r is Shown => r.line !== null);
  const box = flat ? "divide-y divide-line" : "divide-y divide-line overflow-hidden rounded-xl border border-line bg-white";
  if (!grouped) return <Items rows={rows} box={box} />;
  const days = new Map<string, typeof rows>();
  for (const r of rows) {
    const k = dayLabel(r.e.ts);
    days.set(k, [...(days.get(k) ?? []), r]);
  }
  return (
    <div className={flat ? "" : "space-y-8"}>
      {[...days].map(([day, items]) => (
        <div key={day}>
          <h3
            className={
              flat
                ? "sticky top-0 z-[1] border-b border-line bg-sidebar/95 px-4 py-1.5 text-[12px] font-medium text-muted backdrop-blur"
                : "mb-2.5 text-[13px] font-medium text-muted"
            }
          >
            {day}
          </h3>
          <Items rows={items} box={box} />
        </div>
      ))}
    </div>
  );
}

export function hasVisibleActivity(events: AccessEvent[]): boolean {
  return events.some((e) => lineFor(e) !== null);
}
