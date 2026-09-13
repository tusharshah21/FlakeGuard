import { FAILED_CELLS, RUN } from '../data/run'

/**
 * The hero's visual thesis: one real CI run drawn as its matrix cells. Thirty-two pass, two fail,
 * and the run is red — which is the whole argument for the product in one picture.
 */
export function MatrixPanel() {
  const passed = RUN.cells.length - FAILED_CELLS.length

  return (
    <figure className="m-0 rounded-xl border border-line bg-panel p-6 pb-5">
      <figcaption className="mb-[18px] flex items-baseline justify-between gap-4 font-mono text-xs text-muted">
        <span>
          run {RUN.id} · {RUN.repo}
        </span>
        <span>{RUN.cells.length} cells</span>
      </figcaption>

      <div
        className="grid grid-cols-9 gap-[7px]"
        role="img"
        aria-label={`${RUN.cells.length} matrix cells from one real CI run: ${passed} passed, ${FAILED_CELLS.length} failed.`}
      >
        {RUN.cells.map(([name, failed]) => (
          <div
            key={name}
            title={name}
            className={
              failed
                ? 'cell-fail aspect-square rounded-[3px] bg-fail'
                : 'aspect-square rounded-[3px] bg-pass opacity-55'
            }
          />
        ))}
      </div>

      <p className="mt-[18px] flex flex-wrap gap-[18px] border-t border-line pt-4 font-mono text-xs text-muted">
        <span className="flex items-center gap-2">
          <i className="inline-block size-[9px] rounded-[2px] bg-pass opacity-55" />
          {passed} passed
        </span>
        {FAILED_CELLS.map((name) => (
          <span key={name} className="flex items-center gap-2">
            <i className="inline-block size-[9px] rounded-[2px] bg-fail" />
            {name.replace('-latest', '').replace('-test-ci-notci1', '').replace('-test-', '-')}
          </span>
        ))}
      </p>

      <p className="mt-4 font-mono text-[13px] text-fail">conclusion: {RUN.conclusion}</p>
    </figure>
  )
}
