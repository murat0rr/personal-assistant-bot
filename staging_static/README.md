# Staging для Mini App

Bind-mounted в контейнер `api` на `/app/staging_static`, отдаётся по
`/miniapp-staging/` (см. `src/adapters/api.py`) — второй, отдельный от
прод-роута, static-mount на том же бэкенде. См. `SPEC.md` §5 и
`DEPLOY.md` за полным описанием workflow.

Коротко: `POST /miniapp/api/*` (реальные данные, реальная авторизация)
общие для прод- и staging-статики — меняется только то, какой
`index.html` их вызывает. Чтобы проверить кандидата перед мержем в
`master`:

```bash
scp src/adapters/miniapp_static/index.html \
    -i ~/.ssh/assistant_vps root@85.137.24.126:/opt/assistant/staging_static/index.html
```

Никакой пересборки/рестарта — файл подхватывается на следующий
запрос. Открыть в реальном Telegram (не в обычном браузере — без
подписанного `initData` `/miniapp/api/*` ответит 401) через бот-команду
`/staging` (см. `src/handlers/mode_buttons.py`).

Содержимое этой директории — не для git (см. `.gitignore`), кроме
этого README-плейсхолдера, который держит директорию и путь
задокументированными.
