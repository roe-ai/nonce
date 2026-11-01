import { History } from "lucide-react";
import Link from "next/link";
import { ActivityFeed, hasVisibleActivity } from "@/components/activity";
import { Empty, PageHeader } from "@/components/ui";
import { api, type AccessEvent } from "@/lib/api";

const TABS = [
  { key: "all", label: "Everything" },
  { key: "blocked", label: "Blocked" },
];

export default async function ActivityPage({ searchParams }: { searchParams: Promise<{ show?: string }> }) {
  const { show = "all" } = await searchParams;
  const events = await api<AccessEvent[]>(`/admin/events?limit=200${show === "blocked" ? "&blocked=true" : ""}`);

  return (
    <>
      <PageHeader title="Activity" description="Everything AI apps did with your data, and everything we stopped." />
      <div className="mb-6 flex gap-1">
        {TABS.map((t) => (
          <Link
            key={t.key}
            href={t.key === "all" ? "/activity" : `/activity?show=${t.key}`}
            className={`h-9 rounded-md px-3 text-[13px] leading-9 font-medium sm:h-7 sm:px-2.5 sm:leading-7 ${show === t.key ? "bg-selected text-ink" : "text-muted hover:text-ink"}`}
          >
            {t.label}
          </Link>
        ))}
      </div>
      {hasVisibleActivity(events) ? (
        <ActivityFeed events={events} />
      ) : (
        <Empty icon={<History size={20} strokeWidth={1.6} />} title={show === "blocked" ? "Nothing blocked yet" : "No activity yet"}>
          {show === "blocked" ? "When an app oversteps, you'll see it here." : "When an AI app uses your data, you'll see each step here."}
        </Empty>
      )}
    </>
  );
}
