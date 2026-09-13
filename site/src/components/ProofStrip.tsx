import { FACTS } from '../data/run'

/** Three figures that back the claim above. Each is traceable to the repository's own data. */
export function ProofStrip() {
  return (
    <section className="grid gap-px border-y border-line bg-line sm:grid-cols-3">
      {FACTS.map(({ value, label }) => (
        <div key={label} className="bg-paper px-6 pt-[26px] pb-7 sm:px-0 sm:first:pl-0">
          <b className="block font-mono text-[27px] font-medium tracking-[-0.02em] tabular-nums">{value}</b>
          <span className="mt-[7px] block max-w-[34ch] text-[14.5px] text-muted">{label}</span>
        </div>
      ))}
    </section>
  )
}
