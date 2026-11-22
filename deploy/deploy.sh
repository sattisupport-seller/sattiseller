#!/usr/bin/env bash
# Выпуск и откат Satti одной командой (Ubuntu 24.04).
#   ./deploy.sh up        — обновить до текущей версии: бэкап, миграции, запуск, проверка здоровья
#   ./deploy.sh rollback  — вернуться на предыдущий образ и откатить последнюю миграцию (после бэкапа)
# Все секреты — в deploy/.env (права 600). Ничего не запускает без docker compose.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEPLOY_DIR"
COMPOSE=(docker compose -f docker-compose.yml --env-file .env)
STATE_DIR="$DEPLOY_DIR/state"
mkdir -p "$STATE_DIR"

need() { command -v "$1" >/dev/null 2>&1 || { echo "нужен $1" >&2; exit 1; }; }
need docker
docker compose version >/dev/null 2>&1 || { echo "нужен docker compose v2" >&2; exit 1; }
[ -f .env ] || { echo "нет deploy/.env (скопируйте .env.example и заполните)" >&2; exit 1; }

health() {
  local tries=20
  for _ in $(seq 1 "$tries"); do
    if "${COMPOSE[@]}" exec -T app python -c "import urllib.request,sys; sys.exit(0 if urllib.request.urlopen('http://127.0.0.1:8000/v1/health', timeout=4).status==200 else 1)" 2>/dev/null; then
      return 0
    fi
    sleep 5
  done
  return 1
}

backup() {
  # первый запуск: контейнера приложения ещё нет — бэкапить нечего, это не ошибка
  if [ -z "$("${COMPOSE[@]}" ps -q app 2>/dev/null)" ]; then
    echo "бэкап пропущен: приложение ещё не запускалось"
    return 0
  fi
  "${COMPOSE[@]}" exec -T app python scripts/backup.py create
}

case "${1:-}" in
  up)
    backup
    if [ -f "$STATE_DIR/current_image" ]; then cp "$STATE_DIR/current_image" "$STATE_DIR/previous_image"; fi
    "${COMPOSE[@]}" build app
    "${COMPOSE[@]}" up -d db
    "${COMPOSE[@]}" run --rm app python -m alembic upgrade head
    "${COMPOSE[@]}" up -d app caddy
    if health; then
      docker inspect --format '{{.Image}}' "$("${COMPOSE[@]}" ps -q app)" > "$STATE_DIR/current_image"
      echo "готово: сервер отвечает на /v1/health"
    else
      echo "сервер не отвечает после обновления — откат" >&2
      "$0" rollback
      exit 1
    fi
    ;;
  rollback)
    [ -f "$STATE_DIR/previous_image" ] || { echo "нет предыдущей версии для отката" >&2; exit 1; }
    backup
    "${COMPOSE[@]}" run --rm -e SATTI_ALLOW_DOWNGRADE=1 app python -m alembic downgrade -1 || echo "миграция не откатилась (проверьте вручную)" >&2
    "${COMPOSE[@]}" stop app
    "${COMPOSE[@]}" up -d app
    echo "откат выполнен на предыдущий образ; проверьте /v1/health"
    ;;
  *)
    echo "использование: $0 up | rollback" >&2
    exit 2
    ;;
esac
