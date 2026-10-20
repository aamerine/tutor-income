#!/usr/bin/env bash
# Build, run and test the Tutor Income Planner in containers.
# Uses podman if available, else docker. Override with ENGINE=docker.
set -euo pipefail
cd "$(dirname "$0")"

ENGINE="${ENGINE:-$(command -v podman >/dev/null && echo podman || echo docker)}"
IMAGE=localhost/tutor-income:latest
TEST_IMAGE=localhost/tutor-income-test:latest
E2E_IMAGE=localhost/tutor-income-e2e:latest
NAME=tutor-income
VOLUME=tutor-income-data
PORT="${PORT:-8080}"
BIND="${BIND:-127.0.0.1}" # set BIND=0.0.0.0 to reach it from other devices on your network

build_args=()
[[ "$ENGINE" == podman ]] && build_args+=(--format docker) # keeps HEALTHCHECK

build() {
  "$ENGINE" build "${build_args[@]}" --target runtime -t "$IMAGE" .
}

start() {
  build
  "$ENGINE" rm -f "$NAME" >/dev/null 2>&1 || true
  "$ENGINE" run -d --name "$NAME" \
    -p "$BIND:$PORT:8000" \
    -v "$VOLUME:/data" \
    --restart always \
    "$IMAGE" >/dev/null
  echo "Running at http://localhost:$PORT  (data in volume '$VOLUME')"
}

stop() {
  "$ENGINE" rm -f "$NAME" >/dev/null && echo "Stopped. Data is kept in volume '$VOLUME'."
}

unit_tests() {
  "$ENGINE" build "${build_args[@]}" --target test -t "$TEST_IMAGE" .
  "$ENGINE" run --rm "$TEST_IMAGE" "$@"
}

e2e_tests() {
  build
  "$ENGINE" build "${build_args[@]}" -f Dockerfile.e2e -t "$E2E_IMAGE" .
  local net="tutor-e2e-$$" app="tutor-e2e-app-$$"
  # shellcheck disable=SC2064
  trap "'$ENGINE' rm -f '$app' >/dev/null 2>&1; '$ENGINE' network rm '$net' >/dev/null 2>&1" EXIT
  "$ENGINE" network create "$net" >/dev/null
  # No volume: every e2e run starts from an empty database.
  "$ENGINE" run -d --name "$app" --network "$net" "$IMAGE" >/dev/null
  for _ in $(seq 60); do
    if "$ENGINE" exec "$app" python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)" 2>/dev/null; then
      break
    fi
    sleep 0.5
  done
  mkdir -p test-results
  "$ENGINE" run --rm --network "$net" --ipc=host \
    -e E2E_BASE_URL="http://$app:8000" \
    -v "$PWD/test-results:/e2e/test-results:Z" \
    "$E2E_IMAGE" pytest tests/e2e --output test-results --screenshot only-on-failure "$@"
}

case "${1:-}" in
  build) build ;;
  start) start ;;
  stop) stop ;;
  logs) "$ENGINE" logs -f "$NAME" ;;
  test) shift; unit_tests "$@" ;;
  e2e) shift; e2e_tests "$@" ;;
  test-all) unit_tests && e2e_tests ;;
  *)
    cat <<EOF
Usage: ./run.sh <command>
  start      build the image and run the app on http://localhost:$PORT
  stop       stop the app (data is kept)
  logs       follow the app logs
  build      build the app image only
  test       run unit + integration tests in a container (extra args go to pytest)
  e2e        run browser end-to-end tests against a fresh app container
  test-all   test, then e2e
Environment: ENGINE=podman|docker  PORT=8080  BIND=127.0.0.1
EOF
    exit 1
    ;;
esac
