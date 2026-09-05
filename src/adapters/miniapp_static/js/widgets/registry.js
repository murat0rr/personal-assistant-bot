// Единственное место, где перечислены все виджеты аналитики (Phase 46).
// Добавить новый график в будущем — один новый файл с фабрикой
// createXWidget(ctx) + одна строка здесь; ни panel.js, ни index.html
// трогать не нужно.

import { createSphereChartWidget } from "./sphere-chart.js";
import { createMonthChartWidget } from "./month-chart.js";
import { createGanttChartWidget } from "./gantt-chart.js";
import { createAiSummaryWidget } from "./ai-summary.js";
import { createGoalProgressChartWidget } from "./goal-progress-chart.js";

export const WIDGET_REGISTRY = [
  { id: "sphere-chart", title: "Задачи по сферам", defaultEnabled: true, create: createSphereChartWidget },
  { id: "month-chart", title: "Выполнено задач", defaultEnabled: true, create: createMonthChartWidget },
  { id: "gantt-chart", title: "Проекты", defaultEnabled: true, create: createGanttChartWidget },
  { id: "ai-summary", title: "ИИ-аналитика", defaultEnabled: true, create: createAiSummaryWidget },
  // Прогресс по целям (Phase 67, фидбек) — одна фабрика на все три
  // тира (см. goal-progress-chart.js), три отдельные строки реестра —
  // тот же приём, что и у остальных виджетов: отдельно включаются/
  // выключаются в настройках, отдельно перерисовываются.
  {
    id: "goal-progress-weekly",
    title: "Цели — неделя",
    defaultEnabled: true,
    create: (ctx) => createGoalProgressChartWidget(ctx, "weekly"),
  },
  {
    id: "goal-progress-monthly",
    title: "Цели — месяц",
    defaultEnabled: true,
    create: (ctx) => createGoalProgressChartWidget(ctx, "monthly"),
  },
  {
    id: "goal-progress-yearly",
    title: "Цели — год",
    defaultEnabled: true,
    create: (ctx) => createGoalProgressChartWidget(ctx, "yearly"),
  },
];
