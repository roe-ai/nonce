import { LayoutGrid } from "lucide-react";
import { disableAgent } from "@/app/actions";
import { AddApp } from "@/components/add-app";
import { AppMode } from "@/components/app-mode";
import { TimeLeft } from "@/components/live";
import { AppAvatar, Button, Dot, Empty, List, PageHeader } from "@/components/ui";
import { api, mcpUrl, type Agent, type Grant } from "@/lib/api";
import { ago, describeFilterInline } from "@/lib/humanize";

export default async function AppsPage() {
  const [agents, active] = await Promise.all([api<Agent[]>("/admin/agents"), api<Grant[]>("/admin/grants?status=active")]);
  const connected = agents.filter((a) => a.status === "active");

  return (
    <>
      <PageHeader title="AI apps" description="Apps that can ask to use your data. Each one asks separately, and you can cut any of them off." action={<AddApp mcpUrl={mcpUrl} />} />
      {connected.length ? (
        <List>
          {connected.map((a) => {
            const grant = active.find((g) => g.agent_id === a.id);
            return (
              <div key={a.id} className="flex items-center gap-3.5 px-4 py-3.5">
                <AppAvatar kind={a.kind} name={a.name} size={36} />
                <div className="min-w-0 flex-1">
                  <div className="flex items-center gap-2 font-medium">
                    {a.name} <AppMode agentId={a.id} name={a.name} kind={a.kind} mode={a.mode ?? "standard"} />
                  </div>
                  <p className="mt-0.5 flex items-center gap-1.5 truncate text-[13px] text-muted">
                    {grant ? (
                      <>
                        <Dot tone="green" /> Can see {describeFilterInline(grant.query_constraint, grant.source)} ·{" "}
                        {grant.expires_at && <TimeLeft until={grant.expires_at} />}
                      </>
                    ) : (
                      <>
                        <Dot tone="gray" /> No access · last active {ago(a.last_seen_at).toLowerCase()}
                      </>
                    )}
                  </p>
                </div>
                {a.blocked > 0 && <span className="shrink-0 text-[12px] text-faint">{a.blocked} blocked</span>}
                <form action={disableAgent.bind(null, a.id)}>
                  <Button variant="danger">Remove</Button>
                </form>
              </div>
            );
          })}
        </List>
      ) : (
        <Empty icon={<LayoutGrid size={20} strokeWidth={1.6} />} title="No apps yet">
          Add ChatGPT, Claude or another assistant. It will only see your data when you ask it something.
        </Empty>
      )}
    </>
  );
}
