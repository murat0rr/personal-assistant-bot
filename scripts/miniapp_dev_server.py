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
let _nextTemplateId = 100;
const _templates = __TEMPLATES_JSON__;
let _nextProjectId = 10;
const _projects = __PROJECTS_JSON__;
let _nextGoalId = 100;
const _goals = __GOALS_JSON__;

function _serialize(t) {
  return {
    id: t.id,
    title: t.title,
    due_date: t.due,
    due_time: t.time,
    priority: t.priority,
    done: t.done,
    sort_order: t.sort_order,
    project_id: t.project_id || null,
    sphere: t.sphere || null,
  };
}

function _serializeProject(p) {
  const linked = _tasks.filter((t) => t.project_id === p.id && !t.archived);
  return {
    id: p.id,
    title: p.title,
    description: p.description,
    spheres: p.spheres || [],
    color: p.color || null,
    done: !!p.done,
    start_date: p.start_date,
    end_date: p.end_date,
    task_count: linked.length,
    done_count: linked.filter((t) => t.done).length,
  };
}

function _serializeGoal(g) {
  return {
    id: g.id,
    spheres: g.spheres || [],
    tier: g.tier,
    period_start: g.period_start || null,
    period_end: g.period_end || null,
    text: g.text,
    done: !!g.done,
  };
}

// Мок "Проанализировать задачи и добавить" (Phase 52) — реального
// Claude тут нет, просто несколько канонических предложений с
// подставленным названием, этого достаточно, чтобы проверить сам
// экран ревью (чекбоксы, режим правки, "Готово"), не качество текста.
function _mockSuggestedTasks(title) {
  return [
    `Составить план: ${title}`,
    `Первый шаг по «${title}»`,
    `Проверить прогресс по «${title}»`,
  ];
}

function _serializeTemplate(t) {
  return {
    id: t.id,
    title: t.title,
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
    } else if (action === "project") {
      t.project_id = body.project_id;
    } else if (action === "sphere") {
      t.sphere = body.sphere;
    }
  } else if (path === "/miniapp/api/briefing") {
    result = { weather: "дев-харнесс, погода не настроена" };
  } else if (path === "/miniapp/api/habits" && method === "GET") {
    result = [];
  } else if (path === "/miniapp/api/templates" && method === "GET") {
    result = _templates
      .filter((t) => !t.archived)
      .map((t) => _serializeTemplate(t))
      .sort((a, b) => a.sort_order - b.sort_order);
  } else if (path === "/miniapp/api/templates" && method === "POST") {
    const id = _nextTemplateId++;
    const t = {
      id,
      title: body.title,
      sort_order: Date.now(),
      archived: false,
      last_used: null,
      stale_after: 14,
    };
    _templates.push(t);
    result = _serializeTemplate(t);
  } else if (path === "/miniapp/api/templates/archive-batch" && method === "POST") {
    for (const id of body.ids) {
      const t = _templates.find((x) => x.id === id);
      if (t) t.archived = true;
    }
  } else if (path.match(/\\/templates\\/(\\d+)\\/(\\w[\\w-]*)/)) {
    const m = path.match(/\\/templates\\/(\\d+)\\/(\\w[\\w-]*)/);
    const id = Number(m[1]);
    const action = m[2];
    const t = _templates.find((x) => x.id === id);
    if (!t) return { ok: false, status: 404, json: async () => ({}) };
    if (action === "reorder") {
      t.sort_order = body.sort_order;
    } else if (action === "title") {
      t.title = body.title;
    } else if (action === "use") {
      const due = body.due_date;
      const taskId = _nextId++;
      _tasks.push({
        id: taskId,
        title: t.title,
        due: due.slice(0, 10),
        time: due.length > 10 ? due.slice(11, 16) : null,
        priority: "средний",
        done: false,
        sort_order: Date.now(),
      });
      t.last_used = due.slice(0, 10);
      result = { id: taskId, title: t.title };
    }
  } else if (path === "/miniapp/api/suggest-spheres" && method === "POST") {
    // Мок подсказки сферы (Phase 51) — простое сопоставление по
    // ключевому слову в названии, чтобы было на чём проверить сам
    // механизм (тихий запрос после простановки даты, автозаполнение
    // чипов, пустой список — не блокирует форму), без реального Claude.
    const title = (body.title || "").toLowerCase();
    const sport = ["марафон", "трениров", "спорт"];
    const study = ["испанск", "курс", "учеба", "учёба"];
    const work = ["отчет", "отчёт", "работ"];
    let spheres = [];
    if (sport.some((w) => title.includes(w))) spheres = ["спорт"];
    else if (study.some((w) => title.includes(w))) spheres = ["учёба"];
    else if (work.some((w) => title.includes(w))) spheres = ["работа"];
    result = { spheres };
  } else if (path === "/miniapp/api/projects" && method === "GET") {
    result = _projects.filter((p) => !p.archived).map((p) => _serializeProject(p));
  } else if (path === "/miniapp/api/projects" && method === "POST") {
    const id = _nextProjectId++;
    const p = {
      id,
      title: body.title,
      description: body.description,
      spheres: body.spheres || [],
      start_date: body.start_date,
      end_date: body.end_date,
      color: body.color || null,
      done: false,
      archived: false,
    };
    _projects.push(p);
    result = _serializeProject(p);
  } else if (path.match(/\\/projects\\/(\\d+)\\/archive/)) {
    const m = path.match(/\\/projects\\/(\\d+)\\/archive/);
    const p = _projects.find((x) => x.id === Number(m[1]));
    if (!p) return { ok: false, status: 404, json: async () => ({}) };
    p.archived = true;
  } else if (path.match(/\\/projects\\/(\\d+)\\/(done|color|edit)/)) {
    const m = path.match(/\\/projects\\/(\\d+)\\/(done|color|edit)/);
    const id = Number(m[1]);
    const action = m[2];
    const p = _projects.find((x) => x.id === id);
    if (!p) return { ok: false, status: 404, json: async () => ({}) };
    if (action === "done") p.done = body.done;
    else if (action === "color") p.color = body.color;
    else if (action === "edit") Object.assign(p, body);
  } else if (path.match(/\\/projects\\/(\\d+)\\/suggest-tasks/)) {
    const m = path.match(/\\/projects\\/(\\d+)\\/suggest-tasks/);
    const p = _projects.find((x) => x.id === Number(m[1]));
    if (!p) return { ok: false, status: 404, json: async () => ({}) };
    result = { tasks: _mockSuggestedTasks(p.title) };
  } else if (path.match(/\\/projects\\/(\\d+)\\/create-tasks/)) {
    const m = path.match(/\\/projects\\/(\\d+)\\/create-tasks/);
    const projectId = Number(m[1]);
    for (const title of body.titles || []) {
      _tasks.push({
        id: _nextId++,
        title,
        due: null,
        time: null,
        priority: "средний",
        done: false,
        sort_order: Date.now(),
        project_id: projectId,
      });
    }
    result = { created: (body.titles || []).length };
  } else if (path === "/miniapp/api/goals" && method === "GET") {
    result = _goals.filter((g) => !g.archived).map((g) => _serializeGoal(g));
  } else if (path === "/miniapp/api/goals" && method === "POST") {
    const id = _nextGoalId++;
    const g = {
      id,
      spheres: body.spheres || [],
      tier: body.tier,
      text: body.text,
      period_start: null,
      period_end: null,
      done: false,
      archived: false,
    };
    _goals.push(g);
    result = _serializeGoal(g);
  } else if (path.match(/\\/goals\\/(\\d+)\\/(done|archive|text|edit)/)) {
    const m = path.match(/\\/goals\\/(\\d+)\\/(done|archive|text|edit)/);
    const id = Number(m[1]);
    const action = m[2];
    const g = _goals.find((x) => x.id === id);
    if (!g) return { ok: false, status: 404, json: async () => ({}) };
    if (action === "done") g.done = body.done;
    else if (action === "archive") g.archived = true;
    else if (action === "text") g.text = body.text;
    else if (action === "edit") {
      if (body.text != null) g.text = body.text;
      if (body.spheres != null) g.spheres = body.spheres;
      if (body.tier != null) g.tier = body.tier;
    }
  } else if (path.match(/\\/goals\\/(\\d+)\\/suggest-tasks/)) {
    const m = path.match(/\\/goals\\/(\\d+)\\/suggest-tasks/);
    const g = _goals.find((x) => x.id === Number(m[1]));
    if (!g) return { ok: false, status: 404, json: async () => ({}) };
    result = { tasks: _mockSuggestedTasks(g.text) };
  } else if (path.match(/\\/goals\\/(\\d+)\\/create-tasks/)) {
    const m = path.match(/\\/goals\\/(\\d+)\\/create-tasks/);
    const goal = _goals.find((x) => x.id === Number(m[1]));
    const sphere = goal && goal.spheres && goal.spheres.length ? goal.spheres[0] : null;
    for (const title of body.titles || []) {
      _tasks.push({
        id: _nextId++,
        title,
        due: null,
        time: null,
        priority: "средний",
        done: false,
        sort_order: Date.now(),
        sphere,
      });
    }
    result = { created: (body.titles || []).length };
  } else if (path.match(/\\/calendar\\/month\\?month=(\\d{4})-(\\d{2})/)) {
    const m = path.match(/\\/calendar\\/month\\?month=(\\d{4})-(\\d{2})/);
    const year = Number(m[1]);
    const month = Number(m[2]);
    result = {};
    for (const t of _tasks) {
      if (t.archived || t.priority !== "event" || !t.due) continue;
      const [ty, tm] = t.due.split("-").map(Number);
      if (ty === year && tm === month) {
        (result[t.due] = result[t.due] || []).push(t.title);
      }
    }
  } else if (path.match(/\\/calendar\\/month-moods\\?month=(\\d{4})-(\\d{2})/)) {
    // Тот же паттерн "заполнено каждый третий день", что у /diary/{date}
    // ниже — только сразу на весь месяц, для плиток календаря.
    const m = path.match(/\\/calendar\\/month-moods\\?month=(\\d{4})-(\\d{2})/);
    const year = Number(m[1]);
    const month = Number(m[2]);
    const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
    result = {};
    for (let d = 1; d <= daysInMonth; d++) {
      if (d % 3 !== 0) continue;
      const iso = `${year}-${String(month).padStart(2, "0")}-${String(d).padStart(2, "0")}`;
      result[iso] = [1, 2, 2, 3][d % 4]; // немного разброса по значениям
    }
  } else if (path.match(/\\/diary\\/(\\d{4}-\\d{2}-\\d{2})/)) {
    const m = path.match(/\\/diary\\/(\\d{4}-\\d{2}-\\d{2})/);
    const iso = m[1];
    const day = Number(iso.slice(8, 10));
    result =
      day % 3 === 0
        ? {
            physical: 2,
            social: 3,
            productivity: 1,
            happiness: 2,
            highlight: "дев-харнесс: пример особенности дня",
            // Ревью дня (Phase 48) — из Postgres в реальном бэкенде,
            // тут просто мок, чтобы было на чём проверить блок.
            review: "дев-харнесс: пример ИИ-саммари дня",
          }
        : null;
  } else if (path.match(/\\/analytics\\/spheres(\\?month=(\\d{4})-(\\d{2}))?/)) {
    // Листаемый по месяцам (Phase 53, тот же приём, что /analytics/month
    // ниже) — в отличие от того мока, тут считаем по-настоящему
    // отфильтрованные по due-дате задачи (не синтетику): переключение на
    // соседний месяц у большинства мок-задач (due="сегодня") корректно
    // покажет пустой график — это и есть проверяемое поведение (фильтр
    // реально работает), не баг мока.
    const m = path.match(/\\/analytics\\/spheres\\?month=(\\d{4})-(\\d{2})/);
    const now = new Date();
    const year = m ? Number(m[1]) : now.getFullYear();
    const month = m ? Number(m[2]) : now.getMonth() + 1;
    const monthKey = `${year}-${String(month).padStart(2, "0")}`;
    const counts = {};
    const doneCounts = {};
    for (const t of _tasks) {
      if (!t.archived && t.sphere && t.due && t.due.startsWith(monthKey)) {
        counts[t.sphere] = (counts[t.sphere] || 0) + 1;
        if (t.done) doneCounts[t.sphere] = (doneCounts[t.sphere] || 0) + 1;
      }
    }
    const spheres = Object.keys(counts)
      .sort()
      .map((sphere) => ({ sphere, count: counts[sphere], done: doneCounts[sphere] || 0 }));
    result = { year, month, spheres };
  } else if (path.match(/\\/analytics\\/month(\\?month=(\\d{4})-(\\d{2}))?/)) {
    // Листаемый график (Phase 41) — без ?month= отдаёт "текущий месяц"
    // (реального today), с ?month= — тот месяц, который спросили;
    // реальных данных по прошлым/будущим месяцам в моке нет, отдаём тот
    // же синтетический паттерн независимо от месяца — этого достаточно,
    // чтобы проверить сам факт переключения (заголовок/дни меняются).
    const m = path.match(/\\/analytics\\/month\\?month=(\\d{4})-(\\d{2})/);
    const now = new Date();
    const year = m ? Number(m[1]) : now.getFullYear();
    const month = m ? Number(m[2]) : now.getMonth() + 1;
    const daysInMonth = new Date(Date.UTC(year, month, 0)).getUTCDate();
    const days = Array.from({ length: daysInMonth }, (_, i) => String(i + 1).padStart(2, "0"));
    const all_counts = days.map((_, i) => (i % 4 === 0 ? 2 : i % 3 === 0 ? 1 : 0));
    const activeProjects = _projects.filter((p) => !p.archived);
    result = {
      year,
      month,
      days,
      all_counts,
      projects: [
        ...activeProjects.map((p, i) => ({
          title: p.title,
          total: i === 0 ? 3 : 0,
          counts: i === 0 ? all_counts : days.map(() => 0),
        })),
        { title: "Без проекта", total: 1, counts: days.map((_, i) => (i === 2 ? 1 : 0)) },
      ],
    };
  } else if (path === "/miniapp/api/analytics/summary") {
    result = {
      text: "дев-харнесс: тут будет текстовая ИИ-аналитика по сферам/месяцу/проектам.",
    };
  }

  window.__lastTasks = _tasks;
  window.__lastTemplates = _templates;
  window.__lastProjects = _projects;
  window.__lastGoals = _goals;
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
    tomorrow = (date.today() + timedelta(days=1)).isoformat()
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
    # Завтрашняя (Phase 50) — dated_tasks уже содержит все задачи с
    # датой независимо от дня, страница "Завтра" читает отсюда же
    # (tasksForDate), не отдельным полем с бэкенда.
    tasks.append(
        {
            "id": 905,
            "title": "Завтрашняя задача",
            "due": tomorrow,
            "time": None,
            "priority": "средний",
            "done": False,
            "sort_order": 100,
        }
    )
    return tasks


def _default_templates() -> list[dict]:
    # last_used/stale_after — не используются рендером (подсветку "давно
    # не делал" убрали в Phase 29), оставлены как есть в мок-данных, не
    # мешают.
    today = date.today()
    return [
        {
            "id": 1,
            "title": "Тренировка по боксу",
            "sort_order": 1000,
            "archived": False,
            "last_used": (today - timedelta(days=2)).isoformat(),
            "stale_after": 14,
        },
        {
            "id": 2,
            "title": "Стирка",
            "sort_order": 2000,
            "archived": False,
            "last_used": (today - timedelta(days=20)).isoformat(),
            "stale_after": 14,
        },
        {
            "id": 3,
            "title": "Продукты",
            "sort_order": 3000,
            "archived": False,
            "last_used": None,
            "stale_after": 14,
        },
    ]


def _default_projects() -> list[dict]:
    today = date.today()
    return [
        {
            "id": 1,
            "title": "Подготовка к сессии",
            "description": "Зачёты и экзамены зимней сессии",
            # Несколько сфер (Phase 48) — заодно проверяет, что список из
            # 2+ элементов рендерится/редактируется корректно, не только
            # частный случай "одна сфера" или "без сферы".
            "spheres": ["учёба", "развитие"],
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=30)).isoformat(),
            "archived": False,
        },
        {
            "id": 2,
            "title": "Без сферы и дат",
            "description": None,
            "spheres": [],
            "start_date": None,
            "end_date": None,
            "archived": False,
        },
        # Три ниже — специально для проверки упаковки строк ганта (item 2,
        # Phase 41): "Курсовая" той же (первой) сферы, что "Подготовка к
        # сессии", но НЕ пересекается по датам с ней — должна встать в
        # ОДНУ строку с ней. "Практика" той же сферы, но ПЕРЕСЕКАЕТСЯ по
        # датам с "Подготовка к сессии" — должна получить отдельную
        # строку, несмотря на совпадение сферы. "Тренировки" — другая
        # сфера, своя строка независимо от пересечения дат с кем угодно.
        {
            "id": 3,
            "title": "Курсовая работа",
            "description": None,
            "spheres": ["учёба"],
            "start_date": (today + timedelta(days=35)).isoformat(),
            "end_date": (today + timedelta(days=55)).isoformat(),
            "archived": False,
        },
        {
            "id": 4,
            "title": "Практика",
            "description": None,
            "spheres": ["учёба"],
            "start_date": (today + timedelta(days=5)).isoformat(),
            "end_date": (today + timedelta(days=20)).isoformat(),
            "archived": False,
        },
        {
            "id": 5,
            "title": "Тренировки к марафону",
            "description": None,
            "spheres": ["спорт"],
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=40)).isoformat(),
            "archived": False,
        },
    ]


def _default_goals() -> list[dict]:
    return [
        {
            "id": 1,
            "spheres": ["спорт"],
            "tier": "weekly",
            "text": "Пробежать 15км за неделю",
            "period_start": None,
            "period_end": None,
            "done": False,
            "archived": False,
        },
        {
            "id": 2,
            "spheres": ["работа"],
            "tier": "monthly",
            "text": "Закрыть квартальный отчёт",
            "period_start": None,
            "period_end": None,
            "done": True,
            "archived": False,
        },
        {
            "id": 3,
            "spheres": ["развитие", "учёба"],
            "tier": "yearly",
            "text": "Выучить испанский до разговорного уровня",
            "period_start": None,
            "period_end": None,
            "done": False,
            "archived": False,
        },
    ]


def _build_mock_script(
    tasks: list[dict], templates: list[dict], projects: list[dict], goals: list[dict]
) -> str:
    today = date.today().isoformat()
    yesterday = (date.today() - timedelta(days=1)).isoformat()
    script = MOCK_SCRIPT.replace("__TASKS_JSON__", json.dumps(tasks, ensure_ascii=False))
    script = script.replace("__TEMPLATES_JSON__", json.dumps(templates, ensure_ascii=False))
    script = script.replace("__PROJECTS_JSON__", json.dumps(projects, ensure_ascii=False))
    script = script.replace("__GOALS_JSON__", json.dumps(goals, ensure_ascii=False))
    script = script.replace("__TODAY_JSON__", json.dumps(today))
    script = script.replace("__YESTERDAY_JSON__", json.dumps(yesterday))
    return script


def build_merged_html(
    tasks: list[dict], templates: list[dict], projects: list[dict], goals: list[dict]
) -> bytes:
    html = INDEX_HTML.read_text(encoding="utf-8")
    if TELEGRAM_SCRIPT_TAG not in html:
        raise RuntimeError(
            "index.html изменил структуру — тег telegram-web-app.js не найден, "
            "обнови TELEGRAM_SCRIPT_TAG в scripts/miniapp_dev_server.py"
        )
    mock = f"<script>{_build_mock_script(tasks, templates, projects, goals)}</script>\n"
    merged = html.replace(TELEGRAM_SCRIPT_TAG, mock)
    return merged.encode("utf-8")


_STATIC_DIR = INDEX_HTML.parent  # src/adapters/miniapp_static
_JS_CONTENT_TYPES = {
    ".js": "text/javascript; charset=utf-8",
    ".mjs": "text/javascript; charset=utf-8",
}


def make_handler(
    tasks: list[dict], templates: list[dict], projects: list[dict], goals: list[dict]
) -> type[http.server.BaseHTTPRequestHandler]:
    class Handler(http.server.BaseHTTPRequestHandler):
        def do_GET(self) -> None:  # noqa: N802 (метод BaseHTTPRequestHandler)
            if self.path in ("/", "/index.html"):
                try:
                    body = build_merged_html(tasks, templates, projects, goals)
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
                return

            # Виджеты аналитики (Phase 46) — index.html грузит их через
            # <script type="module" src="./js/widgets/...">, до сих пор
            # этот харнесс отдавал ровно один файл (index.html целиком,
            # с внедрённым моком) и ничего больше не требовалось. Теперь
            # нужно реально отдавать дерево статики — тот же принцип,
            # что прод (StaticFiles(directory=_STATIC_DIR) в api.py),
            # только руками: резолвим путь и проверяем, что он не вышел
            # за пределы _STATIC_DIR (../../secrets и т.п.).
            suffix = Path(self.path).suffix
            if suffix in _JS_CONTENT_TYPES:
                requested = (_STATIC_DIR / self.path.lstrip("/")).resolve()
                if _STATIC_DIR.resolve() in requested.parents and requested.is_file():
                    body = requested.read_bytes()
                    self.send_response(200)
                    self.send_header("Content-Type", _JS_CONTENT_TYPES[suffix])
                    self.send_header("Content-Length", str(len(body)))
                    self.send_header("Cache-Control", "no-store")
                    self.end_headers()
                    self.wfile.write(body)
                    return

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
    templates = _default_templates()
    projects = _default_projects()
    # Первая задача набора линкуется на первый проект — чтобы прогресс-бар
    # в разделе "Проекты" было на чём проверить без ручных действий.
    if tasks:
        tasks[0]["project_id"] = projects[0]["id"]
    # Разные сферы на части задач — чтобы диаграмма "по сферам" в
    # аналитике было на чём проверить без ручных действий.
    _spheres_cycle = ["учёба", "работа", "спорт", "развитие", "отношения"]
    for i, t in enumerate(tasks):
        t["sphere"] = _spheres_cycle[i % len(_spheres_cycle)]
    goals = _default_goals()

    handler = make_handler(tasks, templates, projects, goals)
    server = http.server.HTTPServer(("127.0.0.1", args.port), handler)
    print(f"Mini App dev-сервер: http://127.0.0.1:{args.port}/  (Ctrl+C — остановить)")
    print(
        f"Задач в наборе: {len(tasks)}, шаблонов: {len(templates)}, "
        f"проектов: {len(projects)}, целей: {len(goals)}"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
