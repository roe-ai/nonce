import { ArrowRight, Check, Loader2 } from "lucide-react";
import { headers } from "next/headers";
import Link from "next/link";
import type { ReactNode } from "react";
import { AppSetup } from "@/components/add-app";
import { ConnectAccountButton } from "@/components/connect-account";
import { CopyButton } from "@/components/live";
import { PhoneSetup } from "@/components/phone";
import { AccountLogo, AppAvatar } from "@/components/ui";
import { api, mcpUrl, type AccessEvent, type Agent, type Connection, type SourceId } from "@/lib/api";
import { SOURCES, source } from "@/lib/humanize";

type StepId = "account" | "app" | "phone" | "try";
const ORDER: StepId[] = ["account", "app", "phone", "try"];
const PROVIDERS: SourceId[] = ["gmail", "calendar", "drive", "slack"];
const TITLES: Record<StepId, string> = {
  account: "Connect an account",
  app: "Add Privato to your AI app",
  phone: "Get a tap when an app asks",
  try: "Ask your first question",
};
const PROMPTS: Record<SourceId, string> = {
  gmail: "Using Privato, find my most recent shipping confirmation email.",
  calendar: "Using Privato, what's on my calendar tomorrow?",
  drive: "Using Privato, find the doc I edited most recently.",
  slack: "Using Privato, catch me up on my Slack mentions from today.",
};

function Waiting({ children }: { children: ReactNode }) {
  return (
    <p className="mt-4 flex items-center gap-2 text-[13px] text-muted">
      <Loader2 size={14} className="animate-spin" /> {children}
    </p>
  );
}

function Next({ to, children = "Continue" }: { to: string; children?: ReactNode }) {
  return (
    <Link href={to} className="mt-5 inline-flex h-9 items-center gap-1.5 rounded-lg bg-ink px-4 text-[13px] font-medium text-white hover:bg-black">
      {children} <ArrowRight size={14} />
    </Link>
  );
}

function Step({ n, id, current, done, summary, children }: { n: number; id: StepId; current: boolean; done: boolean; summary?: ReactNode; children: ReactNode }) {
  return (
    <li className={`rounded-2xl border bg-white ${current ? "border-ink/15 shadow-[0_10px_28px_-18px_rgba(60,40,20,0.35)]" : "border-line"}`}>
      <Link href={`/welcome?step=${id}`} scroll={false} className="flex items-center gap-3.5 px-5 py-4">
        <span
          className={`grid size-7 shrink-0 place-items-center rounded-full text-[12px] font-semibold ${
            done ? "bg-emerald-600 text-white" : current ? "bg-ink text-white" : "bg-sidebar text-muted"
          }`}
        >
          {done ? <Check size={14} strokeWidth={2.5} /> : n}
        </span>
        <span className="min-w-0 flex-1">
          <span className={`block font-medium ${current || done ? "text-ink" : "text-muted"}`}>{TITLES[id]}</span>
          {summary && !current && <span className="mt-0.5 block truncate text-[12.5px] text-muted">{summary}</span>}
        </span>
        {id === "phone" && !done && <span className="text-[11.5px] text-faint">Optional</span>}
      </Link>
      {current && <div className="border-t border-line px-5 pt-4 pb-5">{children}</div>}
    </li>
  );
}

function FirstRequest({ event }: { event: AccessEvent }) {
  const outcome =
    event.decision === "allow"
      ? "Privato let it through, for just that, for a few minutes."
      : event.decision === "ask"
        ? "Privato is holding it for you. Allow or decline it on your dashboard."
        : `Privato blocked it${event.reason ? `: ${event.reason.toLowerCase()}` : "."}`;
  return (
    <div className="mt-4 rounded-xl bg-sidebar p-4">
      <p className="flex items-center gap-2 text-[13px] font-medium">
        <AppAvatar kind={event.agent_kind} name={event.agent_name} size={20} /> {event.agent_name} asked
      </p>
      {event.user_request && <p className="mt-1.5 font-display text-[17px] leading-snug">“{event.user_request}”</p>}
      <p className="mt-1.5 text-[13px] text-muted">{outcome}</p>
    </div>
  );
}

export default async function WelcomePage({
  searchParams,
}: {
  searchParams: Promise<{ step?: string; connected?: string; error?: string; source?: string }>;
}) {
  const [{ step: asked, connected, error, source: failed }, connections, agents, notifications, events, host] = await Promise.all([
    searchParams,
    api<Connection[]>("/admin/connections"),
    api<Agent[]>("/admin/agents"),
    api<{ push_key: string | null; push_devices: number }>("/admin/notifications").catch(() => ({ push_key: null, push_devices: 0 })),
    api<AccessEvent[]>("/admin/events?limit=50"),
    headers().then((h) => h.get("host")),
  ]);

  const accounts = connections.filter((c) => c.status === "active");
  const apps = agents.filter((a) => a.status === "active");
  const first = [...events].reverse().find((e) => e.action === "access.request");
  const done: Record<StepId, boolean> = { account: accounts.length > 0, app: apps.length > 0, phone: notifications.push_devices > 0, try: !!first };
  const finished = done.account && done.app && done.try;
  const current: StepId | null = ORDER.includes(asked as StepId) ? (asked as StepId) : finished ? null : (ORDER.find((s) => !done[s]) ?? null);
  const after = (id: StepId) => `/welcome?step=${ORDER[ORDER.indexOf(id) + 1]}`;
  const app = apps[0];
  const appName = app?.name ?? "your AI app";
  const providers = [...new Set(accounts.map((c) => c.provider))];

  return (
    <>
      <header className="mb-8">
        <h1 className="font-display text-[34px] leading-tight tracking-[-0.01em]">{finished && !current ? "You're set." : "Let's set up Privato."}</h1>
        <p className="mt-1 text-muted">
          {finished && !current
            ? "Your AI apps now ask Privato first, and only see what each question needs."
            : "A few steps, about two minutes. AI apps will only see what you ask about, for a few minutes at a time."}
        </p>
      </header>

      {finished && !current && (
        <div className="mb-6">
          <Next to="/">Go to your dashboard</Next>
        </div>
      )}

      <ol className="space-y-3">
        <Step n={1} id="account" current={current === "account"} done={done.account} summary={accounts.map((c) => c.account).join(", ")}>
          {connected && <p className="mb-4 rounded-lg bg-emerald-50 px-3 py-2 text-[13px] text-emerald-800">{source(connected).label} is connected and protected.</p>}
          {error && (
            <p className="mb-4 rounded-lg bg-red-50 px-3 py-2 text-[13px] text-red-700">
              {error === "access_denied" || error === "cancelled" ? `${source(failed).label} wasn't connected. You can try again.` : error}
            </p>
          )}
          <p className="mb-4 text-[13px] text-muted">Pick what AI apps may ask about. Privato keeps the login; apps never see it, and everything is read-only.</p>
          <div className="divide-y divide-line rounded-xl border border-line">
            {PROVIDERS.map((id) => {
              const mine = accounts.filter((c) => c.provider === id);
              return (
                <div key={id} className="flex items-center gap-3 px-3.5 py-3">
                  <AccountLogo logo={SOURCES[id].logo} size={32} muted={!mine.length} />
                  <div className="min-w-0 flex-1">
                    <p className="text-[14px] font-medium">{SOURCES[id].label}</p>
                    {mine.length > 0 && <p className="truncate text-[12px] text-muted">{mine.map((c) => c.account).join(", ")}</p>}
                  </div>
                  <ConnectAccountButton provider={id} label={SOURCES[id].label} another={mine.length > 0} back="/welcome?step=account" short />
                </div>
              );
            })}
          </div>
          {done.account && <Next to={after("account")} />}
        </Step>

        <Step n={2} id="app" current={current === "app"} done={done.app} summary={apps.map((a) => a.name).join(", ")}>
          {done.app ? (
            <>
              <p className="flex items-center gap-2 text-[14px]">
                <AppAvatar kind={app.kind} name={app.name} size={24} /> {app.name} is connected. It starts with no access, and asks Privato each time.
              </p>
              <Next to={after("app")} />
            </>
          ) : (
            <>
              <AppSetup mcpUrl={mcpUrl} />
              <Waiting>Waiting for your app to connect. This page updates by itself.</Waiting>
            </>
          )}
        </Step>

        <Step n={3} id="phone" current={current === "phone"} done={done.phone} summary={done.phone ? "Notifications are on" : undefined}>
          <p className="mb-4 text-[13px] text-muted">
            When an app asks for something unusual, Privato holds it until you say so. Turn on notifications to hear about it right away. For
            your phone, open <span className="font-medium text-ink">{host ?? "this site"}</span> there and add it to your Home Screen.
          </p>
          <PhoneSetup pushKey={notifications.push_key} />
          <div className="flex items-center gap-4">
            <Next to={after("phone")}>{done.phone ? "Continue" : "Skip for now"}</Next>
          </div>
        </Step>

        <Step n={4} id="try" current={current === "try"} done={done.try} summary={first?.user_request ? `“${first.user_request}”` : undefined}>
          {first ? (
            <>
              <FirstRequest event={first} />
              <Next to="/">Go to your dashboard</Next>
            </>
          ) : (
            <>
              <p className="mb-3 text-[13px] text-muted">
                Ask {appName} something that needs your data. If it doesn&apos;t reach for Privato, turn Privato on in its tools or connectors menu.
              </p>
              <div className="space-y-2">
                {(providers.length ? providers : (["gmail"] as SourceId[])).map((p) => (
                  <div key={p} className="flex items-center gap-2 rounded-lg border border-line px-3 py-2">
                    <AccountLogo logo={SOURCES[p].logo} size={24} />
                    <span className="min-w-0 flex-1 text-[13px]">{PROMPTS[p]}</span>
                    <CopyButton text={PROMPTS[p]} />
                  </div>
                ))}
              </div>
              <Waiting>Waiting for {appName} to ask. You&apos;ll see what Privato decided right here.</Waiting>
            </>
          )}
        </Step>
      </ol>

      {!finished && (
        <p className="mt-8 text-center text-[12.5px] text-faint">
          <Link href="/" className="hover:text-ink">
            Skip setup
          </Link>
        </p>
      )}
    </>
  );
}
