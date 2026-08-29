# Деплой на VPS

Runbook для первого деплоя и настройки CI/CD. Контекст и обоснование
выбора провайдеров — в `docs/PLAN.md`, Phase 8.

## 1. Аренда VPS

[Timeweb Cloud](https://timeweb.cloud/services/cloud-servers) — облачный
сервер, локация **Амстердам** или **Франкфурт**, тариф от ~2 vCPU / 4 ГБ
RAM / 50 ГБ NVMe. Образ — **Ubuntu 24.04 LTS**. После создания сохрани:

- IP-адрес сервера
- root-пароль или SSH-ключ (если Timeweb предложит сгенерировать —
  используй его; если нет — сгенерируй свой: `ssh-keygen -t ed25519 -C "assistant-vps"`
  и добавь публичный ключ при создании сервера)

## 2. Домен

Купи домен на [reg.ru](https://www.reg.ru) (зона `.ru` — самая дешёвая).
В панели управления доменом добавь DNS-запись:

```
Тип: A
Имя: @ (или пусто — на корень домена)
Значение: <IP сервера>
```

DNS распространяется не мгновенно (от нескольких минут до пары часов) —
можно проверить командой `nslookup <домен>`.

## 3. Первичная настройка сервера

Сначала нужен сам git-репозиторий на GitHub (см. шаг 6) — либо клонируй
скрипт `setup_server.sh` на сервер вручную сейчас, а репозиторий подтянешь
позже. Подключись по SSH:

```bash
ssh root@<IP сервера>
```

Скопируй `scripts/setup_server.sh` на сервер (или создай там же через
`nano`/`vim`, содержимое — в репозитории), затем:

```bash
chmod +x setup_server.sh
./setup_server.sh git@github.com:<твой-user>/assistant.git
```

Скрипт ставит Docker, git, настраивает `ufw` (только 22/80/443) и
клонирует репозиторий в `/opt/assistant`.

## 4. Перенос `.env` и первый запуск

С локальной машины:

```bash
scp .env root@<IP сервера>:/opt/assistant/.env
```

В скопированном `.env` на сервере добавь/проверь:

```
DOMAIN=<твой домен, например assistant.ru>
```

На сервере:

```bash
cd /opt/assistant
docker compose run --rm bot uv run alembic upgrade head
docker compose up --build -d
docker compose logs bot --tail 30   # убедиться, что стартовало чисто
```

Первый запуск Caddy может занять до минуты — он сам получает сертификат
Let's Encrypt для `DOMAIN`. Проверь: `curl https://<домен>/health` должен
вернуть `{"status":"ok"}`.

## 5. Переключить интеграции на новый домен

- **BotFather** → твой бот → Bot Settings → Menu Button → URL —
  поменять на `https://<домен>/miniapp/`
- **MacroDroid** (F10, экранное время) — в макросе "Отправка" поменять
  URL на `https://<домен>/webhooks/tasker/screen-time`
- Локальный ngrok/докер на Windows-машине больше не нужен — можно
  остановить (`docker compose down` на локальной машине), сервер теперь
  главный.

## 6. GitHub-репозиторий + CI/CD

Если репозитория ещё нет на GitHub — создай пустой (без README/лицензии,
чтобы не конфликтовать с локальной историей) и подключи:

```bash
git remote add origin git@github.com:<твой-user>/assistant.git
git push -u origin master
```

Дальше настрой три секрета: репозиторий → Settings → Secrets and
variables → Actions → New repository secret:

| Имя | Значение |
|---|---|
| `VPS_HOST` | IP сервера |
| `VPS_USER` | `root` (или другой пользователь с доступом к `/opt/assistant` и Docker) |
| `VPS_SSH_KEY` | приватный SSH-ключ, у которого публичная пара — в `~/.ssh/authorized_keys` на сервере |

Если ключа для деплоя ещё нет — сгенерируй отдельный (не тот, что для
ручного входа):

```bash
ssh-keygen -t ed25519 -f deploy_key -C "github-actions-deploy" -N ""
```

`deploy_key.pub` → на сервер: `ssh-copy-id -i deploy_key.pub root@<IP>`
(или вручную дописать в `~/.ssh/authorized_keys`).
`deploy_key` (приватный, без расширения) → содержимое файла целиком —
в секрет `VPS_SSH_KEY`. Файл `deploy_key` после этого удали локально,
он больше не нужен — публичный уже на сервере, приватный — в GitHub Secrets.

После этого — `.github/workflows/deploy.yml` уже в репозитории: любой
`git push` в `master` сам подтянет изменения на сервер, прогонит миграции
и пересоберёт контейнеры.

## Дальнейшие обновления

Обычная разработка дальше не меняется — тот же цикл (фаза → план →
реализация → тесты → коммит), просто последний шаг теперь не только
коммит, а `git push`, который сам доезжает до сервера.
