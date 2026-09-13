import { REPO, REVERSAL_PR } from '../data/run'
import { T } from '../timing'
import { MatrixPanel } from './MatrixPanel'

export function Hero() {
  return (
    <main className="grid items-center gap-12 py-14 lg:grid-cols-[1.05fr_0.95fr] lg:gap-[72px] lg:pt-[76px] lg:pb-[84px]">
      <div>
        <p
          className="rise mb-[22px] font-mono text-[12.5px] tracking-[0.1em] text-muted uppercase"
          style={{ animationDelay: `${T.eyebrow}ms` }}
        >
          Autonomous CI triage
        </p>

        <h1
          className="rise font-display text-[clamp(42px,6vw,72px)] leading-[1.02] font-bold tracking-[-0.035em] text-balance"
          style={{ animationDelay: `${T.headline}ms` }}
        >
          Every cell is green.
          <br />
          {/* Turns red as the two failing cells land in the matrix beside it. */}
          The run is <span className="redden text-fail">red</span>.
        </h1>

        <p className="rise mt-6 max-w-[46ch] text-[19px] text-muted" style={{ animationDelay: `${T.sub}ms` }}>
          A 34-cell test matrix passes <b className="font-medium text-ink">94.4%</b> of the time per cell, and fails{' '}
          <b className="font-medium text-ink">162 of 191</b> runs overall. FlakeGuard finds the flakes hiding in that
          gap, quarantines them, and opens the pull request to let them back in when they recover.
        </p>

        <div className="rise mt-[34px] flex flex-wrap gap-3" style={{ animationDelay: `${T.actions}ms` }}>
          <a
            href={REPO}
            className="rounded-[7px] bg-accent px-5 py-[11px] text-[15px] font-medium text-accent-ink transition-[filter,transform] duration-200 hover:-translate-y-px hover:brightness-110 focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-accent"
          >
            Read the code
          </a>
          <a
            href={REVERSAL_PR}
            className="rounded-[7px] border border-line px-5 py-[11px] text-[15px] font-medium text-ink transition-[background-color,transform] duration-200 hover:-translate-y-px hover:bg-panel focus-visible:outline-2 focus-visible:outline-offset-[3px] focus-visible:outline-accent"
          >
            See it reverse itself
          </a>
        </div>
      </div>

      <MatrixPanel />
    </main>
  )
}
