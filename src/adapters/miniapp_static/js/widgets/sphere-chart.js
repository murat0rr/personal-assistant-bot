// Виджет "Задачи по сферам" — листаемый по месяцам (Phase 53, тот же
// приём навигации/свайпа, что уже есть у month-chart.js), сама
// столбчатая диаграмма — без изменений в логике (Phase 24/33/34).

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
  const { api, escapeHtml, getMonthNamesFull, pad2 } = ctx;
  let container = null;
  // Своё состояние месяца — не синхронизировано ни с month-chart, ни с
  // месячным календарём, это независимые виджеты (тот же принцип, что
  // уже описан у month-chart.js::year/month).
  let year = null;
  let month = null;

  function render(data) {
    const spheres = data.spheres || [];
    const nav =
      '<div class="month-chart-nav">' +
      '<button type="button" class="small-btn" id="sphere-chart-prev" aria-label="Предыдущий месяц">‹</button>' +
      `<span>${getMonthNamesFull()[data.month - 1]} ${data.year}</span>` +
      '<button type="button" class="small-btn" id="sphere-chart-next" aria-label="Следующий месяц">›</button>' +
      "</div>";
    const header = `<p class="chart-title">Задачи по сферам</p>${nav}`;

    function attachNav() {
      document.getElementById("sphere-chart-prev").onclick = () => goTo(-1);
      document.getElementById("sphere-chart-next").onclick = () => goTo(1);
      attachSwipe();
    }

    const total = spheres.reduce((sum, s) => sum + s.count, 0);
    if (total === 0) {
      container.innerHTML = `${header}<div class="chart-empty">В этом месяце нет задач со сферой</div>`;
      attachNav();
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
    attachNav();
  }

  async function load() {
    container.innerHTML = '<div class="chart-empty">Загрузка…</div>';
    try {
      const key = `${year}-${pad2(month)}`;
      const data = await api(`/miniapp/api/analytics/spheres?month=${key}`);
      render(data);
    } catch (e) {
      container.innerHTML = '<div class="chart-empty">Не удалось загрузить.</div>';
    }
  }

  async function goTo(delta) {
    let m = month + delta;
    let y = year;
    if (m < 1) {
      m = 12;
      y -= 1;
    } else if (m > 12) {
      m = 1;
      y += 1;
    }
    year = y;
    month = m;
    await load();
  }

  function attachSwipe() {
    if (container.dataset.swipeAttached) return;
    container.dataset.swipeAttached = "1";
    let startX = null;
    let startY = null;
    let pointerId = null;
    container.addEventListener("pointerdown", (e) => {
      if (e.target.closest("button")) return;
      startX = e.clientX;
      startY = e.clientY;
      pointerId = e.pointerId;
    });
    container.addEventListener("pointerup", (e) => {
      if (startX === null || e.pointerId !== pointerId) return;
      const dx = e.clientX - startX;
      const dy = e.clientY - startY;
      startX = null;
      if (Math.abs(dx) > 40 && Math.abs(dx) > Math.abs(dy) * 1.5) {
        goTo(dx < 0 ? 1 : -1);
      }
    });
  }

  return {
    id: "sphere-chart",
    async mount(el) {
      container = el;
      if (year === null) {
        const now = new Date();
        year = now.getFullYear();
        month = now.getMonth() + 1;
      }
      await load();
    },
    unmount() {
      container = null;
    },
    async refresh() {
      if (container) await load();
    },
  };
}
