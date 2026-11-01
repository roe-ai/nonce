"use client";

import { Check } from "lucide-react";
import { useState, useTransition } from "react";
import { chooseAccounts } from "@/app/actions";

/** Which of your accounts a waiting request reads. The app suggests; you tap to change before approving. */
export function AccountChips({ grantId, options, selected }: { grantId: string; options: { id: string; account: string }[]; selected: string[] }) {
  const [chosen, setChosen] = useState(selected);
  const [saving, start] = useTransition();

  function toggle(id: string) {
    const next = chosen.includes(id) ? chosen.filter((x) => x !== id) : [...chosen, id];
    if (!next.length) return;
    setChosen(next);
    start(() => chooseAccounts(grantId, next));
  }

  return (
    <span role="group" aria-label="Accounts it will read" className={`mt-1 flex flex-wrap gap-1.5 ${saving ? "opacity-70" : ""}`}>
      {options.map((o) => {
        const on = chosen.includes(o.id);
        const last = on && chosen.length === 1;
        return (
          <button
            key={o.id}
            type="button"
            aria-pressed={on}
            disabled={last}
            title={last ? "It needs at least one account" : on ? `Don't read ${o.account}` : `Also read ${o.account}`}
            onClick={() => toggle(o.id)}
            className={`inline-flex h-8 max-w-full items-center gap-1 rounded-full px-2.5 text-[12px] ring-1 transition-colors sm:h-6 sm:px-2 sm:text-[11.5px] ${
              on ? "bg-white text-ink ring-ink/40" : "text-faint ring-line hover:text-muted"
            } disabled:cursor-default`}
          >
            {on && <Check size={11} strokeWidth={2.5} className="shrink-0" />}
            <span className="truncate">{o.account}</span>
          </button>
        );
      })}
    </span>
  );
}
