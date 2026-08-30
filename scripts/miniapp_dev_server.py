"""Dev-сервер для ручного и скриптового (synthetic PointerEvent) тестирования
Mini App вне Telegram — формализует харнесс, который в Phase 13-17 пересобирался
руками заново на каждый раунд правок drag&drop (см. SPEC.md, §5, пункт 2).

Отдаёт src/adapters/miniapp_static/index.html КАК ЕСТЬ (читается заново на
каждый запрос — никакой рассинхронизации с реальным файлом, в отличие от
статической копии), но с внедрённым мок-скриптом перед настоящим
telegram-web-app.js:
  - window.Telegram.WebApp — ready/expand/initData/HapticFeedback
    (window.__hapticCalls — список вызовов impactOccurred, для проверки)
  - window.fetch — весь набор /miniapp/api/* эндпоинтов на in-memory доске
    задач (window.__lastTasks — текущее состояние для проверки)
  - window.__gestures — переиспользуемые хелперы для synthetic PointerEvent
    (fire/dragGrip) вместо ручного повторения одного и того же кода в
    javascript_exec на каждый тест

Настоящий telegram-web-app.js в этой странице не грузится вообще (в отличие
от прод-index.html) — в обычном браузере он всё равно не даёт ничего, кроме
шума в консоли, а главное молча перезаписывает мок, если сеть доступна.

Использование:
    uv run python scripts/miniapp_dev_server.py
    uv run python scripts/miniapp_dev_server.py --port 8080 --count 8
    uv run python scripts/miniapp_dev_server.py --tasks scripts/example_tasks.json

Дальше открыть http://127.0.0.1:8765/ — обычный браузер или Claude Browser
pane. Из консоли/javascript_exec: window.__lastTasks, window.__hapticCalls,
window.__gestures.fire(el, type, x, y, id), window.__gestures.dragGrip(grip,
[[x0,y0],[x1,y1],...], {id, stepDelayMs}).
"""

from __future__ import annotations

import argparse
import http.server
import json
from datetime import date, timedelta
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
INDEX_HTML = REPO_ROOT / "src" / "adapters" / "miniapp_static" / "index.html"
TELEGRAM_SCRIPT_TAG = '<script src="https://telegram.org/js/telegram-web-app.js"></script>'

MOCK_SCRIPT = """
window.__hapticCalls = [];
window.Telegram = {
  WebApp: {
    ready() {},
    expand() {},
    initData: "dev-harness",
    HapticFeedback: { impactOccurred: (style) => window.__hapticCalls.push(style) },
  },
};

let _nextId = 1000;
const _tasks = __TASKS_JSON__;

function _serialize(t) {
  return {
    id: t.id,
    title: t.title,
    due_date: t.due,
    due_time: t.time,
    priority: t.priority,
    done: t.done,
    sort_order: t.sort_order,
  };
}

function _buildBoard() {
  const today = __TODAY_JSON__;
  const yesterday = __YESTERDAY_JSON__;
  const byOrder = (a, b) => a.sort_order - b.sort_order;
  const alive = () => _tasks.filter((t) => !t.archived);
  const dayTasks = (d) => alive().filter((t) => t.due === d).sort(byOrder).map(_serialize);
  return {
    days: {
      yesterday: { date: yesterday, tasks: dayTasks(yesterday) },
      today: { date: today, tasks: dayTasks(today) },
    },
    dated_tasks: alive().filter((t) => t.due).sort(byOrder).map(_serialize),
    inbox: alive()
      .filter((t) => t.due === null || (t.due < today && !t.done))
      .sort(byOrder)
      .map(_serialize),
  };
}

window.fetch = async (path, options = {}) => {
  const method = options.method || "GET";
  const body = options.body ? JSON.parse(options.body) : null;
  let result = { status: "ok" };

  if (path === "/miniapp/api/tasks" && method === "GET") {
    result = _buildBoard();
  } else if (path === "/miniapp/api/tasks" && method === "POST") {
    const id = _nextId++;
    _tasks.push({
      id,
      title: body.title,
      due: body.due_date ? body.due_date.slice(0, 10) : null,
      time: body.due_date && body.due_date.length > 10 ? body.due_date.slice(11, 16) : null,
      priority: "средний",
      done: false,
      sort_order: Date.now(),
    });
    result = { status: "ok", id };
  } else if (path === "/miniapp/api/tasks/archive-batch" && method === "POST") {
    for (const id of body.ids) {
      const t = _tasks.find((x) => x.id === id);
      if (t) t.archived = true;
    }
  } else if (path.match(/\\/tasks\\/(\\d+)\\/(\\w[\\w-]*)/)) {
    const m = path.match(/\\/tasks\\/(\\d+)\\/(\\w[\\w-]*)/);
    const id = Number(m[1]);
    const action = m[2];
    const t = _tasks.find((x) => x.id === id);
    if (!t) return { ok: false, status: 404, json: async () => ({}) };
    if (action === "done") t.done = body.done;
    else if (action === "due-date") {
      t.due = body.due_date.slice(0, 10);
      t.time = body.due_date.length > 10 ? body.due_date.slice(11, 16) : null;
      t.sort_order = Date.now();
    } else if (action === "priority") {
      t.priority = body.priority;
      t.sort_order = Date.now();
    } else if (action === "reorder") {
      t.sort_order = body.sort_order;
    } else if (action === "title") {
      t.title = body.title;
    } else if (action === "archive") {
      t.archived = true;
    }
  } else if (path === "/miniapp/api/briefing") {
    result = { weather: "дев-харнесс, погода не настроена" };
  } else if (path === "/miniapp/api/habits" && method === "GET") {
    result = [];
  }

  window.__lastTasks = _tasks;
  return { ok: true, status: 200, json: async () => result };
};

window.__gestures = {
  fire(el, type, x, y, id = 1) {
    const ev = new PointerEvent(type, {
      bubbles: true,
      cancelable: true,
      clientX: x,
      clientY: y,
      pointerId: id,
      isPrimary: true,
      pointerType: "touch",
    });
    el.dispatchEvent(ev);
    return ev;
  },
  async dragGrip(grip, points, { id = 1, stepDelayMs = 15 } = {}) {
    // points — [[x0,y0], [x1,y1], ...]: первая точка — pointerdown, дальше
    // pointermove по очереди на document (см. почему не на самой ручке —
    // SPEC.md §2.3, MA-4), последняя точка также используется для pointerup.
    const [first, ...rest] = points;
    this.fire(grip, "pointerdown", first[0], first[1], id);
    for (const [x, y] of rest) {
      this.fire(document, "pointermove", x, y, id);
      if (stepDelayMs) await new Promise((r) => setTimeout(r, stepDelayMs));
    }
    const last = points[points.length - 1];
    this.fire(document, "pointerup", last[0], last[1], id);
  },
};
"""


def _default_tasks(count: int) -> list[dict]:
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    tasks = []
    for i in range(1, count + 1):
        tasks.append(
            {
                "id": i,
                "title": f"Задача {i}",
                "due": today,
                "time": None,
                "priority": "средний",
                "done": False,
                "sort_order": i * 1000,
            }
        )
    # Разношёрстный набор поверх однообразных — событие, важная, выполненная,
    # вчерашняя, инбокс — типовой сценарий проверки без ручного редактирования.
    tasks.append(
        {
            "id": 900,
            "title": "Событие со временем",
            "due": today,
            "time": "14:30",
            "priority": "event",
            "done": False,
            "sort_order": 500,
        }
    )
    tasks.append(
        {
            "id": 901,
            "title": "Важная задача",
            "due": today,
            "time": None,
            "priority": "высокий",
            "done": False,
            "sort_order": 1500,
        }
    )
    tasks.append(
        {
            "id": 902,
            "title": "Выполненная задача",
            "due": today,
            "time": None,
            "priority": "средний",
            "done": True,
            "sort_order": 2500,
        }
    )
    tasks.append(
        {
            "id": 903,
            "title": "Вчерашняя задача",
            "due": yesterday,
            "time": None,
            "priority": "средний",
            "done": False,
            "sort_order": 100,
        }
    )
    tasks.append(
        {
            "id": 904,
            "title": "Инбокс без даты",
            "due": None,
            "time": None,
            "priority": "средний",
            "done": False,
            "sort_order": 100,
        }
    )
    return tasks


def _build_mock_script(tasks: list[dict]) -> str:
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    script = MOCK_SCRIPT.replace("__TASKS_JSON__", json.dumps(tasks, ensure_ascii=False))
    script = script.replace("__TODAY_JSON__", json.dumps(today))
    script = script.replace("__YESTERDAY_JSON__", json.dumps(yesterday))
    return script


def build_merged_html(tasks: list[dict]) -> bytes:
    html = INDEX_HTML.read_text(encoding="utf-8")
    if TELEGRAM_SCRIPT_TAG not in html:
        raise RuntimeError(
            "index.html изменил структуру — тег telegram-web-app.js не найден, "
            "обнови TELEGRAM_SCRIPT_TAG в scripts/miniapp_dev_server.py"
        )
    mock = f"<script>{_build_mock_script(tasks)}</script>\n"
    merged = html.replace(TELEGRAM_SCRIPT_TAG, mock)
    return merged.encode("utf-8")


def make_handler(tasks: list[dict]) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (метод BaseHTTPRequestHandler)
            if self.path in ("/", "/index.html"):
                try:
                    body = build_merged_html(tasks)
                except RuntimeError as exc:
                    self.send_response(500)
                    self.end_headers()
                    self.wfile.write(str(exc).encode("utf-8"))
                    return
                self.send_response(200)
                self.send_header("Content-Type", "text/html; charset=utf-8")
                self.send_header("Content-Length", str(len(body)))
                self.send_header("Cache-Control", "no-store")
                self.end_headers()
                self.wfile.write(body)
            else:
                self.send_response(404)
                self.end_headers()

        def log_message(self, fmt: str, *args: object) -> None:
            pass  # тихо — не засорять вывод при каждом запросе/скролле

    return Handler


def main() -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument(
        "--count", type=int, default=3, help="сколько однообразных задач добавить на 'Сегодня'"
    )
    parser.add_argument(
        "--tasks",
        type=Path,
        default=None,
        help="JSON-файл со списком задач (форма как в default_tasks) вместо синтетического набора",
    )
    args = parser.parse_args()

    tasks = (
        json.loads(args.tasks.read_text(encoding="utf-8"))
        if args.tasks
        else _default_tasks(args.count)
    )

    handler = make_handler(tasks)
    server = http.server.HTTPServer(("127.0.0.1", args.port), handler)
    print(f"Mini App dev-сервер: http://127.0.0.1:{args.port}/  (Ctrl+C — остановить)")
    print(f"Задач в наборе: {len(tasks)}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
