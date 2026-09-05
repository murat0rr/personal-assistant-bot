// Прогресс по целям — недельные/месячные/годовые (Phase 67, фидбек:
// "3 графика недельной/месячной/годовой аналитики целей... отсортированы
// от самых успешных к неуспешным, выполненные в самом верху,
// подсвечены"). Одна фабрика на все три тира — регистрируется в
// registry.js три раза с разным tier/title, тот же приём, что и любой
// другой виджет (create(ctx) => объект mount/unmount/refresh).
//
// Данные берутся из уже загруженных целей (getGoalsData — весь список,
// все тиры сразу, см. index.html::loadGoals), фильтруются по tier
// здесь же — отдельного похода в сеть не нужно, тот же источник, что
// уже кормит вкладку "Проекты".

const TIER_TITLES = {
  weekly: "Цели — неделя",
  monthly: "Цели — месяц",
  yearly: "Цели — год",
};

export function createGoalProgressChartWidget(ctx, tier) {
  const { escapeHtml, getGoalsData, bus } = ctx;
  let container = null;
  let onGoalsChanged = null;

  function percentDone(goal) {
    if (!goal.task_count) return null; // нет задач — не 0%, а "нечего оценивать"
    return Math.round((goal.done_count / goal.task_count) * 100);
  }

  function render() {
    const goals = getGoalsData().filter((g) => g.tier === tier);
    container.innerHTML = `<p class="chart-title">${TIER_TITLES[tier]}</p>`;
    if (goals.length === 0) {
      container.innerHTML += '<div class="chart-empty">Нет целей на этот период</div>';
      return;
    }

    // Самые успешные — вверху (% выполнения по убыванию); без единой
    // задачи — в самый низ, оценивать нечего, не "провал".
    const sorted = [...goals].sort((a, b) => {
      const pa = percentDone(a);
      const pb = percentDone(b);
      if (pa === null && pb === null) return 0;
      if (pa === null) return 1;
      if (pb === null) return -1;
      return pb - pa;
    });

    const rows = sorted
      .map((g) => {
        const pct = percentDone(g);
        const title = escapeHtml(g.title);
        if (pct === null) {
          return (
            '<div class="goal-progress-row">' +
            `<div class="goal-progress-head"><span class="goal-progress-title">${title}</span>` +
            '<span class="goal-progress-count">нет задач</span></div>' +
            '<div class="goal-progress-track"></div>' +
            "</div>"
          );
        }
        // 100% — небольшая подсветка (Phase 67: "подсвечены, чтобы было
        // приятно глазу") — не раскрашиваем весь список по рангу
        // отдельными цветами, порядок сортировки и так несёт смысл
        // ранга; выделяем только реально завершённые цели.
        const highlighted = pct === 100 ? " goal-progress-row-done" : "";
        return (
          `<div class="goal-progress-row${highlighted}">` +
          `<div class="goal-progress-head"><span class="goal-progress-title">${title}</span>` +
          `<span class="goal-progress-count">${g.done_count}/${g.task_count}</span></div>` +
          '<div class="goal-progress-track">' +
          `<div class="goal-progress-fill" style="width:${pct}%"></div>` +
          "</div></div>"
        );
      })
      .join("");

    container.innerHTML += `<div class="goal-progress-list">${rows}</div>`;
  }

  return {
    id: `goal-progress-${tier}`,
    async mount(el) {
      container = el;
      render();
      onGoalsChanged = () => this.refresh();
      bus.addEventListener("goals:changed", onGoalsChanged);
    },
    unmount() {
      if (onGoalsChanged) bus.removeEventListener("goals:changed", onGoalsChanged);
      onGoalsChanged = null;
      container = null;
    },
    async refresh() {
      if (container) render();
    },
  };
}
