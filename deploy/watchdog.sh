#!/usr/bin/env bash
# Внешний сторож «сервер не отвечает» (MASTER_PLAN 3.10 и 4.2).
# Запускается НЕ на сервере Satti: на втором сервере, у другого хостинга, или на любом Linux-компьютере с cron.
# Изнутри упавшего сервера письмо не отправить — поэтому проверка снаружи.
#
# cron (каждые 5 минут):  */5 * * * * /opt/satti-watchdog/watchdog.sh
# Переменные (файл /opt/satti-watchdog/watchdog.env, права 600):
#   SATTI_HEALTH_URL=https://api.<домен>/v1/health
#   ALERT_EMAIL=<почта владельца>
#   ALERT_FROM=watchdog@<домен>
#   SMTP_URL=smtps://smtp.<сервис>:465   SMTP_USER=...   SMTP_PASSWORD=...
# Письмо уходит после двух неудачных проверок подряд (10 минут) и ещё одно — когда сервер снова отвечает.
set -euo pipefail

DIR="$(cd "$(dirname "$0")" && pwd)"
# shellcheck disable=SC1091
[ -f "$DIR/watchdog.env" ] && . "$DIR/watchdog.env"
: "${SATTI_HEALTH_URL:?не задан SATTI_HEALTH_URL}"
: "${ALERT_EMAIL:?не задан ALERT_EMAIL}"
STATE="$DIR/state"
FAILS_FILE="$STATE/fails"
DOWN_FILE="$STATE/down"
mkdir -p "$STATE"

send_mail() {
  local subject="$1" body="$2"
  if [ -n "${SMTP_URL:-}" ]; then
    printf 'From: %s\r\nTo: %s\r\nSubject: %s\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n%s\r\n' \
      "${ALERT_FROM:-watchdog@localhost}" "$ALERT_EMAIL" "$subject" "$body" |
      curl -sS --ssl-reqd --url "$SMTP_URL" --user "${SMTP_USER}:${SMTP_PASSWORD}" \
        --mail-from "${ALERT_FROM:-watchdog@localhost}" --mail-rcpt "$ALERT_EMAIL" --upload-file - ||
      echo "watchdog: письмо не отправлено" >&2
  else
    echo "watchdog: $subject — $body" >&2  # без SMTP: cron пришлёт вывод на почту пользователя
  fi
}

if curl -fsS --max-time 15 "$SATTI_HEALTH_URL" | grep -q '"status"'; then
  echo 0 > "$FAILS_FILE"
  if [ -f "$DOWN_FILE" ]; then
    rm -f "$DOWN_FILE"
    send_mail "Satti: сервер снова отвечает" "Проверка $SATTI_HEALTH_URL прошла в $(date -u '+%Y-%m-%d %H:%M UTC')."
  fi
  exit 0
fi

fails=$(( $(cat "$FAILS_FILE" 2>/dev/null || echo 0) + 1 ))
echo "$fails" > "$FAILS_FILE"
if [ "$fails" -ge 2 ] && [ ! -f "$DOWN_FILE" ]; then
  date -u '+%Y-%m-%d %H:%M UTC' > "$DOWN_FILE"
  send_mail "Satti: сервер не отвечает" \
    "Адрес $SATTI_HEALTH_URL не отвечает $fails проверки подряд (около $((fails * 5)) минут). Что делать — OPERATIONS.md, «Сервер не отвечает»."
fi
