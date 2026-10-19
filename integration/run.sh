#!/usr/bin/env bash
# Runs plane_autojoin inside Plane's real backend image (compose.yml):
# migrates a fresh database, then signs users up through Plane's own
# Adapter.complete_login_or_signup() in each scenario of scenario.py.
# Needs Docker with the compose plugin. Removes its containers on exit.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"
compose() { docker compose -f compose.yml "$@"; }
trap 'compose down -v --remove-orphans >/dev/null 2>&1 || true' EXIT

compose pull --quiet
compose up -d --wait db redis

echo "--- migrate"
compose run --rm -T backend sh -c 'python manage.py wait_for_db && python manage.py migrate --no-input' >/dev/null

# scenario NAME [ENV=VALUE...]: one backend process per scenario, because
# plane_autojoin reads its configuration once, at start-up.
scenario() {
    local name="$1"
    shift
    local args=()
    for kv in "$@"; do args+=(-e "$kv"); done
    echo "--- scenario: $name"
    compose run --rm -T -e "SCENARIO=$name" ${args[@]+"${args[@]}"} backend \
        python manage.py shell --no-imports < scenario.py
}

scenario domains \
    PLANE_AUTOJOIN_WORKSPACE_SLUG=acme \
    PLANE_AUTOJOIN_EMAIL_DOMAINS=example.com
scenario trust_all \
    PLANE_AUTOJOIN_WORKSPACE_SLUG=lab \
    PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS=true \
    ENABLE_EMAIL_PASSWORD=0 ENABLE_MAGIC_LINK_LOGIN=0
scenario trust_all_magic_code_on \
    PLANE_AUTOJOIN_WORKSPACE_SLUG=lab2 \
    PLANE_AUTOJOIN_TRUST_ALL_VERIFIED_EMAILS=true \
    ENABLE_EMAIL_PASSWORD=0 ENABLE_MAGIC_LINK_LOGIN=1
scenario off

echo "OK - all scenarios passed"
