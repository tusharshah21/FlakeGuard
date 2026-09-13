/**
 * The page-load sequence, in milliseconds. Kept in one place so the headline, the matrix and the verdict line
 * stay in step: the greens fill, the two failures land, the word "red" turns with them, the verdict follows.
 *
 * Nothing here gates visibility — these are animation delays only. See the comment in index.css.
 */
export const T = {
  /** Text blocks, in the order they settle. */
  eyebrow: 0,
  headline: 80,
  sub: 200,
  actions: 300,
  panel: 180,

  /** Matrix: each passing cell follows the previous one. */
  cellStart: 420,
  cellStep: 13,

  /** Both failures land together, after every passing cell has arrived. */
  failLand: 1450,

  /** Legend and verdict close the sequence. */
  legend: 1700,
  verdict: 1850,
  strip: 700,
  stripStep: 90,
} as const

/** Animation delay for a cell at `index`, given whether it is one of the failures. */
export function cellDelay(index: number, failed: boolean): string {
  return `${failed ? T.failLand : T.cellStart + index * T.cellStep}ms`
}
