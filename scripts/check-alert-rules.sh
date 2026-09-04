#!/usr/bin/env bash
# Run the alert-rule unit tests.
#
# WHY THIS IS A GATE AND NOT A ONE-OFF. An alert rule that cannot fire is
# indistinguishable from a healthy system, and this repository has collected a
# list of checks that were green because they tested nothing. The obvious way to
# prove a rule fires is to break something and watch -- that was done once, on a
# rule with `severity: critical` and a live e-mail receiver, and it delivered a
# false alert to a real mailbox. `promtool test rules` establishes the same
# property against synthetic series, offline, with no notification path in
# existence.
#
# Uses the pinned Prometheus image rather than a promtool on PATH: the tests must
# be evaluated by the same version that evaluates the rules in production.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
# Digest copied from compose/observability.yml, not from a registry lookup: the
# tests must be evaluated by the SAME build that evaluates the rules in
# production. If the two ever drift, this is the line to change.
IMAGE="prom/prometheus:v2.55.1@sha256:2659f4c2ebb718e7695cb9b25ffa7d6be64db013daba13e05c875451cf51b0d3"
TESTS_DIR="$ROOT/observability/prometheus/rule-tests"

shopt -s nullglob
tests=("$TESTS_DIR"/*.test.yml)
shopt -u nullglob

# A run that finds no test files and reports success is the exact defect this
# script exists to prevent, so it is refused explicitly.
if [ ${#tests[@]} -eq 0 ]; then
  echo "check-alert-rules: FAIL - no *.test.yml found in ${TESTS_DIR#"$ROOT"/}; nothing was tested"
  exit 1
fi

names=()
for t in "${tests[@]}"; do names+=("$(basename "$t")"); done

if ! out=$(docker run --rm \
      -v "$ROOT/observability/prometheus:/p:ro" \
      -w /p/rule-tests \
      --entrypoint promtool \
      "$IMAGE" test rules "${names[@]}" 2>&1); then
  echo "$out"
  # Deliberately does not claim WHY. This same path catches a failed assertion,
  # an unreachable image and a malformed test file, and asserting a cause it has
  # not established is how a message sends someone to the wrong place.
  echo "check-alert-rules: FAIL - promtool test rules did not pass; see the output above"
  exit 1
fi

echo "check-alert-rules: OK - ${#tests[@]} rule test file(s) pass (${names[*]})"
