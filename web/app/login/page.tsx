import { signInWithGoogle } from "@/app/actions";
import { BrandMark } from "@/components/ui";

function GoogleG() {
  return (
    <svg viewBox="0 0 48 48" width="18" height="18" aria-hidden>
      <path fill="#FFC107" d="M43.6 20.5H42V20H24v8h11.3C33.7 32.7 29.2 36 24 36c-6.6 0-12-5.4-12-12s5.4-12 12-12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 12.9 4 4 12.9 4 24s8.9 20 20 20 20-8.9 20-20c0-1.3-.1-2.4-.4-3.5z" />
      <path fill="#FF3D00" d="M6.3 14.7l6.6 4.8C14.7 15.1 19 12 24 12c3.1 0 5.8 1.2 7.9 3.1l5.7-5.7C34 6.1 29.3 4 24 4 16.3 4 9.7 8.3 6.3 14.7z" />
      <path fill="#4CAF50" d="M24 44c5.2 0 9.9-2 13.4-5.2l-6.2-5.2C29.2 35.1 26.7 36 24 36c-5.2 0-9.6-3.3-11.3-7.9l-6.5 5C9.5 39.6 16.2 44 24 44z" />
      <path fill="#1976D2" d="M43.6 20.5H42V20H24v8h11.3c-.8 2.2-2.2 4.2-4.1 5.6l6.2 5.2C37 39.2 44 34 44 24c0-1.3-.1-2.4-.4-3.5z" />
    </svg>
  );
}

export default async function LoginPage({ searchParams }: { searchParams: Promise<{ error?: string; next?: string }> }) {
  const { error, next } = await searchParams;
  return (
    <div className="grid min-h-screen place-items-center px-4">
      <div className="w-full max-w-[340px] text-center">
        <BrandMark height={24} className="mx-auto mb-6" />
        <h1 className="text-[20px] font-semibold tracking-[-0.01em]">Welcome to Privato</h1>
        <p className="mt-1.5 text-[13px] text-muted">AI sees what it needs. Nothing else.</p>
        <form action={signInWithGoogle} className="mt-7">
          {next && <input type="hidden" name="next" value={next} />}
          <button className="inline-flex h-10 w-full items-center justify-center gap-2.5 rounded-lg border border-line bg-white text-[14px] font-medium shadow-[0_1px_2px_rgba(0,0,0,0.04)] transition-colors hover:bg-sidebar">
            <GoogleG /> Continue with Google
          </button>
        </form>
        {error && (
          <p className="mt-3 text-[13px] text-red-600">{error === "cancelled" ? "Sign-in was cancelled. Try again when you're ready." : error}</p>
        )}
        <p className="mt-6 text-[12px] text-faint">New here? This creates your account. Signing in only shares your name and email.</p>
      </div>
    </div>
  );
}
