import { MessageSquare, Smartphone } from "lucide-react";
import { removePhone, signOut } from "@/app/actions";
import { OfflineHours } from "@/components/offline-hours";
import { PhoneSetup } from "@/components/phone";
import { PhoneForm } from "@/components/phone-form";
import { Button, Dot, List, PageHeader, Section } from "@/components/ui";
import { api, type User } from "@/lib/api";

export default async function SettingsPage() {
  const [me, notifications] = await Promise.all([
    api<User>("/admin/me"),
    api<{
      sms: boolean;
      verify: string;
      messages: string;
      push_key: string | null;
      push_devices: number;
    }>("/admin/notifications"),
  ]);

  return (
    <>
      <PageHeader title="Settings" />

      <Section title="Your account">
        <List>
          <div className="flex items-center gap-3.5 px-4 py-4">
            {me.picture ? (
              // eslint-disable-next-line @next/next/no-img-element -- Google profile photo
              <img
                src={me.picture}
                alt=""
                referrerPolicy="no-referrer"
                className="size-9 rounded-full"
              />
            ) : (
              <span className="grid size-9 place-items-center rounded-full bg-hover font-semibold text-muted">
                {(me.name ?? me.email).slice(0, 1).toUpperCase()}
              </span>
            )}
            <div className="min-w-0 flex-1">
              <p className="truncate font-medium">{me.name ?? me.email}</p>
              <p className="truncate text-[13px] text-muted">
                {me.email} · Google
              </p>
            </div>
            <form action={signOut}>
              <Button>Sign out</Button>
            </form>
          </div>
        </List>
      </Section>

      <Section title="Offline hours">
        <List>
          <OfflineHours
            start={me.offline_start}
            end={me.offline_end}
            timezone={me.timezone}
          />
        </List>
      </Section>

      <section id="phone" className="scroll-mt-20">
        <Section title="Notifications on this device">
          <List>
            <div className="px-4 py-4">
              <p className="mb-3 text-[13px] text-muted">
                Get a notification the moment an app asks for something, and
                allow or decline it right from your phone.
                {notifications.push_devices > 0 &&
                  ` On for ${notifications.push_devices} ${notifications.push_devices === 1 ? "device" : "devices"}.`}
              </p>
              <PhoneSetup pushKey={notifications.push_key} />
            </div>
          </List>
        </Section>
      </section>

      {notifications.sms && (
        <Section title="Text me when an app needs my OK">
          <List>
            <div className="px-4 py-4">
              <div className="mb-3 flex items-start gap-3.5">
                <span className="grid size-9 shrink-0 place-items-center rounded-lg border border-line bg-white text-muted">
                  {me.phone_verified_at ? (
                    <MessageSquare size={16} strokeWidth={1.8} />
                  ) : (
                    <Smartphone size={16} strokeWidth={1.8} />
                  )}
                </span>
                <div className="min-w-0 flex-1">
                  {me.phone_verified_at ? (
                    <>
                      <p className="font-medium">{me.phone}</p>
                      <p className="mt-0.5 flex items-center gap-1.5 text-[13px] text-muted">
                        <Dot tone="green" /> We&apos;ll text you to allow or
                        decline requests, and when we block something.
                      </p>
                    </>
                  ) : (
                    <>
                      <p className="font-medium">Add your phone</p>
                      <p className="mt-0.5 text-[13px] text-muted">
                        When an app asks for more than usual, you&apos;ll get a
                        text with a link to allow or decline it.
                      </p>
                    </>
                  )}
                </div>
                {me.phone_verified_at && (
                  <form action={removePhone}>
                    <Button variant="danger">Remove</Button>
                  </form>
                )}
              </div>
              {!me.phone_verified_at && <PhoneForm />}
              {notifications.messages !== "sms" && (
                <p className="mt-3 text-[12px] text-faint">
                  {notifications.messages === "dev"
                    ? "Texting isn't set up on this server yet, so codes and texts go to the server log."
                    : "Texting isn't available on this server yet."}
                </p>
              )}
            </div>
          </List>
        </Section>
      )}
    </>
  );
}
