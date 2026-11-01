function Bar({ className }: { className: string }) {
  return <div className={`animate-pulse rounded-lg bg-[#ebe5da] ${className}`} />;
}

/** Shown the instant you switch tabs, while the page loads. */
export function PageSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading" className="space-y-6">
      <Bar className="h-9 w-56" />
      <div className="space-y-3">
        <Bar className="h-4 w-28" />
        <Bar className="h-20 w-full rounded-2xl" />
        <Bar className="h-20 w-full rounded-2xl" />
      </div>
      <div className="space-y-3">
        <Bar className="h-4 w-36" />
        <Bar className="h-32 w-full rounded-2xl" />
      </div>
    </div>
  );
}

export function HomeSkeleton() {
  return (
    <div aria-busy="true" aria-label="Loading" className="mx-auto flex max-w-[1600px] flex-col gap-5 p-4 md:p-7">
      <div className="space-y-2">
        <Bar className="h-10 w-72 max-w-full" />
        <Bar className="h-4 w-56" />
      </div>
      <div className="grid grid-cols-1 gap-6 lg:grid-cols-[1.1fr_1fr_1.1fr]">
        {[0, 1, 2].map((i) => (
          <div key={i} className="space-y-3">
            <Bar className="h-6 w-40" />
            <Bar className="h-40 w-full rounded-2xl" />
            <Bar className="h-28 w-full rounded-2xl" />
          </div>
        ))}
      </div>
    </div>
  );
}
