import { REPO } from '../data/run'

export function TopBar() {
  return (
    <header className="rise flex items-center justify-between gap-6 border-b border-line py-[22px]">
      <div className="flex flex-wrap items-baseline gap-[10px]">
        <span className="font-display text-[19px] font-extrabold tracking-[-0.02em]">FlakeGuard</span>
        <span className="font-mono text-xs text-muted">flaky-test triage for GitHub Actions + pytest</span>
      </div>
      <a
        href={REPO}
        className="hidden border-b border-transparent font-mono text-[13px] text-muted transition-colors hover:border-line hover:text-ink sm:inline"
      >
        github.com/tusharshah21/FlakeGuard →
      </a>
    </header>
  )
}
