"use client";

import { useActionState } from "react";
import { sendPhoneCode, verifyPhoneCode, type PhoneState } from "@/app/actions";
import { Button } from "@/components/ui";

const input = "h-9 w-full rounded-lg border border-line bg-white px-3 text-[14px] outline-none focus:border-ink";

export function PhoneForm() {
  const [sent, send, sending] = useActionState<PhoneState, FormData>(sendPhoneCode, { step: "number" });
  const [checked, check, checking] = useActionState<PhoneState, FormData>(verifyPhoneCode, { step: "code" });

  if (checked.step === "done") {
    return <p className="text-[13px] text-emerald-700">Your number is verified.</p>;
  }

  if (sent.step === "code" || checked.phone) {
    const phone = checked.phone ?? sent.phone;
    return (
      <form action={check} className="space-y-2.5">
        <p className="text-[13px] text-muted">We texted a code to {phone}.</p>
        <input type="hidden" name="phone" value={phone} />
        <div className="flex gap-2">
          <input name="code" inputMode="numeric" autoComplete="one-time-code" placeholder="6-digit code" autoFocus className={input} />
          <Button variant="primary" disabled={checking}>
            {checking ? "Checking…" : "Verify"}
          </Button>
        </div>
        {checked.error && <p className="text-[12px] text-red-600">{checked.error}</p>}
        <button name="intent" value="resend" className="text-[12px] text-muted underline decoration-line underline-offset-4 hover:text-ink">
          Send a new code
        </button>
      </form>
    );
  }

  return (
    <form action={send} className="space-y-2.5">
      <div className="flex gap-2">
        <input name="phone" type="tel" autoComplete="tel" placeholder="(415) 555-0100" defaultValue={sent.phone} className={input} />
        <Button variant="primary" disabled={sending}>
          {sending ? "Sending…" : "Send code"}
        </Button>
      </div>
      {sent.error && <p className="text-[12px] text-red-600">{sent.error}</p>}
    </form>
  );
}
