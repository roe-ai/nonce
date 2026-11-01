import type { ReactNode } from "react";

export function PageHeader({ title, description, action }: { title: string; description?: string; action?: ReactNode }) {
  return (
    <header className="mb-8 flex items-end justify-between gap-6">
      <div>
        <h1 className="text-[22px] font-semibold tracking-[-0.01em]">{title}</h1>
        {description && <p className="mt-1.5 text-muted">{description}</p>}
      </div>
      {action}
    </header>
  );
}

export function Section({ title, action, children }: { title: string; action?: ReactNode; children: ReactNode }) {
  return (
    <section className="mb-10">
      <div className="mb-3 flex items-center justify-between">
        <h2 className="text-[13px] font-medium text-muted">{title}</h2>
        {action}
      </div>
      {children}
    </section>
  );
}

/** A card with a fixed header whose body scrolls on its own. */
export function Panel({
  title,
  count,
  action,
  children,
  className = "",
}: {
  title: ReactNode;
  count?: number;
  action?: ReactNode;
  children: ReactNode;
  className?: string;
}) {
  return (
    <section className={`flex min-h-0 flex-col overflow-hidden rounded-xl border border-line bg-white ${className}`}>
      <div className="flex h-11 shrink-0 items-center justify-between gap-3 border-b border-line px-4">
        <h2 className="flex items-center gap-2 truncate text-[13px] font-medium">
          {title}
          {count ? <span className="rounded-full bg-sidebar px-1.5 py-px text-[11px] font-medium text-muted tabular-nums">{count}</span> : null}
        </h2>
        {action}
      </div>
      <div className="min-h-0 flex-1 overflow-y-auto">{children}</div>
    </section>
  );
}

export function PanelEmpty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex h-full min-h-40 flex-col items-center justify-center px-6 py-8 text-center">
      {icon && <div className="mb-3 text-faint">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-xs text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export function List({ children }: { children: ReactNode }) {
  return <div className="divide-y divide-line overflow-hidden rounded-xl border border-line bg-white">{children}</div>;
}

export function Empty({ icon, title, children }: { icon?: ReactNode; title: string; children?: ReactNode }) {
  return (
    <div className="flex flex-col items-center rounded-xl border border-dashed border-line bg-white px-6 py-10 text-center">
      {icon && <div className="mb-3 text-faint">{icon}</div>}
      <p className="font-medium">{title}</p>
      {children && <div className="mt-1 max-w-sm text-[13px] text-muted">{children}</div>}
    </div>
  );
}

export function Button({
  children,
  variant = "secondary",
  ...props
}: React.ButtonHTMLAttributes<HTMLButtonElement> & { variant?: "primary" | "secondary" | "ghost" | "danger" }) {
  const styles = {
    primary: "bg-ink text-white hover:bg-black shadow-sm",
    secondary: "bg-white text-ink border border-line hover:bg-sidebar shadow-[0_1px_1px_rgba(0,0,0,0.03)]",
    ghost: "text-muted hover:bg-sidebar hover:text-ink",
    danger: "text-muted hover:bg-red-50 hover:text-red-600",
  }[variant];
  return (
    <button
      {...props}
      className={`inline-flex h-8 shrink-0 items-center gap-1.5 rounded-lg px-3 text-[13px] font-medium whitespace-nowrap transition-colors disabled:opacity-50 ${styles} ${props.className ?? ""}`}
    >
      {children}
    </button>
  );
}

/** Apps with a logo in public/logos/<kind>.svg. Keep in sync with AgentKind in backend/nonce/main.py. */
export const KNOWN_APPS: Record<string, string> = {
  chatgpt: "ChatGPT",
  claude: "Claude",
  cursor: "Cursor",
  gemini: "Gemini",
  copilot: "Copilot",
  perplexity: "Perplexity",
  muse: "Muse",
  grok: "Grok",
  deepseek: "DeepSeek",
  mistral: "Mistral",
  meta: "Meta AI",
  pi: "Pi",
  codex: "Codex",
  windsurf: "Windsurf",
  manus: "Manus",
};

const APP_COLORS: Record<string, string> = {
  chatgpt: "#10a37f",
  claude: "#d97757",
  cursor: "#3b3a37",
  gemini: "#4f7ff0",
  copilot: "#2f7de1",
  perplexity: "#1f8a8a",
  muse: "#c2549b",
  grok: "#3b3a37",
  deepseek: "#4d6bfe",
  mistral: "#f2702a",
  meta: "#0866ff",
  pi: "#b7793e",
  codex: "#10a37f",
  windsurf: "#0f9b8e",
  manus: "#6b5bd6",
};

/** Each app's color on its passes: its brand color, or a steady hue picked from its name. */
export function appColor(kind: string | null | undefined, name: string | null | undefined): string {
  const key = logoKey(kind, name);
  if (key && APP_COLORS[key]) return APP_COLORS[key];
  const n = [...(name ?? "?")].reduce((h, c) => (h * 31 + c.charCodeAt(0)) % 360, 7);
  return `hsl(${n} 45% 48%)`;
}

function logoKey(kind: string | null | undefined, name: string | null | undefined): string | null {
  if (kind && KNOWN_APPS[kind]) return kind;
  const n = name?.toLowerCase().replace(/[^a-z]/g, "") ?? "";
  return Object.keys(KNOWN_APPS).find((k) => n === k || n.startsWith(k)) ?? null;
}

export function AppAvatar({ kind, name, size = 32 }: { kind?: string | null; name?: string | null; size?: number }) {
  const key = logoKey(kind, name);
  if (key) {
    return (
      <span
        className="grid shrink-0 place-items-center rounded-lg border border-line bg-white"
        style={{ width: size, height: size }}
        aria-hidden
      >
        {/* eslint-disable-next-line @next/next/no-img-element -- tiny static SVGs */}
        <img src={`/logos/${key}.svg`} alt="" width={Math.round(size * 0.58)} height={Math.round(size * 0.58)} />
      </span>
    );
  }
  return (
    <span
      className="grid shrink-0 place-items-center rounded-lg bg-hover font-semibold text-muted"
      style={{ width: size, height: size, fontSize: size * 0.42 }}
      aria-hidden
    >
      {(name ?? "?").slice(0, 1).toUpperCase()}
    </span>
  );
}

export function BrandMark({ height = 14, className = "" }: { height?: number; className?: string }) {
  // eslint-disable-next-line @next/next/no-img-element -- tiny static SVG
  return <img src="/roe-mark.svg" alt="" aria-hidden style={{ height, width: (height * 31.5) / 22 }} className={className} />;
}

export function AccountLogo({ logo, size = 36, muted = false }: { logo: string; size?: number; muted?: boolean }) {
  return (
    <span className="grid shrink-0 place-items-center rounded-lg border border-line bg-white" style={{ width: size, height: size }} aria-hidden>
      {/* eslint-disable-next-line @next/next/no-img-element -- tiny static SVGs */}
      <img src={`/logos/${logo}.svg`} alt="" className={`size-[55%] object-contain ${muted ? "opacity-60 grayscale-[35%]" : ""}`} />
    </span>
  );
}

export function Dot({ tone }: { tone: "green" | "amber" | "red" | "gray" }) {
  const c = { green: "bg-emerald-500", amber: "bg-amber-500", red: "bg-red-500", gray: "bg-zinc-300" }[tone];
  return <span className={`inline-block size-1.5 shrink-0 rounded-full ${c}`} />;
}
