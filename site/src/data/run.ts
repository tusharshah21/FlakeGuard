/**
 * One real scheduled run of dask/distributed's Tests workflow, as FlakeGuard ingested it.
 * 34 pooled matrix cells; two of them failed, so the whole run is red.
 *
 * Source: flakeguard.db, run_cells where run_id = 34568247988.
 */
export const RUN = {
  id: '34568247988',
  repo: 'dask/distributed',
  conclusion: 'failure',
  /** Cell names in the order the matrix renders, marked with whether that cell's job failed. */
  cells: [
    ['macos-latest-py314-test-ci-ci1', false],
    ['macos-latest-py314-test-ci-notci1', false],
    ['ubuntu-24.04-arm-py310-test-ci-ci1', false],
    ['ubuntu-24.04-arm-py310-test-ci-notci1', false],
    ['ubuntu-24.04-arm-py311-test-ci-ci1', false],
    ['ubuntu-24.04-arm-py311-test-ci-notci1', false],
    ['ubuntu-24.04-arm-py312-test-ci-ci1', false],
    ['ubuntu-24.04-arm-py312-test-ci-notci1', false],
    ['ubuntu-24.04-arm-py313-test-ci-ci1', false],
    ['ubuntu-24.04-arm-py313-test-ci-notci1', false],
    ['ubuntu-24.04-arm-py314-test-ci-ci1', false],
    ['ubuntu-24.04-arm-py314-test-ci-notci1', false],
    ['ubuntu-latest-py310-test-ci-ci1', false],
    ['ubuntu-latest-py310-test-ci-notci1', false],
    ['ubuntu-latest-py310-test-noqueue-ci1', false],
    ['ubuntu-latest-py310-test-noqueue-notci1', true],
    ['ubuntu-latest-py311-test-ci-ci1', false],
    ['ubuntu-latest-py311-test-ci-notci1', false],
    ['ubuntu-latest-py312-test-ci-ci1', false],
    ['ubuntu-latest-py312-test-ci-notci1', false],
    ['ubuntu-latest-py313-test-ci-ci1', false],
    ['ubuntu-latest-py313-test-ci-notci1', false],
    ['ubuntu-latest-py314-test-ci-ci1', false],
    ['ubuntu-latest-py314-test-ci-notci1', false],
    ['windows-latest-py310-test-ci-ci1', false],
    ['windows-latest-py310-test-ci-notci1', false],
    ['windows-latest-py311-test-ci-ci1', false],
    ['windows-latest-py311-test-ci-notci1', false],
    ['windows-latest-py312-test-ci-ci1', false],
    ['windows-latest-py312-test-ci-notci1', false],
    ['windows-latest-py313-test-ci-ci1', false],
    ['windows-latest-py313-test-ci-notci1', true],
    ['windows-latest-py314-test-ci-ci1', false],
    ['windows-latest-py314-test-ci-notci1', false],
  ] as const satisfies readonly (readonly [string, boolean])[],
}

export const FAILED_CELLS = RUN.cells.filter(([, failed]) => failed).map(([name]) => name)

/** Figures quoted on the page. Each one is traceable; see the README of the main repo. */
export const FACTS = [
  {
    value: '704,323',
    label: 'test observations ingested across 89 days of real CI history',
  },
  {
    value: '0',
    label: 'numbers invented by the model across 80 classifier outputs, checked mechanically',
  },
  {
    value: '35 runs',
    label: 'of clean passes before the agent reopens a test it quarantined',
  },
] as const

export const REPO = 'https://github.com/tusharshah21/FlakeGuard'
export const REVERSAL_PR = `${REPO}/pull/7`
