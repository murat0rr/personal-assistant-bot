#!/usr/bin/env bash
# Первичная настройка чистого Ubuntu-сервера под этот проект.
# Идемпотентно — можно запускать повторно, если что-то прервалось.
#
# Использование (по SSH на сервере, от root):
#   ./setup_server.sh git@github.com:<user>/assistant.git
set -euo pipefail

REPO_URL="${1:?Укажи URL git-репозитория первым аргументом}"
APP_DIR="/opt/assistant"

echo "== Docker =="
if ! command -v docker >/dev/null 2>&1; then
	curl -fsSL https://get.docker.com | sh
else
	echo "Docker уже установлен, пропускаю"
fi

echo "== git =="
apt-get update -qq
apt-get install -y -qq git

echo "== swap 2G (подстраховка от OOM при пересборке образов) =="
if [ -f /swapfile ]; then
	echo "/swapfile уже существует, пропускаю"
else
	fallocate -l 2G /swapfile
	chmod 600 /swapfile
	mkswap /swapfile
	swapon /swapfile
	echo "/swapfile none swap sw 0 0" >>/etc/fstab
fi

echo "== ufw (открываю только SSH/HTTP/HTTPS) =="
apt-get install -y -qq ufw
ufw allow OpenSSH
ufw allow 80/tcp
ufw allow 443/tcp
ufw --force enable

echo "== Клонирование репозитория =="
if [ -d "$APP_DIR/.git" ]; then
	echo "$APP_DIR уже существует, пропускаю клонирование"
else
	git clone "$REPO_URL" "$APP_DIR"
fi

cat <<'EOF'

Готово. Дальше вручную:
  1. Скопировать .env на сервер: scp .env root@<IP>:/opt/assistant/.env
  2. cd /opt/assistant
  3. docker compose run --rm bot uv run alembic upgrade head
  4. docker compose up --build -d
EOF
