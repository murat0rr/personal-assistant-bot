---
name: assistant-dev-workflow
description: >
  Use whenever working in the C:\Users\murat\assistant repository (the
  personal Telegram assistant project) — implementing a new phase or
  feature, generating/applying an Alembic migration, running any
  `docker compose` command against this project, or preparing to commit
  changes here. ALWAYS consult this before generating an Alembic
  migration in this repo — Docker's build cache has silently produced
  empty migrations here multiple times, and the fix is non-obvious.
  ALWAYS consult this before running `git commit` in this repo — this
  project's convention requires a live Docker/Telegram check first, not
  just green tests. Also trigger on phrases like "давай фаза N", "новая
  миграция", "мигрируй базу", "пересобери докер", or any request to add
  a feature/handler/job to this bot.
---

# Разработка личного Telegram-ассистента

Этот скилл — память о том, как устроена работа над конкретно этим
проектом (`C:\Users\murat\assistant`) и о граблях, на которые здесь уже
наступали не один раз. Полная спецификация — `docs/PLAN.md`, конвенции —
`CLAUDE.md`; этот файл дополняет их операционными деталями, которые
проще один раз закрепить, чем каждый раз выводить заново.

## Цикл одной фазы

Проект развивается строго по фазам PLAN.md, один цикл на фазу:

1. **План** — если требования неполные или есть развилка в архитектуре,
   сначала `EnterPlanMode`, прочитать релевантные файлы, при
   необходимости `AskUserQuestion` по конкретным развилкам (не спрашивать
   "ок ли план?" — для этого `ExitPlanMode`), написать план в файл,
   `ExitPlanMode` на согласование. Не пропускать этот шаг ради скорости —
   в этом проекте почти каждая фаза меняла архитектуру по ходу
   обсуждения (кнопки-режимы, отказ от Notion-подписок в пользу общих
   напоминалок и т.п.) именно потому, что план обсуждался до кода.
2. **Реализация** — следовать существующим паттернам (см. ниже).
3. **Тесты и линт** — локально, без Docker (быстрее): venv лежит прямо в
   репозитории.
   ```bash
   ./.venv/Scripts/python.exe -m pytest -q
   ./.venv/Scripts/ruff.exe check .
   ./.venv/Scripts/ruff.exe format .
   ```
4. **Живой прогон** — тесты проходят не значит, что фича работает.
   Пересобрать и поднять стек, проверить логи на чистый старт:
   ```bash
   docker compose up --build -d
   docker compose logs bot --tail 25
   ```
   Убедиться, что новые apscheduler-джобы зарегистрированы (если
   добавлялись) и нет ошибок при старте. Дальше — реальная проверка
   фичи: попросить пользователя протестировать в Telegram, либо самому
   `curl`/`docker compose exec` для проверяемой логики (вебхуки, ручной
   вызов функции сборки сообщения и т.п.).
5. **Коммит** — только после того, как живой прогон подтверждён (самим
   или пользователем). Сообщение коммита — на русском, с перечислением
   изменений, обязательно с трейлером:
   ```
   Co-Authored-By: Claude Sonnet 5 <noreply@anthropic.com>
   ```

## Ловушка: Docker build cache и «пустые» файлы в контейнере

`docker compose run <service> ...` **не гарантирует**, что образ
пересобран под текущее состояние файлов на хосте — если образ уже
существует, compose может использовать старый, даже если исходники
поменялись минуту назад. В этом проекте это уже приводило к реальному
багу: `alembic revision --autogenerate` сгенерировал пустую миграцию
(`pass` вместо `op.create_table(...)`), потому что контейнер работал со
старой версией `src/models/__init__.py`, не импортирующей новую модель.

**Правило**: после любого изменения файлов в `src/` или `migrations/` —
явный `docker compose build <service>` (или `docker compose up --build`)
**перед** тем, как полагаться на содержимое файлов внутри контейнера.
Не доверять тому, что `docker compose run` сам пересоберёт при
изменении — он не обязан.

Быстрая проверка, если результат выглядит подозрительно (пустая
миграция, старое поведение): сверить содержимое файла внутри образа
против хоста, например
`docker compose run --rm <service> uv run python -c "from src.models import Base; print(sorted(Base.metadata.tables.keys()))"`
— если новой таблицы там нет, значит образ устарел, пересобрать и
повторить.

## Генерация Alembic-миграций в этом окружении

Bind-mounts ненадёжны в этой Windows-среде через git-bash, поэтому
миграции генерируются внутри временного контейнера и копируются на хост
через `docker cp`. Точная последовательность (пропуск любого шага —
частая причина сломанной или пустой миграции):

1. `docker compose build <service>` — образ точно содержит актуальные
   модели (см. ловушку выше).
2. `docker compose run --name migration_gen_X <service> uv run alembic revision --autogenerate -m "описание"`
3. `docker cp migration_gen_X:/app/migrations/versions/. migrations/versions/`
4. `docker rm migration_gen_X`
5. Открыть сгенерированный файл — убедиться, что там реальные
   `op.create_table`/`op.add_column`/`op.drop_column` и т.п., **не**
   пустой `pass`. Если пусто — образ был устаревший, вернуться к шагу 1.
6. Прогнать линт на файле миграции (автогенерированный код не в стиле
   проекта):
   ```bash
   ./.venv/Scripts/ruff.exe format migrations/versions/<файл>.py
   ./.venv/Scripts/ruff.exe check migrations/versions/<файл>.py --fix
   ```
7. `docker compose build <service>` **снова** — файл миграции только что
   изменился на хосте после форматирования, шаг 6 сделал образ из шага 1
   опять устаревшим.
8. `docker compose run --rm <service> uv run alembic upgrade head`
9. Проверить: `docker compose run --rm <service> uv run alembic current`
   должен показать новую ревизию как `(head)`.

## Соглашения проекта, которые легко забыть

- **Секреты только через `.env`** — никогда не хардкодить, никогда не
  логировать. Новую переменную — сразу и в `.env.example` (пустое
  значение), и в `src/core/config.py` (`pydantic-settings`).
- **Вебхуки (Notion, Tasker) всегда проверяются по секрету** перед
  обработкой payload — см. `src/adapters/tasker_webhook.py::_verify_secret`
  (`secrets.compare_digest`, 401 при отсутствии/несовпадении) как образец.
- **Бот отвечает только `TELEGRAM_USER_ID`** — любой хендлер и любой
  webhook, принимающий пользовательский ввод, должен это проверять
  (`src/core/auth.py::is_authorized`), остальным — вежливый отказ без
  раскрытия функциональности.
- **Notion-интеграции — адаптивный паттерн**: названия и типы свойств в
  реальных базах пользователя не всегда совпадают с тем, что задумано
  изначально (например, поле даты называлось `Date`, а не `Due date`;
  `Status` может быть нативным Notion-статусом или обычным select).
  Проверять схему в рантайме, а не считать её фиксированной — образцы:
  `_find_date_property`, `_resolve_status_value`, `_read_text`/
  `_read_number`/`_read_date` в `src/integrations/notion.py`.
- **Один хендлер = один сценарий** (`src/handlers/f*.py`) — не смешивать
  логику разных фич в одном модуле, даже если они похожи.
- **STT и LLM-клиент — всегда за интерфейсом** (`src/integrations/`), не
  завязываться на конкретного провайдера в хендлерах.
- Claude API в этом проекте идёт через сторонний прокси
  (`CLAUDE_BASE_URL`) — у него есть известные ограничения (не
  поддерживает нативные server-side тулы вроде `web_search`, требует
  `name`+`input_schema` у любого тула). Structured extraction (forced
  tool-use с кастомным тулом) через прокси работает нормально.
