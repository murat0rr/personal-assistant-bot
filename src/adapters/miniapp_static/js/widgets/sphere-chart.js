// Виджет "Задачи по сферам" — листаемый по месяцам (Phase 53), сама
// столбчатая диаграмма — без изменений в логике (Phase 24/33/34).
// Phase 89: свой прев/некст + свайп убраны — месяцем теперь управляет
// общий банер на вкладке "Аналитика" (index.html, bus-событие
// "analytics:month-changed"), тот же приём, что уже был у
// goal-progress-chart.js/gantt-chart.js для своих bus-событий.

// Тот же порядок, что SPHERES на бэкенде — фиксированная палитра, чтобы
// цвет сферы был одним и тем же везде, где она встречается на странице.
// Дублируется тут намеренно (не через ctx) — больше нигде во виджетах
// аналитики не нужна, а не-виджетный код (например, выбор сферы в форме
// задачи) исторически не завязан на эту палитру, свои цвета не берёт.
const SPHERE_COLORS = {
  учёба: "#5b8def",
  работа: "#e0a52c",
  спорт: "#4caf7d",
  развитие: "#a06fe0",
  отношения: "#e0637a",
};

function sphereColor(sphere) {
  return SPHERE_COLORS[sphere] || "var(--text-muted)";
}

export function createSphereChartWidget(ctx) {
  const { api, escapeHtml, bus, getAnalyticsSelectedMonth, pad2 } = ctx;
  let container = null;
  let year = null;
  let month = null;
  let onMonthChanged = null;

  function render(data) {
    const spheres = data.spheres || [];
    const header = '<p class="chart-title">Задачи по сферам</p>';

    const total = spheres.reduce((sum, s) => sum + s.count, 0);
    if (total === 0) {
      container.innerHTML = `${header}<div class="chart-empty">В этом месяце нет задач со сферой</div>`;
      return;
    }

    // Столбчатая диаграмма — один столбец на сферу, нижняя часть темнее
    // (выполнено), верхняя — обычный цвет сферы (не выполнено). График
    // слева, легенда справа.
    const max = Math.max(1, ...spheres.map((s) => s.count));
    const w = 100;
    const h = 130;
    const padLeft = 20;
    const padBottom = 4;
    const padTop = 4;
    const plotW = w - padLeft - 4;
    const plotH = h - padTop - padBottom;
    const barGap = 6;
    const barW = (plotW - barGap * (spheres.length - 1)) / spheres.length;

    const yTicks = Array.from(new Set([0, Math.round(max / 2), max]));
    const yToPx = (v) => padTop + plotH - (v / max) * plotH;
    const gridLines = yTicks
      .map((v) => {
        const y = yToPx(v);
        return (
          `<line x1="${padLeft}" y1="${y}" x2="${w - 4}" y2="${y}" stroke="var(--hairline)" stroke-width="1"/>` +
          `<text x="${padLeft - 4}" y="${y + 3}" font-size="8" fill="var(--text-muted)" text-anchor="end">${v}</text>`
        );
      })
      .join("");

    const bars = spheres
      .map((s, i) => {
        const color = sphereColor(s.sphere);
        const darker = `color-mix(in srgb, ${color} 65%, black 35%)`;
        const x = padLeft + i * (barW + barGap);
        const totalH = (s.count / max) * plotH;
        const doneH = s.count ? totalH * (s.done / s.count) : 0;
        const notDoneH = totalH - doneH;
        const topY = padTop + plotH - totalH;
        const doneY = padTop + plotH - doneH;
        let bar = "";
        if (notDoneH > 0) {
          bar += `<rect x="${x}" y="${topY}" width="${barW}" height="${notDoneH}" fill="${color}"/>`;
        }
        if (doneH > 0) {
          bar += `<rect x="${x}" y="${doneY}" width="${barW}" height="${doneH}" fill="${darker}"/>`;
        }
        return bar;
      })
      .join("");

    const svg = `<svg viewBox="0 0 ${w} ${h}" width="${w}" height="${h}" style="flex-shrink:0">${gridLines}${bars}</svg>`;
    const legend = spheres
      .map(
        (s) =>
          `<div class="sphere-legend-row"><span class="sphere-swatch" style="background:${sphereColor(s.sphere)}"></span>` +
          `<span class="sphere-legend-label">${escapeHtml(s.sphere)}</span>` +
          `<span class="sphere-legend-value">${s.done}/${s.count} · ${Math.round((s.count / total) * 100)}%</span></div>`
      )
      .join("");
    container.innerHTML = `${header}<div class="sphere-chart-row">${svg}<div class="sphere-legend">${legend}</div></div>`;
  }

  async function load() {
    // Защита от гонки (Phase 89, найдена живой проверкой на
    // ai-summary.js — тот же механизм здесь): свайп на другой месяц, пока
    // предыдущий load() ещё в полёте, не должен дать его устаревшему
    // ответу перезаписать уже отрисованный новый месяц.
    const requestedKey = `${year}-${pad2(month)}`;
    container.innerHTML = '<div class="chart-empty">Загрузка…</div>';
    try {
      const data = await api(`/miniapp/api/analytics/spheres?month=${requestedKey}`);
      if (requestedKey !== `${year}-${pad2(month)}`) return;
      render(data);
    } catch (e) {
      if (requestedKey !== `${year}-${pad2(month)}`) return;
      container.innerHTML = '<div class="chart-empty">Не удалось загрузить.</div>';
    }
  }

  return {
    id: "sphere-chart",
    async mount(el) {
      container = el;
      const sel = getAnalyticsSelectedMonth();
      year = sel.year;
      month = sel.month;
      onMonthChanged = ({ detail }) => {
        year = detail.year;
        month = detail.month;
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
