// Контроллер панели аналитики (Phase 46) — монтирует только включённые
// виджеты из WIDGET_REGISTRY, ничего не знает про их внутренности.
// Выбор — per-device (localStorage), тот же паттерн, что getStoredTheme/
// setTheme в index.html: чисто визуальное предпочтение конкретного
// устройства, не серверные данные; обёрнуто в try/catch на случай
// приватного режима браузера, где localStorage может быть недоступен.

import { WIDGET_REGISTRY } from "./registry.js";

const STORAGE_KEY = "analyticsWidgets";
// Отдельный ключ (Phase 71, фидбек: "графики рисуются в согласии с
// очередью") — порядок ВСЕХ виджетов реестра, включённых и выключенных
// (не только включённых, как STORAGE_KEY выше): перетаскивание в
// настройках работает по всему списку разом, чтобы выключенный виджет,
// если его потом снова включат, вернулся на своё же место, а не в
// конец. Порядок и включённость — независимые понятия.
const ORDER_STORAGE_KEY = "analyticsWidgetOrder";

export function getEnabledIds() {
  try {
    const raw = localStorage.getItem(STORAGE_KEY);
    if (raw) return JSON.parse(raw);
  } catch (e) {
    // приватный режим и т.п. — откатываемся на дефолт ниже
  }
  return WIDGET_REGISTRY.filter((w) => w.defaultEnabled).map((w) => w.id);
}

export function setEnabledIds(ids) {
  try {
    localStorage.setItem(STORAGE_KEY, JSON.stringify(ids));
  } catch (e) {
    // приватный режим — выбор просто не переживёт перезагрузку страницы
  }
}

// Порядок — массив id ВСЕХ виджетов реестра (не только включённых).
// Идентификаторы, которых нет в сохранённом порядке (новый виджет
// появился в реестре уже после того, как пользователь настроил
// порядок) дописываются в конец в порядке объявления в реестре —
// иначе виджет, добавленный будущей фазой, вообще не отрисовался бы,
// пока пользователь явно не перетащит что-нибудь в настройках.
export function getWidgetOrder() {
  let stored = [];
  try {
    const raw = localStorage.getItem(ORDER_STORAGE_KEY);
    if (raw) stored = JSON.parse(raw);
  } catch (e) {
    // приватный режим и т.п. — откатываемся на порядок реестра целиком
  }
  const known = new Set(WIDGET_REGISTRY.map((w) => w.id));
  const order = stored.filter((id) => known.has(id));
  const missing = WIDGET_REGISTRY.map((w) => w.id).filter((id) => !order.includes(id));
  return [...order, ...missing];
}

export function setWidgetOrder(ids) {
  try {
    localStorage.setItem(ORDER_STORAGE_KEY, JSON.stringify(ids));
  } catch (e) {
    // приватный режим — порядок просто не переживёт перезагрузку страницы
  }
}

let activeWidgets = [];

export async function renderAnalyticsPanel(container, ctx) {
  activeWidgets.forEach((w) => w.unmount());
  activeWidgets = [];
  container.innerHTML = "";

  const enabled = new Set(getEnabledIds());
  const order = getWidgetOrder();
  const toShow = order
    .map((id) => WIDGET_REGISTRY.find((entry) => entry.id === id))
    .filter((entry) => entry && enabled.has(entry.id));

  if (toShow.length === 0) {
    container.innerHTML =
      '<div class="section"><div class="chart-card"><div class="chart-empty">' +
      "Все графики отключены — включите нужные в настройках (⚙ рядом с заголовком)." +
      "</div></div></div>";
    return;
  }

  for (const entry of toShow) {
    const section = document.createElement("div");
    section.className = "section";
    const card = document.createElement("div");
    card.className = "chart-card";
    section.appendChild(card);
    container.appendChild(section);

    const widget = entry.create(ctx);
    activeWidgets.push(widget);
    try {
      await widget.mount(card);
    } catch (e) {
      card.innerHTML = '<div class="chart-empty">Не удалось загрузить.</div>';
    }
  }
}
