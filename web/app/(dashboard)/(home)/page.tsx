import { ArrowRight, Inbox, Lock, X } from "lucide-react";
import Link from "next/link";
import type { ReactNode } from "react";
import { AccessPasses, RequestPass } from "@/components/access";
import { ActivityFeed, hasVisibleActivity } from "@/components/activity";
import { Heatmap } from "@/components/heatmap";
import { PhoneNudge } from "@/components/phone";
import { BrandMark, Panel, PanelEmpty } from "@/components/ui";
import { api, type AccessEvent, type Connection, type DailyActivity, type Grant, type Overview, type RequestGroup } from "@/lib/api";

const DAY_RE = /^\d{4}-\d{2}-\d{2}$/;

function dayTitle(day: string): string {
  return new Date(`${day}T00:00:00Z`).toLocaleDateString("en-US", { weekday: "long", month: "long", day: "numeric", timeZone: "UTC" });
}

/** A column of passes sitting on the paper, with its own scroll. */
function Lane({ title, count, children }: { title: string; count?: number; children: ReactNode }) {
  return (
    <section className="flex min-h-0 min-w-0 flex-col">
      <h2 className="mb-3 flex shrink-0 items-baseline gap-2 px-1">
        <span className="font-display text-[22px] leading-none">{title}</span>
        {count ? <span className="text-[12px] font-medium text-faint tabular-nums">{count}</span> : null}
      </h2>
      <div className="-mx-1 min-h-0 flex-1 overflow-y-auto px-1 pt-2 pb-4">{children}</div>
    </section>
  );
}

function Quiet({ icon, title, children }: { icon: ReactNode; title: string; children: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-2xl border border-dashed border-line px-6 py-10 text-center">
      <div className="mb-3 text-faint">{icon}</div>
      <p className="font-display text-[19px]">{title}</p>
      <p className="mt-1 max-w-xs text-[13px] text-muted">{children}</p>
    </div>
  );
}

function headline(waiting: number, apps: number): { title: string; sub: string } {
  if (waiting) return { title: `${waiting} ${waiting === 1 ? "request needs" : "requests need"} you.`, sub: "Nothing goes through until you say so." };
  if (apps) return { title: `${apps === 1 ? "One app can" : `${apps} apps can`} see a little, for a little while.`, sub: "Each pass ends on its own. You can stop any of them now." };
  return { title: "All quiet.", sub: "No AI app can see your data right now." };
}

export default async function HomePage({ searchParams }: { searchParams: Promise<{ day?: string }> }) {
  const { day: rawDay } = await searchParams;
  const day = rawDay && DAY_RE.test(rawDay) ? rawDay : undefined;
  const [overview, waiting, active, daily, events, notifications, connections] = await Promise.all([
    api<Overview>("/admin/overview"),
    api<RequestGroup[]>("/admin/requests"),
    api<Grant[]>("/admin/grants?status=active"),
    api<DailyActivity>("/admin/activity/daily"),
    api<AccessEvent[]>(day ? `/admin/events?day=${day}&limit=300` : "/admin/events?limit=100"),
    api<{ push_key: string | null }>("/admin/notifications").catch(() => ({ push_key: null })),
    api<Connection[]>("/admin/connections"),
  ]);

  if (!overview.connections) {
    return (
      <div className="flex flex-col items-center px-5 pt-28 text-center">
        <BrandMark height={28} className="mb-6" />
        <h1 className="font-display text-[40px] leading-tight tracking-[-0.01em]">AI sees what it needs. Nothing else.</h1>
        <p className="mt-2 max-w-md text-muted">
          Connect your accounts to Privato. AI apps only see what they need, only when you ask, and only for a few minutes.
        </p>
        <Link href="/welcome" className="mt-7 inline-flex h-9 items-center gap-1.5 rounded-lg bg-ink px-4 text-[13px] font-medium text-white hover:bg-black">
          Set up Privato <ArrowRight size={14} />
        </Link>
      </div>
    );
  }

  const apps = new Set(active.map((g) => g.agent_id)).size;
  const waitingCount = waiting.reduce((n, grp) => n + grp.grants.length, 0);
  const { title, sub } = headline(waitingCount, apps);

  return (
    <div className="mx-auto flex max-w-[1600px] flex-col gap-5 p-4 md:h-screen md:p-7">
      <header className="shrink-0">
        <h1 className="font-display text-[34px] leading-[1.1] tracking-[-0.01em] md:text-[40px]">{title}</h1>
        <p className="mt-1 text-muted">{sub}</p>
      </header>

      {!overview.agents && (
        <Link
          href="/welcome"
          className="flex items-center justify-between gap-3 rounded-2xl bg-white px-4 py-3 text-[13px] shadow-[0_10px_28px_-16px_rgba(60,40,20,0.35)] ring-1 ring-line hover:bg-sidebar"
        >
          <span>
            <span className="font-medium">Finish setting up.</span> <span className="text-muted">Add Privato to ChatGPT, Claude or another AI app.</span>
          </span>
          <ArrowRight size={14} className="shrink-0" />
        </Link>
      )}

      <PhoneNudge pushKey={notifications.push_key} />

      <div className="order-last md:order-none">
        <Heatmap data={daily} selected={day} />
      </div>

      <div className="grid min-h-0 flex-1 grid-cols-1 gap-6 lg:grid-cols-[1.1fr_1fr_1.1fr]">
        <Lane title="Waiting for you" count={waitingCount}>
          {waiting.length ? (
            <div className="space-y-3">
              {waiting.map((grp) => (
                <RequestPass key={grp.id} group={grp} accounts={connections} />
              ))}
            </div>
          ) : (
            <Quiet icon={<Inbox size={20} strokeWidth={1.6} />} title="All caught up">
              Apps acting on their own, or asking for too much, will wait here for you.
            </Quiet>
          )}
        </Lane>

        <Lane title="Access right now" count={active.length}>
          {active.length ? (
            <AccessPasses grants={active} />
          ) : (
            <Quiet icon={<Lock size={20} strokeWidth={1.6} />} title="Nothing is open">
              When you ask an AI app for help, it gets a short pass to just what it needs.
            </Quiet>
          )}
        </Lane>

        <Panel
          title={day ? dayTitle(day) : "Recent activity"}
          className="max-h-[480px] min-w-0 md:max-h-none"
          action={
            day ? (
              <Link href="/" scroll={false} className="-mr-2 inline-flex h-9 items-center gap-1 px-2 text-[12px] text-muted hover:text-ink">
                <X size={12} /> Close
              </Link>
            ) : (
              <Link href="/activity" className="-mr-2 inline-flex h-9 items-center px-2 text-[12px] text-muted hover:text-ink">
                See all
              </Link>
            )
          }
        >
          {hasVisibleActivity(events) ? (
            <ActivityFeed events={events} grouped={!day} flat />
          ) : (
            <PanelEmpty title={day ? "A quiet day" : "No activity yet"}>No AI app touched your data.</PanelEmpty>
          )}
        </Panel>
      </div>
    </div>
  );
}
