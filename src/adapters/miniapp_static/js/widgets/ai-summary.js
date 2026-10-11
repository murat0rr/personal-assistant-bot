// Виджет "ИИ-аналитика" — перенесён из renderAiSummary без изменений.
// Кнопка "перегенерировать" (Phase 67, фидбог) — раньше кэш обновлялся
// только по расписанию (_ai_analytics_refresh_job, раз в день), без
// ручного способа обновить прямо сейчас.
//
// Phase 89: следует за банером месяца на вкладке "Аналитика". Кэш
// теперь per-month (ai_analytics_cache, составной PK) — на месяц без
// готового текста бэкенд отдаёт {text: null}, виджет показывает кнопку
// "Сгенерировать" вместо автоматического вызова Claude на каждый свайп
// (решение владельца — свайп по многим месяцам не должен бить по
// кошельку пачкой запросов). Текущий месяц — исключение, как и раньше:
// бэкенд сам подставляет его аварийным фолбэком, если ночная джоба ещё
// не успела отработать (см. api.py::analytics_summary_endpoint).

function refreshIconSvg() {
  return (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" width="16" height="16">' +
    '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/>' +
    '<path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M8 16H3v5"/></svg>'
  );
}

export function createAiSummaryWidget(ctx) {
  const { api, escapeHtml, pad2, bus, getAnalyticsSelectedMonth } = ctx;
  let container = null;
  let onMonthChanged = null;
  let selectedMonthKey = null;

  function renderShell(text, regenerating) {
    container.innerHTML =
      '<div class="chart-title-row">' +
      '<p class="chart-title">ИИ-аналитика</p>' +
      `<button type="button" class="small-btn" id="ai-summary-regenerate" aria-label="Перегенерировать"${regenerating ? " disabled" : ""}>${refreshIconSvg()}</button>` +
      "</div>" +
      `<div class="ai-summary-text">${text ? escapeHtml(text) : "Пока не набралось данных для анализа."}</div>`;
    const btn = document.getElementById("ai-summary-regenerate");
    if (btn) {
      btn.classList.toggle("spinning", regenerating);
      btn.onclick = regenerate;
    }
  }

  function renderGenerateButton() {
    container.innerHTML =
      '<p class="chart-title">ИИ-аналитика</p>' +
      '<div class="chart-empty">Для этого месяца пока нет аналитики.</div>' +
      '<button type="button" class="small-btn" id="ai-summary-generate">Сгенерировать</button>';
    document.getElementById("ai-summary-generate").onclick = () => regenerate();
  }

  // Защита от гонки (найдена живой проверкой, Phase 89): свайп на
  // другой месяц, пока load()/regenerate() предыдущего ещё в полёте —
  // запрос сам по себе не отменяется, но его результат больше не
  // актуален. Каждый вызов запоминает "свой" месяц в requestedMonth и
  // перед записью в DOM сверяет его с текущим selectedMonthKey — если
  // пользователь успел свайпнуть ещё раз, более старый ответ просто
  // отбрасывается (newer load() для актуального месяца либо уже
  // отрисовал своё, либо вот-вот отрисует).
  async function load() {
    const requestedMonth = selectedMonthKey;
    container.innerHTML = '<div class="chart-empty">Загрузка…</div>';
    try {
      const summary = await api(`/miniapp/api/analytics/summary?month=${requestedMonth}`);
      if (requestedMonth !== selectedMonthKey) return;
      if (summary.text === null) {
        renderGenerateButton();
      } else {
        renderShell(summary.text, false);
      }
    } catch (e) {
      if (requestedMonth !== selectedMonthKey) return;
      container.innerHTML = '<div class="chart-empty">Не удалось загрузить.</div>';
    }
  }

  async function regenerate() {
    const requestedMonth = selectedMonthKey;
    const current = container.querySelector(".ai-summary-text")?.textContent || null;
    renderShell(current, true);
    try {
      const summary = await api(
        `/miniapp/api/analytics/summary/regenerate?month=${requestedMonth}`,
        { method: "POST" }
      );
      if (requestedMonth !== selectedMonthKey) return;
      renderShell(summary.text, false);
    } catch (e) {
      if (requestedMonth !== selectedMonthKey) return;
      renderShell(current, false);
      alert("Не удалось перегенерировать.");
    }
  }

  return {
    id: "ai-summary",
    async mount(el) {
      container = el;
      const sel = getAnalyticsSelectedMonth();
      selectedMonthKey = `${sel.year}-${pad2(sel.month)}`;
      onMonthChanged = ({ detail }) => {
        selectedMonthKey = `${detail.year}-${pad2(detail.month)}`;
        load();
      };
      bus.addEventListener("analytics:month-changed", onMonthChanged);
      await load();
    },
    unmount() {
      if (onMonthChanged) bus.removeEventListener("analytics:month-changed", onMonthChanged);
      onMonthChanged = null;
      container = null;
    },
    async refresh() {
      if (container) await load();
    },
  };
}
