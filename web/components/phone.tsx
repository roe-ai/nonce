"use client";

import { Bell, BellOff, Share, SquarePlus, X } from "lucide-react";
import { useRouter } from "next/navigation";
import { useCallback, useEffect, useState, useSyncExternalStore } from "react";
import { addPushDevice, removePushDevice, sendTestPush, type PushSubscriptionJSON } from "@/app/actions";
import { Button } from "@/components/ui";

function urlBase64ToUint8Array(base64: string): Uint8Array<ArrayBuffer> {
  const padded = (base64 + "=".repeat((4 - (base64.length % 4)) % 4)).replace(/-/g, "+").replace(/_/g, "/");
  const raw = atob(padded);
  const out = new Uint8Array(new ArrayBuffer(raw.length));
  for (let i = 0; i < raw.length; i++) out[i] = raw.charCodeAt(i);
  return out;
}

function deviceName(): string {
  const ua = navigator.userAgent;
  const os = /iPhone/.test(ua) ? "iPhone" : /iPad/.test(ua) ? "iPad" : /Android/.test(ua) ? "Android" : /Mac/.test(ua) ? "Mac" : /Windows/.test(ua) ? "Windows" : "Browser";
  const app = /CriOS|Chrome/.test(ua) ? "Chrome" : /FxiOS|Firefox/.test(ua) ? "Firefox" : /Safari/.test(ua) ? "Safari" : "";
  return [os, app].filter(Boolean).join(" · ");
}

interface Phone {
  ios: boolean;
  installed: boolean;
  pushable: boolean;
}

const SERVER: Phone = { ios: false, installed: false, pushable: false };
let cached: Phone | null = null;

function readPhone(): Phone {
  if (!cached) {
    const ios = /iPad|iPhone|iPod/.test(navigator.userAgent);
    const installed = window.matchMedia("(display-mode: standalone)").matches || (navigator as { standalone?: boolean }).standalone === true;
    cached = { ios, installed, pushable: "serviceWorker" in navigator && "PushManager" in window && "Notification" in window };
  }
  return cached;
}

function usePhone(): Phone {
  return useSyncExternalStore(
    () => () => {},
    readPhone,
    () => SERVER,
  );
}

/** Registers the service worker, and refreshes the page when a push arrives while it's open. */
export function ServiceWorker() {
  const router = useRouter();
  useEffect(() => {
    if (!("serviceWorker" in navigator)) return;
    navigator.serviceWorker.register("/sw.js", { scope: "/", updateViaCache: "none" }).catch(() => {});
    const onMessage = (e: MessageEvent) => {
      if (e.data?.type === "privato:refresh" || e.data?.type === "valet:refresh" || e.data?.type === "nonce:refresh" || e.data?.type === "privaty:refresh") router.refresh();
    };
    navigator.serviceWorker.addEventListener("message", onMessage);
    return () => navigator.serviceWorker.removeEventListener("message", onMessage);
  }, [router]);
  return null;
}

function usePush(pushKey: string | null) {
  const [sub, setSub] = useState<PushSubscription | null | undefined>(undefined);
  const [permission, setPermission] = useState<NotificationPermission>("default");
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  useEffect(() => {
    if (!("serviceWorker" in navigator) || !("PushManager" in window)) return;
    let live = true;
    navigator.serviceWorker.ready
      .then((reg) => reg.pushManager.getSubscription())
      .then((s) => {
        if (!live) return;
        setSub(s);
        setPermission(Notification.permission);
      })
      .catch(() => live && setSub(null));
    return () => {
      live = false;
    };
  }, []);

  const turnOn = useCallback(async () => {
    if (!pushKey) return;
    setBusy(true);
    setError(null);
    try {
      const granted = await Notification.requestPermission();
      setPermission(granted);
      if (granted !== "granted") return;
      const reg = await navigator.serviceWorker.ready;
      const s =
        (await reg.pushManager.getSubscription()) ??
        (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: urlBase64ToUint8Array(pushKey) }));
      const failed = await addPushDevice(s.toJSON() as PushSubscriptionJSON, deviceName());
      if (failed) {
        await s.unsubscribe();
        setError(failed);
        return;
      }
      setSub(s);
    } catch {
      setError("Couldn't turn on notifications on this device.");
    } finally {
      setBusy(false);
    }
  }, [pushKey]);

  const turnOff = useCallback(async () => {
    if (!sub) return;
    setBusy(true);
    await removePushDevice(sub.endpoint);
    await sub.unsubscribe();
    setSub(null);
    setBusy(false);
  }, [sub]);

  return { sub, permission, error, busy, turnOn, turnOff };
}

function AddToHomeScreen({ ios }: { ios: boolean }) {
  return ios ? (
    <ol className="space-y-2 text-[13px] text-muted">
      <li className="flex items-center gap-2">
        <span className="grid size-6 shrink-0 place-items-center rounded-full bg-sidebar text-[11px] font-semibold text-ink">1</span>
        Tap <Share size={15} className="text-[#0a84ff]" /> Share in Safari
      </li>
      <li className="flex items-center gap-2">
        <span className="grid size-6 shrink-0 place-items-center rounded-full bg-sidebar text-[11px] font-semibold text-ink">2</span>
        Choose <SquarePlus size={15} /> Add to Home Screen
      </li>
      <li className="flex items-center gap-2">
        <span className="grid size-6 shrink-0 place-items-center rounded-full bg-sidebar text-[11px] font-semibold text-ink">3</span>
        Open Privato from your Home Screen and turn on notifications
      </li>
    </ol>
  ) : (
    <p className="text-[13px] text-muted">In your browser&apos;s menu, choose Install app or Add to Home screen.</p>
  );
}

/** Settings: put Privato on this phone and get a notification when an app needs your OK. */
export function PhoneSetup({ pushKey }: { pushKey: string | null }) {
  const phone = usePhone();
  const { sub, permission, error, busy, turnOn, turnOff } = usePush(pushKey);
  const [tested, setTested] = useState<string | null>(null);

  if (phone.ios && !phone.installed) {
    return (
      <div className="space-y-3">
        <p className="text-[13px] text-muted">On iPhone, notifications work once Privato is on your Home Screen.</p>
        <AddToHomeScreen ios />
      </div>
    );
  }
  if (!phone.pushable) return <p className="text-[13px] text-muted">This browser can&apos;t show notifications from privato.</p>;
  if (!pushKey) return <p className="text-[13px] text-muted">Notifications aren&apos;t set up on this server yet.</p>;
  if (permission === "denied") {
    return (
      <p className="text-[13px] text-muted">
        Notifications are blocked for Privato. Turn them on in your {phone.ios ? "iPhone's Settings → Notifications → Privato" : "browser's site settings"}, then come back.
      </p>
    );
  }
  if (sub === undefined) return <p className="text-[13px] text-faint">Checking this device…</p>;
  if (!sub) {
    return (
      <div className="space-y-2">
        <Button variant="primary" onClick={turnOn} disabled={busy}>
          <Bell size={14} /> {busy ? "Turning on…" : "Turn on notifications"}
        </Button>
        {error && <p className="text-[13px] text-red-600">{error}</p>}
      </div>
    );
  }
  return (
    <div className="flex flex-wrap items-center gap-2">
      <span className="mr-1 inline-flex items-center gap-1.5 text-[13px] font-medium text-emerald-700">
        <Bell size={14} /> On for this device
      </span>
      <Button
        onClick={async () => {
          const n = await sendTestPush();
          setTested(n ? "Sent. It should arrive in a few seconds." : "Couldn't reach this device. Turn notifications off and on again.");
        }}
      >
        Send a test
      </Button>
      <Button variant="ghost" onClick={turnOff} disabled={busy}>
        <BellOff size={14} /> Turn off
      </Button>
      {tested && <p className="w-full text-[13px] text-muted">{tested}</p>}
    </div>
  );
}

const DISMISSED = "privato:phone-nudge-dismissed";

/** Home, on a phone: a nudge to install Privato, then to turn on notifications. */
export function PhoneNudge({ pushKey }: { pushKey: string | null }) {
  const phone = usePhone();
  const { sub, busy, error, turnOn } = usePush(pushKey);
  const [dismissed, setDismissed] = useState(true);
  useEffect(() => {
    // localStorage only exists in the browser.
    // eslint-disable-next-line react-hooks/set-state-in-effect
    setDismissed(localStorage.getItem(DISMISSED) === "1");
  }, []);
  const mobile = phone.ios || /Android/.test(typeof navigator === "undefined" ? "" : navigator.userAgent);
  const needsInstall = mobile && !phone.installed;
  const needsPush = phone.installed && phone.pushable && !!pushKey && sub === null;
  if (dismissed || !(needsInstall || needsPush)) return null;
  return (
    <div className="pass-in relative rounded-2xl bg-white p-4 shadow-[0_10px_28px_-16px_rgba(60,40,20,0.35)] ring-1 ring-line md:hidden">
      <button
        aria-label="Dismiss"
        className="absolute top-2 right-2 grid size-10 place-items-center rounded-lg text-faint hover:bg-sidebar"
        onClick={() => {
          localStorage.setItem(DISMISSED, "1");
          setDismissed(true);
        }}
      >
        <X size={14} />
      </button>
      <p className="font-display text-[19px]">{needsInstall ? "Keep Privato on your phone" : "Get a tap when an app asks"}</p>
      <p className="mt-0.5 mb-3 text-[13px] text-muted">
        {needsInstall ? "Add it to your Home Screen to approve requests in one tap." : "Turn on notifications so requests reach you right away."}
      </p>
      {needsInstall ? (
        <AddToHomeScreen ios={phone.ios} />
      ) : (
        <>
          <Button variant="primary" onClick={turnOn} disabled={busy}>
            <Bell size={14} /> {busy ? "Turning on…" : "Turn on notifications"}
          </Button>
          {error && <p className="mt-2 text-[13px] text-red-600">{error}</p>}
        </>
      )}
    </div>
  );
}
