#!/usr/bin/env bash
# Runs the pipeline described in docs/testing.md#integration-tests: fresh
# db -> migrate -> run the pipeline tests (real Hyperliquid data),
# then always tears the stack (and its database) back down, pass or fail.
set -euo pipefail

cd "$(dirname "$0")/.."

COMPOSE_FILE="docker/test/compose.yaml"

cleanup() {
  echo "--- tearing down: docker compose -f $COMPOSE_FILE down -v ---"
  docker compose -f "$COMPOSE_FILE" down -v
}
trap cleanup EXIT

echo "--- building and starting the test pipeline ---"
docker compose -f "$COMPOSE_FILE" up --build -d

container_id=$(docker compose -f "$COMPOSE_FILE" ps -q e2e-tests)
if [ -z "$container_id" ]; then
  echo "e2e-tests never started - an earlier step (postgres/migrate) failed" >&2
  docker compose -f "$COMPOSE_FILE" logs
  exit 1
fi

# Stream logs live instead of going silent until the container exits -
# e2e-tests logs per-step progress (see docs/testing.md), which
# is only useful if you can see it while it's happening.
docker compose -f "$COMPOSE_FILE" logs -f e2e-tests &
logs_pid=$!

exit_code="$(docker wait "$container_id")"

kill "$logs_pid" 2>/dev/null || true
wait "$logs_pid" 2>/dev/null || true

exit "$exit_code"
