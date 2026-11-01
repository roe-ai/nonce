export default function PagesLayout({ children }: { children: React.ReactNode }) {
  return <div className="mx-auto max-w-[880px] px-5 py-8 md:px-8 md:py-12">{children}</div>;
}
