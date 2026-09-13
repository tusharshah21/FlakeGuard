import { FACTS } from '../data/run'
import { T } from '../timing'

/**
 * Three figures that back the claim above. Each is traceable to the repository's own data.
 *
 * Padding rule: the outer edges sit flush with the page gutter, so the first figure lines up with the headline
 * and the last one with the right margin, while the inner edges are padded away from the divider lines.
 */
export function ProofStrip() {
  return (
    <section className="grid gap-px border-y border-line bg-line sm:grid-cols-3">
      {FACTS.map(({ value, label }, i) => (
        <div
          key={label}
          className="rise bg-paper py-7 sm:px-6 sm:first:pl-0 sm:last:pr-0"
          style={{ animationDelay: `${T.strip + i * T.stripStep}ms` }}
        >
          <b className="block font-mono text-[27px] font-medium tracking-[-0.02em] tabular-nums">{value}</b>
          <span className="mt-[7px] block max-w-[34ch] text-[14.5px] text-muted">{label}</span>
        </div>
      ))}
    </section>
  )
}
