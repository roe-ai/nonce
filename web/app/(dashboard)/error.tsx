"use client";

import { CloudOff } from "lucide-react";

export default function DashboardError({ unstable_retry }: { error: Error & { digest?: string }; unstable_retry: () => void }) {
  return (
    <div className="flex flex-col items-center py-24 text-center">
      <CloudOff size={28} strokeWidth={1.6} className="mb-4 text-faint" />
      <p className="font-medium">Privato is unreachable right now</p>
      <p className="mt-1 text-[13px] text-muted">Your data stays locked while we&apos;re offline. No app can get in.</p>
      <button onClick={() => unstable_retry()} className="mt-5 h-8 rounded-lg border border-line bg-white px-3 text-[13px] font-medium hover:bg-sidebar">
        Try again
      </button>
    </div>
  );
}
