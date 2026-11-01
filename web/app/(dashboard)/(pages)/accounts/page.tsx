import { AlertTriangle, RefreshCw } from "lucide-react";
import {
  pauseAccount,
  pauseConnector,
  refreshConnector,
  removeConnection,
  removeConnector,
  setToolRule,
} from "@/app/actions";
import { ConnectAccountButton } from "@/components/connect-account";
import { ConnectorForm } from "@/components/connector-form";
import { AccountLogo, Dot, PageHeader, Section } from "@/components/ui";
import { api, type Connection, type Connector, type ConnectorTool, type SourceId, type ToolRule } from "@/lib/api";
import { SOURCES, source } from "@/lib/humanize";

const ORDER: SourceId[] = ["gmail", "calendar", "drive", "slack"];
const ACCESS: Record<SourceId, string> = {
  gmail: "read-only",
  calendar: "read-only",
  drive: "read-only",
  slack: "search and read only",
};
const RULES: { rule: ToolRule; label: string }[] = [
  { rule: "auto", label: "Auto" },
  { rule: "ask", label: "Ask me" },
  { rule: "off", label: "Off" },
];

function Small({ children, tone = "plain", ...props }: React.ButtonHTMLAttributes<HTMLButtonElement> & { tone?: "plain" | "danger" }) {
  return (
    <button
      {...props}
      className={`h-9 rounded-lg px-3 text-[13px] font-medium whitespace-nowrap ${
        tone === "danger" ? "text-muted hover:bg-red-50 hover:text-red-600" : "text-muted hover:bg-sidebar hover:text-ink"
      }`}
    >
      {children}
    </button>
  );
}

function AccountRow({ conn }: { conn: Connection }) {
  const paused = conn.status === "paused";
  return (
    <li className="flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 pl-[50px]">
      <div className="min-w-0 flex-1 basis-48">
        <p className={`truncate text-[14px] ${paused ? "text-faint" : ""}`}>{conn.account}</p>
        <p className="mt-0.5 flex items-center gap-1.5 text-[12px] text-muted">
          {paused ? (
            <>
              <Dot tone="gray" /> Paused · apps can&apos;t ask for it
            </>
          ) : (
            <>
              <Dot tone="green" /> {ACCESS[conn.provider]}
            </>
          )}
        </p>
      </div>
      <div className="-mr-2 flex flex-wrap items-center">
        <form action={pauseAccount.bind(null, conn.id, !paused)}>
          <Small>{paused ? "Resume" : "Pause"}</Small>
        </form>
        <form action={removeConnection.bind(null, conn.id)}>
          <Small tone="danger">Disconnect</Small>
        </form>
      </div>
    </li>
  );
}

function ToolRow({ connector, tool }: { connector: Connector; tool: ConnectorTool }) {
  return (
    <li className="space-y-2 py-3">
      <div className="flex flex-wrap items-center gap-2">
        <code className="rounded bg-sidebar px-1.5 py-0.5 text-[12.5px] text-ink">{tool.name}</code>
        <span className={`text-[11.5px] font-medium ${tool.read_only ? "text-emerald-700" : "text-amber-700"}`}>
          {tool.read_only ? "Reads" : "Can change things"}
        </span>
      </div>
      {tool.suspicious ? (
        <p className="flex items-start gap-1.5 text-[12.5px] text-amber-800">
          <AlertTriangle size={13} className="mt-0.5 shrink-0" /> Its description tried to give AI apps instructions, so nonce hid it and turned this tool off.
        </p>
      ) : (
        tool.description && <p className="line-clamp-2 text-[13px] text-muted">{tool.description}</p>
      )}
      <div className="grid grid-cols-3 gap-1 rounded-lg bg-sidebar p-1 sm:inline-grid sm:w-72">
        {RULES.map(({ rule, label }) => (
          <form key={rule} action={setToolRule.bind(null, connector.id, tool.name, rule)}>
            <button
              aria-pressed={tool.rule === rule}
              className={`h-8 w-full rounded-md text-[12.5px] font-medium ${
                tool.rule === rule ? (rule === "off" ? "bg-white text-red-600 shadow-sm" : "bg-white text-ink shadow-sm") : "text-muted"
              }`}
            >
              {label}
            </button>
          </form>
        ))}
      </div>
    </li>
  );
}

function ConnectorCard({ connector }: { connector: Connector }) {
  const paused = connector.status === "paused";
  const on = connector.tools.filter((t) => t.rule !== "off").length;
  let host = connector.url;
  try {
    host = new URL(connector.url).host;
  } catch {}
  return (
    <div className="rounded-xl border border-line bg-white">
      <div className="flex flex-wrap items-center gap-3 px-4 pt-4 pb-3">
        <AccountLogo logo="connector" muted={paused} />
        <div className="min-w-0 flex-1 basis-40">
          <p className="flex items-center gap-2 font-medium">
            <span className="truncate">{connector.name}</span>
            <span className="shrink-0 rounded-full bg-sidebar px-2 py-px text-[11px] font-medium text-muted">{connector.kind === "mcp" ? "MCP" : "API"}</span>
          </p>
          <p className="mt-0.5 flex items-center gap-1.5 truncate text-[12px] text-muted">
            <Dot tone={paused ? "gray" : connector.error ? "amber" : "green"} />
            {paused ? "Paused" : `${on} of ${connector.tools.length} tools on`} · {host}
            {connector.auth_header && ` · ${connector.auth_header} kept by nonce`}
          </p>
        </div>
        <div className="-mr-2 flex flex-wrap items-center">
          <form action={refreshConnector.bind(null, connector.id)}>
            <Small aria-label="Refresh tools">
              <RefreshCw size={14} />
            </Small>
          </form>
          <form action={pauseConnector.bind(null, connector.id, !paused)}>
            <Small>{paused ? "Resume" : "Pause"}</Small>
          </form>
          <form action={removeConnector.bind(null, connector.id)}>
            <Small tone="danger">Remove</Small>
          </form>
        </div>
      </div>
      {connector.error && <p className="mx-4 mb-3 rounded-lg bg-amber-50 px-3 py-2 text-[12.5px] text-amber-800">{connector.error}</p>}
      {connector.tools.length > 0 && (
        <details className="group border-t border-line" open={connector.tools.length <= 4}>
          <summary className="flex h-11 cursor-pointer list-none items-center justify-between px-4 text-[13px] font-medium text-muted">
            What each tool may do
            <span className="text-faint group-open:rotate-90">›</span>
          </summary>
          <ul className="divide-y divide-line px-4 pb-1">
            {connector.tools.map((t) => (
              <ToolRow key={t.name} connector={connector} tool={t} />
            ))}
          </ul>
        </details>
      )}
    </div>
  );
}

export default async function AccountsPage({
  searchParams,
}: {
  searchParams: Promise<{ connected?: string; error?: string; source?: string }>;
}) {
  const [{ connected, error, source: failed }, connections, connectors] = await Promise.all([
    searchParams,
    api<Connection[]>("/admin/connections"),
    api<Connector[]>("/admin/connectors").catch(() => [] as Connector[]),
  ]);

  return (
    <>
      <PageHeader title="Accounts" description="Your accounts stay with nonce. AI apps never get your password or login." />
      {connected && (
        <p className="mb-6 rounded-lg bg-emerald-50 px-4 py-2.5 text-[13px] text-emerald-800">{source(connected).label} is connected and protected.</p>
      )}
      {error && (
        <p className="mb-6 rounded-lg bg-red-50 px-4 py-2.5 text-[13px] text-red-700">
          {error === "access_denied" || error === "cancelled" ? `${source(failed).label} wasn't connected. You can try again any time.` : error}
        </p>
      )}

      <Section title="Your accounts">
        <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">
          {ORDER.map((id) => {
            const mine = connections.filter((c) => c.provider === id);
            const src = SOURCES[id];
            return (
              <div key={id} className="px-4 py-3.5">
                <div className="flex items-center gap-3.5">
                  <AccountLogo logo={src.logo} muted={!mine.length} />
                  <div className="min-w-0 flex-1">
                    <p className="font-medium">{src.label}</p>
                    {!mine.length && (
                      <p className="mt-0.5 flex items-center gap-1.5 text-[13px] text-muted">
                        <Dot tone="gray" /> Not connected
                      </p>
                    )}
                    {mine.length > 1 && <p className="mt-0.5 text-[12px] text-muted">Apps suggest which ones fit each question. You can change it when they ask.</p>}
                  </div>
                  <ConnectAccountButton provider={id} label={src.label} another={mine.length > 0} />
                </div>
                {mine.length > 0 && (
                  <ul className="mt-1.5 divide-y divide-line">
                    {mine.map((c) => (
                      <AccountRow key={c.id} conn={c} />
                    ))}
                  </ul>
                )}
              </div>
            );
          })}
        </div>
      </Section>

      <Section title="Your connectors">
        <p className="-mt-1 mb-3 text-[13px] text-muted">
          Add your own MCP server or API. Apps reach it only through nonce, with the same approvals, limits and checks as your email.
        </p>
        <div className="space-y-3">
          {connectors.map((c) => (
            <ConnectorCard key={c.id} connector={c} />
          ))}
          <ConnectorForm />
        </div>
      </Section>
    </>
  );
}
