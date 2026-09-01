// Виджет "Выполнено задач" — листаемый график месяца (перенесён из
// renderMonthChart/loadMonthChart/goToAnalyticsMonth/attachMonthChartSwipe,
// Phase 24/29/41, без изменений в логике). Сохранены оба бага-фикса
// Phase 41: единственное присваивание innerHTML за рендер (иначе
// += пересоздаёт узлы кнопок навигации и рвёт уже назначенный .onclick
// — баг, пойманный на живой проверке) и dataset.swipeAttached-защита от
// повторного навешивания слушателей свайпа при каждом рендере.

export function createMonthChartWidget(ctx) {
  const { api, escapeHtml, getMonthNamesFull, pad2, getBoardState } = ctx;
  let container = null;
  // Своё состояние месяца — не синхронизировано с месячным календарём,
  // это разные виджеты (см. исходный комментарий у analyticsMonthYear).
  let year = null;
  let month = null;

  function render(data) {
    const nav =
      '<div class="month-chart-nav">' +
      '<button type="button" class="small-btn" id="analytics-month-prev" aria-label="Предыдущий месяц">‹</button>' +
      `<span>${getMonthNamesFull()[data.month - 1]} ${data.year}</span>` +
      '<button type="button" class="small-btn" id="analytics-month-next" aria-label="Следующий месяц">›</button>' +
      "</div>";
    const header = `<p class="chart-title">Выполнено задач</p>${nav}`;

    function attachNav() {
      document.getElementById("analytics-month-prev").onclick = () => goTo(-1);
      document.getElementById("analytics-month-next").onclick = () => goTo(1);
      attachSwipe();
    }

    const counts = data.all_counts || [];
    if (counts.every((c) => c === 0)) {
      container.innerHTML = `${header}<div class="chart-empty">В этом месяце пока ничего не отмечено</div>`;
      attachNav();
      return;
    }

    const max = Math.max(1, ...counts);
    const w = 300;
    const h = 110;
    const padLeft = 18;
    const padBottom = 12;
    const padTop = 4;
    const plotW = w - padLeft - 2;
    const plotH = h - padTop - padBottom;
    const barW = plotW / counts.length;

    const isWeekend = (dayNum) => {
      const wd = new Date(Date.UTC(data.year, data.month - 1, dayNum)).getUTCDay();
      return wd === 0 || wd === 6; // вс=0, сб=6
    };

    const yTicks = Array.from(new Set([0, Math.round(max / 2), max]));
    const yToPx = (v) => padTop + plotH - (v / max) * plotH;
    const gridLines = yTicks
      .map((v) => {
        const y = yToPx(v);
        return (
          `<line x1="${padLeft}" y1="${y}" x2="${w - 2}" y2="${y}" stroke="var(--hairline)" stroke-width="1"/>` +
          `<text x="${padLeft - 4}" y="${y + 3}" font-size="8" fill="var(--text-muted)" text-anchor="end">${v}</text>`
        );
      })
      .join("");

    const bars = counts
      .map((c, i) => {
        const barH = (c / max) * plotH;
        const x = padLeft + i * barW;
        const y = padTop + plotH - barH;
        const opacity = isWeekend(i + 1) ? 0.5 : 1;
        return `<rect x="${x + 0.5}" y="${y}" width="${Math.max(barW - 1, 1)}" height="${Math.max(barH, c > 0 ? 1 : 0)}" fill="var(--accent)" opacity="${opacity}" rx="1"/>`;
      })
      .join("");

    const boardState = getBoardState();
    const todayIso = boardState.days.today ? boardState.days.today.date : null;
    const isCurrentMonth =
      todayIso && todayIso.slice(0, 4) == data.year && Number(todayIso.slice(5, 7)) === data.month;
    const todayDay = isCurrentMonth ? Number(todayIso.slice(8, 10)) : null;
    const todayLine =
      todayDay && todayDay <= counts.length
        ? `<line x1="${padLeft + (todayDay - 0.5) * barW}" y1="${padTop}" x2="${padLeft + (todayDay - 0.5) * barW}" y2="${padTop + plotH}" stroke="var(--neutral-blue)" stroke-width="1.5" stroke-dasharray="2 2"/>`
        : "";

    const xLabels = counts
      .map((c, i) => {
        const dayNum = i + 1;
        if (dayNum !== 1 && dayNum !== counts.length && dayNum % 5 !== 0) return "";
        const x = padLeft + i * barW + barW / 2;
        return `<text x="${x}" y="${h - 1}" font-size="8" fill="var(--text-muted)" text-anchor="middle">${dayNum}</text>`;
      })
      .join("");

    const svg = `<svg viewBox="0 0 ${w} ${h}" width="100%" height="${h}" preserveAspectRatio="none">${gridLines}${bars}${todayLine}${xLabels}</svg>`;

    const projects = data.projects || [];
    let projectsHtml = "";
    if (projects.length) {
      const rows = projects
        .map(
          (p) =>
            `<div class="month-project-row"><span class="month-project-title">${escapeHtml(p.title)}</span>` +
            `<span class="month-project-count">${p.total}</span></div>`
        )
        .join("");
      projectsHtml = `<p class="chart-title" style="margin-top:14px;">По проектам</p>${rows}`;
    }

    container.innerHTML = `${header}${svg}${projectsHtml}`;
    attachNav();
  }

  async function load() {
    container.innerHTML = '<div class="chart-empty">Загрузка…</div>';
    try {
      const key = `${year}-${pad2(month)}`;
      const data = await api(`/miniapp/api/analytics/month?month=${key}`);
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
    id: "month-chart",
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
