// Виджет "ИИ-аналитика" — перенесён из renderAiSummary без изменений.
// Кнопка "перегенерировать" (Phase 67, фидбог) — раньше кэш обновлялся
// только по расписанию (_ai_analytics_refresh_job, раз в день), без
// ручного способа обновить прямо сейчас.

function refreshIconSvg() {
  return (
    '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" ' +
    'stroke-linecap="round" stroke-linejoin="round" width="16" height="16">' +
    '<path d="M3 12a9 9 0 0 1 15-6.7L21 8"/><path d="M21 3v5h-5"/>' +
    '<path d="M21 12a9 9 0 0 1-15 6.7L3 16"/><path d="M8 16H3v5"/></svg>'
  );
}

export function createAiSummaryWidget(ctx) {
  const { api, escapeHtml } = ctx;
  let container = null;

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

  async function regenerate() {
    const current = container.querySelector(".ai-summary-text")?.textContent || null;
    renderShell(current, true);
    try {
      const summary = await api("/miniapp/api/analytics/summary/regenerate", { method: "POST" });
      renderShell(summary.text, false);
    } catch (e) {
      renderShell(current, false);
      alert("Не удалось перегенерировать.");
    }
  }

  return {
    id: "ai-summary",
    async mount(el) {
      container = el;
      container.innerHTML = '<div class="chart-empty">Загрузка…</div>';
      try {
        const summary = await api("/miniapp/api/analytics/summary");
        renderShell(summary.text, false);
      } catch (e) {
        container.innerHTML = '<div class="chart-empty">Не удалось загрузить.</div>';
      }
    },
    unmount() {
      container = null;
    },
    async refresh() {
      if (container) await this.mount(container);
    },
  };
}
