#!/usr/bin/env bash
# Re-render the architecture diagram after editing docs/architecture.md.
set -euo pipefail
cd "$(dirname "$0")/.."
npx --yes @mermaid-js/mermaid-cli@latest -i docs/architecture.md -o "$(pwd)/docs/architecture.svg"
mv -f docs/architecture-1.svg docs/architecture.svg 2>/dev/null || true
echo "wrote docs/architecture.svg"
