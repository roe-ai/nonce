"use client";

import { Activity, Home, Inbox, LayoutGrid, Settings } from "lucide-react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import { useEffect, useState } from "react";

/** Re-renders the server page every few seconds so new requests show up without a reload. */
export function AutoRefresh({ ms = 4000 }: { ms?: number }) {
  const router = useRouter();
  useEffect(() => {
    const id = setInterval(() => {
      if (document.visibilityState === "visible") router.refresh();
    }, ms);
    return () => clearInterval(id);
  }, [router, ms]);
  return null;
}

export function TimeLeft({ until }: { until: number }) {
  const [now, setNow] = useState(() => Date.now() / 1000);
  useEffect(() => {
    const id = setInterval(() => setNow(Date.now() / 1000), 1000);
    return () => clearInterval(id);
  }, []);
  const left = Math.max(0, Math.round(until - now));
  if (!left) return <>Ending…</>;
  if (left < 60) return <>{left}s left</>;
  if (left < 3600) return <>{Math.ceil(left / 60)} min left</>;
  return <>{Math.round(left / 3600)} h left</>;
}

const NAV = [
  { href: "/", label: "Home", icon: Home },
  { href: "/activity", label: "Activity", icon: Activity },
  { href: "/apps", label: "AI apps", icon: LayoutGrid },
  { href: "/accounts", label: "Accounts", icon: Inbox },
  { href: "/settings", label: "Settings", icon: Settings },
];

/** The tab you just tapped lights up right away, before its page arrives. */
function useActiveTab() {
  const path = usePathname();
  const [tap, setTap] = useState<{ href: string; from: string } | null>(null);
  const current = tap && tap.from === path ? tap.href : null;
  return {
    isActive: (href: string) => (current ? current === href : href === "/" ? path === "/" : path.startsWith(href)),
    onTap: (href: string) => setTap({ href, from: path }),
  };
}

export function Nav({ waiting }: { waiting: number }) {
  const { isActive, onTap } = useActiveTab();
  return (
    <nav className="flex flex-col gap-px">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = isActive(href);
        return (
          <Link
            key={href}
            href={href}
            onClick={() => onTap(href)}
            className={`flex h-8 items-center gap-2.5 rounded-md px-2.5 text-[13px] font-medium transition-colors ${
              active ? "bg-selected text-ink" : "text-muted hover:bg-hover hover:text-ink"
            }`}
          >
            <Icon size={15} strokeWidth={1.8} />
            {label}
            {href === "/" && waiting > 0 && (
              <span className="ml-auto grid h-[18px] min-w-[18px] place-items-center rounded-full bg-accent px-1 text-[11px] text-white">{waiting}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

/** Bottom tab bar on phones, clear of the home indicator. */
export function MobileNav({ waiting }: { waiting: number }) {
  const { isActive, onTap } = useActiveTab();
  return (
    <nav className="fixed inset-x-0 bottom-0 z-20 flex border-t border-line bg-canvas/95 pb-[env(safe-area-inset-bottom)] backdrop-blur md:hidden">
      {NAV.map(({ href, label, icon: Icon }) => {
        const active = isActive(href);
        return (
          <Link
            key={href}
            href={href}
            onPointerDown={() => onTap(href)}
            onClick={() => onTap(href)}
            className={`relative flex h-14 flex-1 flex-col items-center justify-center gap-0.5 text-[10.5px] font-medium transition-transform active:scale-95 ${active ? "text-ink" : "text-faint"}`}
          >
            <Icon size={20} strokeWidth={active ? 2.1 : 1.7} />
            {label}
            {href === "/" && waiting > 0 && (
              <span className="absolute top-1.5 left-[calc(50%+6px)] grid h-4 min-w-4 place-items-center rounded-full bg-accent px-1 text-[10px] text-white">{waiting}</span>
            )}
          </Link>
        );
      })}
    </nav>
  );
}

/** The waiting count on the Home Screen icon, where the phone supports it. */
export function AppBadge({ count }: { count: number }) {
  useEffect(() => {
    const nav = navigator as Navigator & { setAppBadge?: (n?: number) => Promise<void>; clearAppBadge?: () => Promise<void> };
    if (count > 0) nav.setAppBadge?.(count).catch(() => {});
    else nav.clearAppBadge?.().catch(() => {});
  }, [count]);
  return null;
}

export function CopyButton({ text, label = "Copy" }: { text: string; label?: string }) {
  const [done, setDone] = useState(false);
  return (
    <button
      type="button"
      onClick={async () => {
        await navigator.clipboard.writeText(text);
        setDone(true);
        setTimeout(() => setDone(false), 1500);
      }}
      className="inline-flex h-7 items-center rounded-md border border-line bg-white px-2.5 text-[12px] font-medium text-ink hover:bg-sidebar"
    >
      {done ? "Copied" : label}
    </button>
  );
}
