#!/usr/bin/env bash
# К-33 Б5: репетиция обновления и отката БЕЗ сервера и без Docker — подменный docker пишет вызовы в журнал
# и отвечает как настоящий. Проверяет порядок шагов deploy.sh, а не сам Docker.
#   bash deploy/rehearse_rollback.sh
# Сценарии:
#   1) обновление сломано (/v1/health не отвечает) → автоматический откат: копия, миграции до ревизии до обновления,
#      предыдущий образ, проверка;
#   2) обновление прошло → откат вручную;
#   3) предыдущей версии нет → понятный отказ.
set -euo pipefail
SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/deploy.sh"
R="$(mktemp -d)"
trap 'rm -rf "$R"' EXIT
mkdir -p "$R/deploy/state" "$R/bin"
cp "$SRC" "$R/deploy/deploy.sh"
sed -i 's/sleep 5/sleep 0/' "$R/deploy/deploy.sh"
# права 600 у .env на Windows не выставить — в репетиции проверка прав отключена (на сервере она работает)
sed -i 's/^\[ "\$(stat -c %a .env.*$/: # проверка прав .env отключена в репетиции/' "$R/deploy/deploy.sh"
printf 'SATTI_IMAGE=satti-server:latest\n' > "$R/deploy/.env"
touch "$R/deploy/docker-compose.yml"

cat > "$R/bin/docker" <<'SHIM'
#!/usr/bin/env bash
echo "docker $*" >> "$REHEARSAL_DIR/log"
args="$*"
case "$args" in
  "compose version"*) exit 0 ;;
  *" ps -q app"*) echo "cid123" ;;
  *"alembic current"*) cat "$REHEARSAL_DIR/db_rev" ;;
  *"alembic upgrade head"*) echo "NEW_HEAD (head)" > "$REHEARSAL_DIR/db_rev" ;;
  *"alembic downgrade "*) echo "${args##*downgrade }" > "$REHEARSAL_DIR/db_rev" ;;
  "inspect "*) cat "$REHEARSAL_DIR/image_now" ;;
  *" build app"*) echo "sha256:new" > "$REHEARSAL_DIR/image_now" ;;
  "tag "*) echo "$2" > "$REHEARSAL_DIR/image_now" ;;
  *"urllib.request"*) [ "$(cat "$REHEARSAL_DIR/broken_image")" != "$(cat "$REHEARSAL_DIR/image_now")" ] ;;
esac
SHIM
chmod +x "$R/bin/docker"
export REHEARSAL_DIR="$R" PATH="$R/bin:$PATH"

reset() {
  : > "$R/log"
  echo "OLD_REV (head)" > "$R/db_rev"
  echo "sha256:old" > "$R/image_now"
  rm -f "$R/deploy/state/"*
  echo "sha256:old" > "$R/deploy/state/current_image"
}
check() { if [ "$2" = "$3" ]; then echo "  ОК: $1"; else echo "  ОШИБКА: $1 — ожидалось $3, есть $2"; exit 1; fi; }

echo "1) обновление сломано → автоматический откат"
reset; echo "sha256:new" > "$R/broken_image"
if bash "$R/deploy/deploy.sh" up >/dev/null 2>&1; then echo "  ОШИБКА: up должен завершиться ошибкой"; exit 1; fi
check "база вернулась к ревизии до обновления" "$(cat "$R/db_rev")" "OLD_REV"
check "работает предыдущий образ" "$(cat "$R/image_now")" "sha256:old"
check "перед откатом сделана копия" "$(grep -c 'backup.py create' "$R/log")" "2"

echo "2) обновление прошло → откат вручную"
reset; echo "none" > "$R/broken_image"
bash "$R/deploy/deploy.sh" up >/dev/null
check "после обновления — новый образ" "$(cat "$R/image_now")" "sha256:new"
bash "$R/deploy/deploy.sh" rollback >/dev/null
check "база вернулась к ревизии до обновления" "$(cat "$R/db_rev")" "OLD_REV"
check "работает предыдущий образ" "$(cat "$R/image_now")" "sha256:old"
check "current_image обновлён" "$(cat "$R/deploy/state/current_image")" "sha256:old"

echo "3) предыдущей версии нет → отказ"
reset; rm -f "$R/deploy/state/current_image"
if bash "$R/deploy/deploy.sh" rollback >/dev/null 2>&1; then echo "  ОШИБКА: откат без предыдущей версии"; exit 1; fi
echo "  ОК: откат отказался"
echo "репетиция пройдена"
