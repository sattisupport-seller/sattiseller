#!/usr/bin/env bash
# Подготовка сервера, выпуск и откат Satti одной командой (Ubuntu 24.04).
#   sudo ./deploy.sh setup <пользователь> <файл с публичным SSH-ключом>
#                         — один раз на чистом сервере: пользователь, вход только по ключу, без root и пароля,
#                           ufw (22, 80, 443), fail2ban, автообновления безопасности, синхронизация времени, Docker
#   ./deploy.sh up        — обновить до текущей версии: бэкап, миграции, запуск, проверка здоровья
#   ./deploy.sh rollback  — вернуться на предыдущий образ и откатить последнюю миграцию (после бэкапа)
# Все секреты — в deploy/.env (права 600). Ничего не запускает без docker compose.
set -euo pipefail

DEPLOY_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DEPLOY_DIR"

setup_server() {
  # 4.3: чистый Ubuntu 24.04. Запускать от root (sudo). Повторный запуск безопасен.
  local user="${1:?укажите имя пользователя}" keyfile="${2:?укажите файл с публичным SSH-ключом}"
  [ "$(id -u)" -eq 0 ] || { echo "setup запускается от root (sudo)" >&2; exit 1; }
  grep -q 'VERSION_ID="24.04"' /etc/os-release || echo "предупреждение: проверено только на Ubuntu 24.04" >&2
  grep -qE '^(ssh-ed25519|ssh-rsa|ecdsa-sha2-nistp256) ' "$keyfile" || { echo "в $keyfile нет публичного SSH-ключа" >&2; exit 1; }

  export DEBIAN_FRONTEND=noninteractive
  apt-get update -q
  apt-get install -y -q ufw fail2ban unattended-upgrades ca-certificates curl gnupg

  # отдельный пользователь, вход только по ключу
  id "$user" >/dev/null 2>&1 || adduser --disabled-password --gecos "" "$user"
  usermod -aG sudo "$user"
  install -d -m 700 -o "$user" -g "$user" "/home/$user/.ssh"
  install -m 600 -o "$user" -g "$user" "$keyfile" "/home/$user/.ssh/authorized_keys"

  # SSH: без root и без паролей (отдельный файл в sshd_config.d — переживает обновления пакета)
  cat > /etc/ssh/sshd_config.d/10-satti.conf <<'SSHD'
PermitRootLogin no
PasswordAuthentication no
KbdInteractiveAuthentication no
PubkeyAuthentication yes
MaxAuthTries 3
SSHD
  sshd -t && systemctl reload ssh

  # брандмауэр: только SSH, HTTP, HTTPS
  ufw default deny incoming
  ufw default allow outgoing
  ufw allow 22/tcp
  ufw allow 80/tcp
  ufw allow 443/tcp
  ufw --force enable

  # fail2ban: перебор SSH
  cat > /etc/fail2ban/jail.d/satti.local <<'F2B'
[sshd]
enabled = true
maxretry = 5
findtime = 10m
bantime = 1h
F2B
  systemctl enable --now fail2ban
  systemctl restart fail2ban

  # автоматические обновления безопасности
  cat > /etc/apt/apt.conf.d/20auto-upgrades <<'APT'
APT::Periodic::Update-Package-Lists "1";
APT::Periodic::Unattended-Upgrade "1";
APT
  systemctl enable --now unattended-upgrades

  # синхронизация времени (коды 2FA и сроки подписок зависят от часов)
  timedatectl set-ntp true
  systemctl enable --now systemd-timesyncd

  # Docker из официального репозитория
  if ! command -v docker >/dev/null 2>&1; then
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg -o /etc/apt/keyrings/docker.asc
    chmod a+r /etc/apt/keyrings/docker.asc
    echo "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.asc] https://download.docker.com/linux/ubuntu $(. /etc/os-release && echo "$VERSION_CODENAME") stable"       > /etc/apt/sources.list.d/docker.list
    apt-get update -q
    apt-get install -y -q docker-ce docker-ce-cli containerd.io docker-compose-plugin
  fi
  usermod -aG docker "$user"

  # секреты: только владелец файлов
  [ -f "$DEPLOY_DIR/.env" ] && chmod 600 "$DEPLOY_DIR/.env"
  [ -d "$DEPLOY_DIR/../server/data/secrets" ] && chmod 700 "$DEPLOY_DIR/../server/data/secrets"     && find "$DEPLOY_DIR/../server/data/secrets" -type f -exec chmod 600 {} +
  chown -R "$user:$user" "$DEPLOY_DIR/.."

  echo "готово. Проверьте вход: ssh $user@<IP> в НОВОМ окне, не закрывая текущее. Затем: ./deploy.sh up"
}

if [ "${1:-}" = "setup" ]; then
  shift
  setup_server "$@"
  exit 0
fi
COMPOSE=(docker compose -f docker-compose.yml --env-file .env)
STATE_DIR="$DEPLOY_DIR/state"
mkdir -p "$STATE_DIR"

need() { command -v "$1" >/dev/null 2>&1 || { echo "нужен $1" >&2; exit 1; }; }
need docker
docker compose version >/dev/null 2>&1 || { echo "нужен docker compose v2" >&2; exit 1; }
[ -f .env ] || { echo "нет deploy/.env (скопируйте .env.example и заполните)" >&2; exit 1; }
[ "$(stat -c %a .env 2>/dev/null || echo 600)" = "600" ] || { echo "deploy/.env должен иметь права 600: chmod 600 deploy/.env" >&2; exit 1; }

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
    echo "использование: $0 setup <пользователь> <ключ.pub> | up | rollback" >&2
    exit 2
    ;;
esac
