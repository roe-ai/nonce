/** Filters and durations in words a person reads at a glance (mirrors backend/privato/humanize.py). */

import type { SourceId } from "./api";

export const SOURCES: Record<SourceId, { label: string; logo: string; items: string; whole: string; wants: string }> = {
  gmail: { label: "Gmail", logo: "gmail", items: "emails", whole: "your entire inbox", wants: "read your email" },
  calendar: { label: "Google Calendar", logo: "google-calendar", items: "events", whole: "your whole calendar", wants: "see your calendar" },
  drive: { label: "Google Drive", logo: "google-drive", items: "files", whole: "all your files", wants: "look at your files" },
  slack: { label: "Slack", logo: "slack", items: "messages", whole: "all your Slack messages", wants: "read your Slack" },
};

export const isConnector = (id: string | null | undefined) => !!id?.startsWith("connector:");

/** A source's words. Connectors the user added are named by `name` (a grant's or event's account). */
export function source(id: string | null | undefined, name?: string | null) {
  if (isConnector(id)) {
    const n = name || "your connector";
    return { label: n, logo: "connector", items: "results", whole: `anything in ${n}`, wants: `use ${n}` };
  }
  return SOURCES[(id ?? "gmail") as SourceId] ?? SOURCES.gmail;
}

function terms(q: string): string[][] {
  const toks = q.replace(/[()]/g, " ").match(/"[^"]*"|\S+/g) ?? [];
  const groups: string[][] = [];
  let join = false;
  for (const t of toks) {
    if (t.toUpperCase() === "OR") {
      join = true;
      continue;
    }
    if (join && groups.length) groups[groups.length - 1].push(t.replace(/"/g, ""));
    else groups.push([t.replace(/"/g, "")]);
    join = false;
  }
  return groups;
}

const list = (xs: string[]) => (xs.length <= 1 ? xs.join("") : `${xs.slice(0, -1).join(", ")} or ${xs.at(-1)}`);
const sentence = (s: string) => s.charAt(0).toUpperCase() + s.slice(1);

function gmail(q: string): string {
  if (/in:anywhere|in:all/i.test(q)) return "Your entire inbox";
  const from: string[] = [];
  const subject: string[] = [];
  const words: string[] = [];
  let unread = false;
  for (const group of terms(q)) {
    const plain: string[] = [];
    for (const t of group) {
      const [field, ...rest] = t.split(":");
      const val = rest.join(":");
      if (val && field.toLowerCase() === "from") from.push(val);
      else if (val && field.toLowerCase() === "subject") subject.push(`“${val}”`);
      else if (t.toLowerCase() === "is:unread") unread = true;
      else if (!val) plain.push(t);
    }
    if (plain.length) words.push(list(plain));
  }
  const parts = [unread ? "Unread emails" : "Emails"];
  if (from.length) parts.push(`from ${list(from)}`);
  if (subject.length) parts.push(`with ${list(subject)} in the subject`);
  if (words.length) parts.push(`about ${words.join(" ")}`);
  return parts.join(" ");
}

const TYPE_WORDS: Record<string, string> = { doc: "docs", sheet: "spreadsheets", slides: "slide decks", pdf: "PDFs", folder: "folders", image: "images" };

function day(iso: string): string {
  const d = new Date(`${iso}T12:00:00`);
  return Number.isNaN(d.getTime()) ? iso : d.toLocaleDateString(undefined, { month: "short", day: "numeric", year: "numeric" });
}

/** Calendar, Drive and Slack filters: words plus key:value terms, all of which must match. */
function structured(q: string, id: SourceId): string {
  const fields: Record<string, string[]> = {};
  const words: string[] = [];
  for (const tok of q.match(/(?:[\w-]+:)?"[^"]*"|\S+/g) ?? []) {
    const m = tok.match(/^([\w-]+):(.+)$/);
    if (m) (fields[m[1].toLowerCase()] ??= []).push(m[2].replace(/"/g, ""));
    else if (!/^(and|or)$/i.test(tok)) words.push(tok.replace(/"/g, ""));
  }
  const f = (k: string) => fields[k] ?? [];
  const types = f("type").map((t) => TYPE_WORDS[t.toLowerCase()] ?? t);
  const parts = [types.length ? list(types) : SOURCES[id].items];
  if (f("name").length) parts.push(`named ${list(f("name").map((n) => `“${n}”`))}`);
  if (f("in").length) parts.push(`in ${list(f("in").map((c) => `#${c.replace(/^#/, "")}`))}`);
  if (f("from").length) parts.push(`from ${list(f("from").map((p) => p.replace(/^@/, "")))}`);
  if (f("with").length) parts.push(`with ${list(f("with"))}`);
  if (f("owner").length) parts.push(`owned by ${list(f("owner"))}`);
  if (words.length) parts.push(`about ${words.join(" ")}`);
  const after = f("after").at(-1);
  const before = f("before").at(-1);
  const when = after && before ? `between ${day(after)} and ${day(before)}` : after ? `after ${day(after)}` : before ? `before ${day(before)}` : "";
  if (when) parts.push(`${id === "drive" ? "modified " : ""}${when}`);
  return sentence(parts.length > 1 || types.length ? parts.join(" ") : `Some of your ${SOURCES[id].items}`);
}

export function describeFilter(q: string | null | undefined, id: string | null = "gmail"): string {
  const src = (id ?? "gmail") as SourceId;
  if (!q?.trim()) return sentence(source(src).whole);
  if (isConnector(src)) return sentence(q.trim());
  return src === "gmail" || !SOURCES[src] ? gmail(q) : structured(q, src);
}

/** For use mid-sentence: "Emails from x" → "emails from x". */
export function describeFilterInline(q: string | null | undefined, id: string | null = "gmail"): string {
  const d = describeFilter(q, id);
  return d.charAt(0).toLowerCase() + d.slice(1);
}

export function describeDuration(seconds: number): string {
  if (seconds < 3600) {
    const m = Math.max(1, Math.round(seconds / 60));
    return `${m} minute${m === 1 ? "" : "s"}`;
  }
  const h = Math.round(seconds / 3600);
  if (h < 48) return `${h} hour${h === 1 ? "" : "s"}`;
  return `${Math.round(h / 24)} days`;
}

export function ago(ts: number | null | undefined): string {
  if (!ts) return "Never";
  const s = Math.max(0, Math.round(Date.now() / 1000 - ts));
  if (s < 60) return "Just now";
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return `${Math.floor(s / 86400)}d ago`;
}

export function timeOfDay(ts: number): string {
  return new Date(ts * 1000).toLocaleTimeString(undefined, { hour: "numeric", minute: "2-digit" });
}

export function dayLabel(ts: number): string {
  const d = new Date(ts * 1000);
  const today = new Date();
  const yesterday = new Date(Date.now() - 86400000);
  if (d.toDateString() === today.toDateString()) return "Today";
  if (d.toDateString() === yesterday.toDateString()) return "Yesterday";
  return d.toLocaleDateString(undefined, { weekday: "long", month: "short", day: "numeric" });
}

export function reasons(text: string | null | undefined): string[] {
  return (text ?? "").split(/\.\s+/).map((r) => r.replace(/\.$/, "").trim()).filter(Boolean);
}

export function hourLabel(h: number): string {
  const hour = h % 12 === 0 ? 12 : h % 12;
  return `${hour}${h < 12 ? "am" : "pm"}`;
}
