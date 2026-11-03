import { AppBadge, AutoRefresh, MobileNav, Nav } from "@/components/live";
import { ServiceWorker } from "@/components/phone";
import Link from "next/link";
import { redirect } from "next/navigation";
import { BrandMark } from "@/components/ui";
import { api, ApiError, type Overview, type User } from "@/lib/api";

function Logo() {
  return (
    <div className="flex items-center gap-2">
      <BrandMark height={15} />
      <span className="text-[14px] font-semibold tracking-[-0.01em]">Privato</span>
    </div>
  );
}

function Avatar({ user }: { user: User }) {
  if (user.picture) {
    // eslint-disable-next-line @next/next/no-img-element -- Google profile photo
    return <img src={user.picture} alt="" referrerPolicy="no-referrer" className="size-7 shrink-0 rounded-full" />;
  }
  return (
    <span className="grid size-7 shrink-0 place-items-center rounded-full bg-hover text-[12px] font-semibold text-muted">
      {(user.name ?? user.email).slice(0, 1).toUpperCase()}
    </span>
  );
}

export default async function DashboardLayout({ children }: { children: React.ReactNode }) {
  const [me, overview] = await Promise.all([
    api<User>("/admin/me").catch((e) => {
      if (e instanceof ApiError && e.status === 401) redirect("/login");
      return null;
    }),
    api<Overview>("/admin/overview").catch(() => null),
  ]);
  const waiting = overview?.pending ?? 0;
  return (
    <div className="flex min-h-screen flex-col md:flex-row">
      <aside className="sticky top-0 hidden h-screen w-[220px] shrink-0 flex-col border-r border-line bg-sidebar px-3 py-4 md:flex">
        <div className="mb-5 px-2.5">
          <Logo />
        </div>
        <Nav waiting={waiting} />
        <div className="mt-auto space-y-3">
          <div className="flex items-center gap-2 px-2.5 text-[12px] text-muted">
            <span className={`size-1.5 rounded-full ${overview ? "bg-emerald-500" : "bg-zinc-300"}`} />
            {overview ? "Protecting your data" : "Offline"}
          </div>
          {me && (
            <Link href="/settings" className="flex items-center gap-2.5 rounded-md px-2.5 py-1.5 hover:bg-hover">
              <Avatar user={me} />
              <span className="min-w-0">
                <span className="block truncate text-[13px] font-medium">{me.name ?? me.email}</span>
                <span className="block truncate text-[11px] text-faint">{me.email}</span>
              </span>
            </Link>
          )}
        </div>
      </aside>
      <header className="sticky top-0 z-10 flex items-center justify-between border-b border-line bg-canvas/90 px-4 pt-[calc(env(safe-area-inset-top)+12px)] pb-3 backdrop-blur md:hidden">
        <Logo />
        {me && (
          <Link href="/settings" aria-label="Settings" className="-m-1.5 grid size-10 place-items-center rounded-full">
            <Avatar user={me} />
          </Link>
        )}
      </header>
      <main className="min-w-0 flex-1 pb-[calc(56px+env(safe-area-inset-bottom))] md:pb-0">{children}</main>
      <MobileNav waiting={waiting} />
      <AutoRefresh />
      <ServiceWorker />
      <AppBadge count={waiting} />
    </div>
  );
}
