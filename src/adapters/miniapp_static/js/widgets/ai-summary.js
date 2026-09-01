// Виджет "ИИ-аналитика" — перенесён из renderAiSummary без изменений.

export function createAiSummaryWidget(ctx) {
  const { api, escapeHtml } = ctx;
  let container = null;

  return {
    id: "ai-summary",
    async mount(el) {
      container = el;
      container.innerHTML = '<div class="chart-empty">Загрузка…</div>';
      try {
        const summary = await api("/miniapp/api/analytics/summary");
        container.innerHTML = '<p class="chart-title">ИИ-аналитика</p>';
        container.innerHTML += `<div class="ai-summary-text">${summary.text ? escapeHtml(summary.text) : "Пока не набралось данных для анализа."}</div>`;
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
