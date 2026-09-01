// Виджет "Проекты" (диаграмма Ганта) — перенесён из renderGanttChart/
// packGanttRows, Phase 24/29/41, без изменений в логике упаковки строк
// или шкалы. Единственное новое здесь — независимость от места мутации
// проектов: раньше loadProjects/createProject/правка проекта в
// index.html дёргали renderGanttChart() по имени напрямую; теперь
// виджет сам подписывается на bus ("projects:changed") и обновляется
// собой — код задач/проектов вообще не знает о существовании Ганта.

const GANTT_PX_PER_DAY = 10; // фиксированный масштаб — только так есть, что скроллить

// Непересекающиеся по времени проекты одной сферы — в одну строку.
// Жадный алгоритм упаковки интервалов ("минимум переговорных комнат
// под непересекающиеся встречи"): группируем по сфере (её отсутствие —
// тоже группа), внутри группы сортируем по началу и кладём каждый
// проект в первую строку, чей последний элемент уже закончился к его
// началу; не нашлось такой — заводим новую строку.
export function packGanttRows(projects) {
  const groups = new Map();
  for (const p of projects) {
    const key = p.sphere || "";
    if (!groups.has(key)) groups.set(key, []);
    groups.get(key).push(p);
  }
  const rows = [];
  for (const group of groups.values()) {
    const sorted = [...group].sort((a, b) => new Date(a.start_date) - new Date(b.start_date));
    const rowsInGroup = []; // { items: [...], lastEnd: <ms> }
    for (const p of sorted) {
      const start = new Date(p.start_date).getTime();
      const end = new Date(p.end_date).getTime();
      const row = rowsInGroup.find((r) => start >= r.lastEnd);
      if (row) {
        row.items.push(p);
        row.lastEnd = end;
      } else {
        rowsInGroup.push({ items: [p], lastEnd: end });
      }
    }
    rows.push(...rowsInGroup.map((r) => r.items));
  }
  return rows;
}

export function createGanttChartWidget(ctx) {
  const { escapeHtml, getMonthNamesFull, getProjectsData, bus } = ctx;
  let container = null;
  let onProjectsChanged = null;

  function render() {
    container.innerHTML = '<p class="chart-title">Проекты</p>';
    const withDates = getProjectsData().filter((p) => p.start_date && p.end_date);
    if (withDates.length === 0) {
      container.innerHTML += '<div class="chart-empty">Нет проектов со сроками</div>';
      return;
    }

    const starts = withDates.map((p) => new Date(p.start_date).getTime());
    const ends = withDates.map((p) => new Date(p.end_date).getTime());
    const min = Math.min(...starts);
    const max = Math.max(...ends);
    const totalDays = Math.max(Math.ceil((max - min) / 86400000), 1);
    const canvasW = totalDays * GANTT_PX_PER_DAY;
    const dayToPx = (ms) => ((ms - min) / 86400000) * GANTT_PX_PER_DAY;

    // Шкала месяцев + линия "сегодня".
    const monthTicks = [];
    const cursor = new Date(min);
    cursor.setDate(1);
    while (cursor.getTime() <= max) {
      const x = Math.max(0, dayToPx(cursor.getTime()));
      // Если самый ранний проект начинается в последний день месяца
      // (напр. 31 августа), 1-е число ЭТОГО месяца уходит в
      // отрицательный x и прижимается к 0, а 1-е число СЛЕДУЮЩЕГО
      // месяца оказывается буквально в одном дне правее — подписи
      // накладываются. Пропускаем метку, если не отстоит от предыдущей
      // хотя бы на ширину подписи.
      const prev = monthTicks[monthTicks.length - 1];
      if (!prev || x - prev.x >= 40) {
        monthTicks.push({
          x,
          label: `${getMonthNamesFull()[cursor.getMonth()].slice(0, 3)} ${cursor.getFullYear()}`,
        });
      }
      cursor.setMonth(cursor.getMonth() + 1);
    }
    const axisHtml = monthTicks
      .map((t) => `<span class="gantt-axis-tick" style="left:${t.x}px">${t.label}</span>`)
      .join("");

    const now = Date.now();
    const todayX = dayToPx(now);
    const todayLineHtml =
      todayX >= 0 && todayX <= canvasW ? `<div class="gantt-today-line" style="left:${todayX}px"></div>` : "";

    const packedRows = packGanttRows(withDates);
    const rowsHtml = packedRows
      .map((items) => {
        const labels = items
          .map((p) => {
            const left = dayToPx(new Date(p.start_date).getTime());
            const width = Math.max(dayToPx(new Date(p.end_date).getTime()) - left, 4);
            const title = escapeHtml(p.title);
            return `<span class="gantt-item-label" style="left:${left}px;max-width:${width}px" title="${title}">${title}</span>`;
          })
          .join("");
        const bars = items
          .map((p) => {
            const left = dayToPx(new Date(p.start_date).getTime());
            const width = Math.max(dayToPx(new Date(p.end_date).getTime()) - left, 4);
            const pct = p.task_count ? Math.round((p.done_count / p.task_count) * 100) : 0;
            const progressWidth = width * (pct / 100);
            return (
              `<div class="gantt-bar" style="left:${left}px;width:${width}px;"></div>` +
              `<div class="gantt-bar-progress" style="left:${left}px;width:${progressWidth}px;"></div>`
            );
          })
          .join("");
        return (
          '<div class="gantt-row">' +
          `<div class="gantt-row-labels">${labels}</div>` +
          `<div class="gantt-track">${bars}</div>` +
          "</div>"
        );
      })
      .join("");

    container.innerHTML +=
      '<div class="gantt-scroll" id="gantt-scroll">' +
      `<div style="width:${canvasW}px">` +
      `<div class="gantt-axis">${axisHtml}</div>` +
      `<div class="gantt-body">${todayLineHtml}${rowsHtml}</div>` +
      "</div></div>";

    // Центрируем на "сегодня" сразу — иначе можно оказаться в самом
    // начале шкалы, далеко от актуального.
    const scrollEl = document.getElementById("gantt-scroll");
    scrollEl.scrollLeft = Math.max(0, todayX - scrollEl.clientWidth / 2);
  }

  return {
    id: "gantt-chart",
    async mount(el) {
      container = el;
      render();
      onProjectsChanged = () => this.refresh();
      bus.addEventListener("projects:changed", onProjectsChanged);
    },
    unmount() {
      if (onProjectsChanged) bus.removeEventListener("projects:changed", onProjectsChanged);
      onProjectsChanged = null;
      container = null;
    },
    async refresh() {
      if (container) render();
    },
  };
}
