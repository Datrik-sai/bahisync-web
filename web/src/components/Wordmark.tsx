import Link from "next/link";

/** Wordmark with the accountant's double underline, the mark for a total that ties. */
export function Wordmark({ href = "/" }: { href?: string }) {
  return (
    <Link href={href} className="group inline-flex flex-col leading-none" aria-label="BahiSync home">
      <span className="text-[1.35rem] font-[750] tracking-[-0.02em] text-ink">BahiSync</span>
      <span aria-hidden className="mt-[3px] flex flex-col gap-[2px]">
        <span className="block h-[1.5px] w-full bg-ledger" />
        <span className="block h-[1.5px] w-full bg-ledger" />
      </span>
    </Link>
  );
}

export function SiteHeader({ appLink = true, wide = false }: { appLink?: boolean; wide?: boolean }) {
  return (
    <header className={`mx-auto flex ${wide ? "max-w-[90rem]" : "max-w-6xl"} items-center justify-between px-5 py-5 sm:px-8`}>
      <Wordmark />
      <nav className="flex items-center gap-5 text-[0.95rem] text-ink-soft">
        <Link href="/#how" className="hidden hover:text-ink sm:inline">How it works</Link>
        <Link href="/#data" className="hidden hover:text-ink sm:inline">Your data</Link>
        <Link href="/#pricing" className="hidden hover:text-ink sm:inline">Pricing</Link>
        {appLink && (
          <Link href="/app" className="rounded-md bg-ink px-4 py-2 font-semibold text-white hover:bg-[#121c40]">
            Convert a statement
          </Link>
        )}
      </nav>
    </header>
  );
}
