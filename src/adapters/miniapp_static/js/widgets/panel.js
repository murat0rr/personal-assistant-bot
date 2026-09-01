// Контроллер панели аналитики (Phase 46) — монтирует только включённые
// виджеты из WIDGET_REGISTRY, ничего не знает про их внутренности.
// Выбор — per-device (localStorage), тот же паттерн, что getStoredTheme/
// setTheme в index.html: чисто визуальное предпочтение конкретного
// устройства, не серверные данные; обёрнуто в try/catch на случай
// приватного режима браузера, где localStorage может быть недоступен.

import { WIDGET_REGISTRY } from "./registry.js";

const STORAGE_KEY = "analyticsWidgets";

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

let activeWidgets = [];

export async function renderAnalyticsPanel(container, ctx) {
  activeWidgets.forEach((w) => w.unmount());
  activeWidgets = [];
  container.innerHTML = "";

  const enabled = new Set(getEnabledIds());
  const toShow = WIDGET_REGISTRY.filter((entry) => enabled.has(entry.id));

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
