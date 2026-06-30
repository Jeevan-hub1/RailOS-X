#!/usr/bin/env bash
###############################################################################
# RailOS-X — Python test runner (per-service / focused runs)
#
# The full suite now also runs in one process from the repo root (`pytest`),
# but this wrapper is handy for running one or a few suites in ISOLATED pytest
# processes — useful when debugging cross-test state (Prometheus registries,
# sys.path-based imports in a few services, etc.).
#
# Usage:
#   ./scripts/run_tests.sh                 # run every suite (isolated processes)
#   ./scripts/run_tests.sh services/adapters/tests [more...]   # run a subset
#
# Env:
#   PYTEST   override the pytest invocation (default: "python -m pytest")
###############################################################################
set -uo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"
export PYTHONPATH="$REPO_ROOT${PYTHONPATH:+:$PYTHONPATH}"

PYTEST="${PYTEST:-python -m pytest}"

# Canonical list of isolated suites.
ALL_SUITES=(
  tests/pbt
  services/adapters/tests
  services/auth_middleware/tests
  services/defect_detector/tests
  services/delay_predictor/tests
  services/edge_node/buffer
  services/edge_node/heartbeat
  services/edge_node/tests
  services/edge_node/uploader
  services/federated_learning/tests
  services/kavach_advisory/tests
  services/maintenance_engine/tests
  services/marl_scheduler/tests
  services/pipeline/influxdb_writer/tests
  services/time_sync/tests
)

if [ "$#" -gt 0 ]; then
  SUITES=("$@")
else
  SUITES=("${ALL_SUITES[@]}")
fi

passed=()
failed=()
for suite in "${SUITES[@]}"; do
  echo "============================================================"
  echo ">> $suite"
  echo "============================================================"
  if $PYTEST "$suite" -q -p no:cacheprovider; then
    passed+=("$suite")
  else
    failed+=("$suite")
  fi
done

echo ""
echo "============================================================"
echo "Summary: ${#passed[@]} passed, ${#failed[@]} failed (of ${#SUITES[@]})"
if [ "${#failed[@]}" -gt 0 ]; then
  printf '  FAILED: %s\n' "${failed[@]}"
  exit 1
fi
echo "All suites passed."
