import { History, Layers, Search, ShieldAlert, X } from "lucide-react";
import { grantAction, groupAction } from "@/app/actions";
import { AccountChips } from "@/components/account-chips";
import { Fuse, Pass, StampButton } from "@/components/pass";
import { AccountLogo, appColor } from "@/components/ui";
import type { Connection, Grant, RequestGroup } from "@/lib/api";
import { ago, describeDuration, describeFilter, isConnector, reasons, source } from "@/lib/humanize";

/** What Cautious mode's look-back found: the searches Luna ran over your past questions, and the closest one. */
function Recall({ grant }: { grant: Grant }) {
  const s = grant.signals ?? {};
  const queries = Array.isArray(s.recall_queries) ? s.recall_queries : [];
  const closest = typeof s.closest === "string" ? s.closest : null;
  if (!queries.length && !closest) return null;
  return (
    <div className="mt-3 space-y-1.5 rounded-xl bg-sidebar/70 px-3.5 py-2.5 text-[12px] text-muted">
      {queries.length > 0 && (
        <p className="flex flex-wrap items-center gap-1.5">
          <Search size={12} strokeWidth={2} className="shrink-0" /> Looked through your past questions for
          {queries.slice(0, 4).map((q) => (
            <span key={q} className="rounded-md bg-white px-1.5 py-px text-ink ring-1 ring-line">
              {q}
            </span>
          ))}
        </p>
      )}
      <p className="flex items-start gap-1.5">
        <History size={12} strokeWidth={2} className="mt-0.5 shrink-0" />
        {closest ? (
          <span>
            Closest thing you&apos;ve asked: <span className="text-ink">“{closest}”</span>
          </span>
        ) : (
          <span>Nothing like it in what you&apos;ve asked before.</span>
        )}
      </p>
    </div>
  );
}

const norm = (t: string) => t.toLowerCase().replace(/[^a-z0-9]+/g, " ").trim();

function andList(parts: string[]): string {
  return parts.length < 2 ? (parts[0] ?? "") : `${parts.slice(0, -1).join(", ")} and ${parts.at(-1)}`;
}

/** The task's name, when Luna named it something other than the question itself. */
export function TaskChip({ title, question }: { title: string | null | undefined; question?: string | null }) {
  if (!title || (question && norm(title) === norm(question))) return null;
  return (
    <span className="inline-flex max-w-full items-center gap-1 truncate rounded-md bg-violet-50 px-1.5 py-0.5 text-[11px] font-medium text-violet-700">
      <Layers size={11} strokeWidth={2} className="shrink-0" /> {title}
    </span>
  );
}

function Kicker({ children }: { children: React.ReactNode }) {
  return <p className="flex items-center gap-2 text-[11px] font-medium tracking-[0.12em] text-faint uppercase">{children}</p>;
}

/** One request, or everything an app asked for one task, answered with one stamp. */
export function RequestPass({ group, accounts = [] }: { group: RequestGroup; accounts?: Connection[] }) {
  const grants = group.grants;
  const [first] = grants;
  const many = grants.length > 1;
  const ids = grants.map((g) => g.id);
  const wants = andList([...new Set(grants.map((g) => source(g.source, g.account).wants))]);
  const questions = [...new Set(grants.map((g) => g.user_request))];
  const why = [...new Set(grants.flatMap((g) => reasons(g.reason)))];
  const recalled = grants.find((g) => g.signals?.recall_queries || g.signals?.closest) ?? first;
  return (
    <Pass color={appColor(first.agent_kind, first.agent_name)} kind={first.agent_kind} name={first.agent_name} label="Request">
      <Kicker>
        {ago(grants.at(-1)!.created_at)}
        <TaskChip title={group.title ?? first.task_title} question={questions[0]} />
      </Kicker>
      <h3 className="mt-1 font-display text-[22px] leading-[1.15] tracking-[-0.01em]">
        {first.agent_name} wants to {wants}
      </h3>
      {questions.map((q) => (
        <p key={q} className="mt-1 font-display text-[16px] text-muted italic">
          “{q}”
        </p>
      ))}

      <ul className="mt-3 divide-y divide-dashed divide-line border-y border-dashed border-line text-[13px]">
        {grants.map((g) => (
          <li key={g.id} className="flex items-center gap-2.5 py-2">
            <AccountLogo logo={source(g.source, g.account).logo} size={22} />
            <What g={g} className="text-ink" accounts={accounts} />
            <span className="shrink-0 text-[12px] text-faint">{describeDuration(g.ttl_s)}</span>
            {many && (
              <form action={grantAction.bind(null, g.id, "deny")}>
                <button
                  aria-label="Don't allow this one"
                  title="Don't allow this one"
                  className="-my-1.5 grid size-9 place-items-center rounded-md text-faint sm:my-0 sm:size-6 hover:bg-sidebar hover:text-ink"
                >
                  <X size={13} />
                </button>
              </form>
            )}
          </li>
        ))}
      </ul>

      {why.length > 0 && (
        <ul className="mt-3 space-y-1 text-[13px] text-amber-900">
          {why.map((r) => (
            <li key={r} className="flex items-start gap-2">
              <ShieldAlert size={13} strokeWidth={2} className="mt-[3px] shrink-0 text-amber-600" /> {r}
            </li>
          ))}
        </ul>
      )}
      <Recall grant={recalled} />

      <div className="mt-4 flex gap-2">
        <form action={many ? groupAction.bind(null, ids, "approve") : grantAction.bind(null, first.id, "approve")}>
          <StampButton variant="primary" stamp="Allowed" tone="good">
            {many ? `Allow all ${ids.length}` : "Allow"}
          </StampButton>
        </form>
        <form action={many ? groupAction.bind(null, ids, "deny") : grantAction.bind(null, first.id, "deny")}>
          <StampButton stamp="Declined" tone="bad">
            Don&apos;t allow
          </StampButton>
        </form>
      </div>
    </Pass>
  );
}

/** What one request reaches, and in which account or connector. */
/** `accounts` (waiting requests only) lets you change which of several accounts it reads. */
function What({ g, className, accounts = [] }: { g: Grant; className: string; accounts?: Connection[] }) {
  const what = describeFilter(g.query_constraint, g.source);
  const options = g.status === "pending" ? accounts.filter((c) => c.provider === g.source && c.status === "active") : [];
  return (
    <span className={`min-w-0 flex-1 ${className}`}>
      <span className="block truncate">{isConnector(g.source) ? `${g.scopes.join(", ")}: ${what}` : what}</span>
      {options.length > 1 ? (
        <AccountChips
          grantId={g.id}
          options={options.map((c) => ({ id: c.id, account: c.account }))}
          selected={g.account_ids?.filter((id) => options.some((c) => c.id === id)) ?? options.map((c) => c.id)}
        />
      ) : (
        g.account && <span className="block truncate text-[11.5px] text-faint">{g.account}</span>
      )}
    </span>
  );
}

/** Live access, one pass per task, each with a fuse burning down to when it ends. */
export function AccessPasses({ grants }: { grants: Grant[] }) {
  const tasks = new Map<string, Grant[]>();
  for (const g of grants) {
    const key = `${g.agent_id}:${g.task_id ?? g.id}`;
    tasks.set(key, [...(tasks.get(key) ?? []), g]);
  }
  return (
    <div className="space-y-3">
      {[...tasks].map(([key, items]) => (
        <AccessPass key={key} grants={items} />
      ))}
    </div>
  );
}

function AccessPass({ grants }: { grants: Grant[] }) {
  const [first] = grants;
  const many = grants.length > 1;
  const color = appColor(first.agent_kind, first.agent_name);
  const start = Math.min(...grants.map((g) => g.activated_at ?? g.created_at));
  const until = Math.max(...grants.map((g) => g.expires_at ?? 0));
  const title = first.task_title && !norm(first.task_title).startsWith(norm(first.user_request)) ? first.task_title : null;
  return (
    <Pass color={color} kind={first.agent_kind} name={first.agent_name} label="Access">
      <Kicker>{first.agent_name}</Kicker>
      <h3 className="mt-1 truncate font-display text-[19px] leading-tight">{title ?? `“${first.user_request}”`}</h3>
      {title && <p className="mt-0.5 truncate text-[12px] text-faint">For “{first.user_request}”</p>}
      <ul className="mt-2.5 space-y-1 text-[13px]">
        {grants.map((g) => (
          <li key={g.id} className="flex items-center gap-2.5">
            <AccountLogo logo={source(g.source, g.account).logo} size={20} />
            <What g={g} className="text-muted" />
            {many && (
              <form action={grantAction.bind(null, g.id, "revoke")}>
                <button
                  aria-label="Stop this one"
                  title="Stop this one"
                  className="-my-1.5 grid size-9 place-items-center rounded-md text-faint sm:my-0 sm:size-6 hover:bg-red-50 hover:text-red-600"
                >
                  <X size={13} />
                </button>
              </form>
            )}
          </li>
        ))}
      </ul>
      <div className="mt-3 flex items-center gap-3">
        <div className="min-w-0 flex-1">{until > 0 && <Fuse start={start} until={until} color={color} />}</div>
        <form action={many ? groupAction.bind(null, grants.map((g) => g.id), "revoke") : grantAction.bind(null, first.id, "revoke")}>
          <StampButton variant="danger" stamp="Stopped" tone="bad">
            {many ? "Stop all" : "Stop"}
          </StampButton>
        </form>
      </div>
    </Pass>
  );
}
