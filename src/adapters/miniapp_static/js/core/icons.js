// Иконки (Phase 57) — чистые функции без зависимости от состояния
// приложения, вынесены из index.html дословно. Сознательно НЕ ES-модуль
// (в отличие от js/widgets/*.js) — эти функции вызываются как обычные
// глобальные идентификаторы из ~100 мест по всему классическому
// скрипту index.html, а обычные <script src> без type="module" на одной
// странице живут в общей глобальной области видимости: верхнеуровневые
// function-объявления здесь становятся вызываемыми оттуда без единой
// правки на местах вызова. Подключается ДО основного <script>.

function icon(inner, size) {
  return `<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" width="${size}" height="${size}">${inner}</svg>`;
}
function checkIcon() {
  return '<svg viewBox="0 0 16 16" fill="none"><path d="M3 8.5l3 3 7-7" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"/></svg>';
}
function calendarIcon() {
  return icon(
    '<rect x="3" y="5" width="18" height="16" rx="2"/><line x1="3" y1="10" x2="21" y2="10"/><line x1="8" y1="2.5" x2="8" y2="6"/><line x1="16" y1="2.5" x2="16" y2="6"/>',
    16
  );
}
function archiveIcon() {
  return icon('<rect x="4" y="10" width="16" height="10" rx="1"/><path d="M12 3v8M9 8l3 3 3-3"/>', 16);
}
function plusIcon() {
  return icon('<line x1="12" y1="5" x2="12" y2="19"/><line x1="5" y1="12" x2="19" y2="12"/>', 18);
}
function moveToTodayIcon() {
  return icon('<line x1="5" y1="12" x2="19" y2="12"/><path d="M13 6l6 6-6 6"/>', 16);
}
function chevronIcon() {
  return icon('<path d="M6 9l6 6 6-6"/>', 14);
}
function eventPinIcon() {
  return icon('<path d="M12 21c4-4.5 7-8 7-12a7 7 0 10-14 0c0 4 3 7.5 7 12z"/><circle cx="12" cy="9" r="2.3"/>', 13);
}
function gripIcon() {
  return icon('<line x1="4" y1="9" x2="20" y2="9"/><line x1="4" y1="15" x2="20" y2="15"/>', 18);
}
// Кнопка "важная задача" в шторке — само поле теперь показывает
// важность жирным шрифтом (Phase 14), не флажком, но кнопке-тумблеру
// в панели всё равно нужен свой значок.
function importantIcon() {
  return icon('<line x1="12" y1="4" x2="12" y2="13"/><circle cx="12" cy="18" r="1" fill="currentColor"/>', 15);
}
function undoIcon() {
  return icon('<path d="M4 10h9a5 5 0 010 10H9"/><path d="M4 10l5-5M4 10l5 5"/>', 16);
}
// Шестерёнка настройки виджетов аналитики (Phase 46) — рядом с
// заголовком "Аналитика", открывает список включения/отключения
// графиков.
function settingsGearIcon() {
  return icon(
    '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 00.33 1.82l.06.06a2 2 0 11-2.83 2.83l-.06-.06a1.65 1.65 0 00-1.82-.33 1.65 1.65 0 00-1 1.51V21a2 2 0 01-4 0v-.09A1.65 1.65 0 009 19.4a1.65 1.65 0 00-1.82.33l-.06.06a2 2 0 11-2.83-2.83l.06-.06a1.65 1.65 0 00.33-1.82 1.65 1.65 0 00-1.51-1H3a2 2 0 010-4h.09A1.65 1.65 0 004.6 9a1.65 1.65 0 00-.33-1.82l-.06-.06a2 2 0 112.83-2.83l.06.06a1.65 1.65 0 001.82.33H9a1.65 1.65 0 001-1.51V3a2 2 0 014 0v.09a1.65 1.65 0 001 1.51 1.65 1.65 0 001.82-.33l.06-.06a2 2 0 112.83 2.83l-.06.06a1.65 1.65 0 00-.33 1.82V9a1.65 1.65 0 001.51 1H21a2 2 0 010 4h-.09a1.65 1.65 0 00-1.51 1z"/>',
    18
  );
}
// Замок у "Сегодня" в настройке отображений (Phase 50) — эту строку
// нельзя выключить, значок рядом с чекбоксом сигнализирует почему.
function lockIcon() {
  return icon(
    '<rect x="4" y="10" width="16" height="10" rx="2"/><path d="M8 10V7a4 4 0 018 0v3"/>',
    14
  );
}
// Шаблонные задачи (Phase 18) — контур звезды, "избранное/быстрый
// выбор", слева от кнопки подтверждения в строке добавления.
function starIcon() {
  return icon(
    '<path d="M12 3.5l2.6 5.3 5.9.9-4.3 4.1 1 5.8-5.2-2.7-5.2 2.7 1-5.8-4.3-4.1 5.9-.9z"/>',
    18
  );
}
// Иконки жестов для экрана помощи (Phase 37) — узнаваемые метафоры,
// не буквальные скриншоты: точка+кольцо = тап/долгое нажатие (кольцо
// штрихом отличает "долго" от "коротко"), стрелка = свайп, двойная
// стрелка вверх-вниз = перетаскивание/перенос порядка.
function tapGestureIcon() {
  return icon('<circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="7"/>', 16);
}
function longPressGestureIcon() {
  return icon(
    '<circle cx="12" cy="12" r="2" fill="currentColor" stroke="none"/><circle cx="12" cy="12" r="7" stroke-dasharray="2.2 3"/>',
    16
  );
}
function swipeGestureIcon() {
  return icon('<path d="M3 12h15M12 6l6 6-6 6"/>', 16);
}
function dragGestureIcon() {
  return icon('<path d="M12 3v18M7 8l5-5 5 5M7 16l5 5 5-5"/>', 16);
}
// Проекты (Phase 19) — папка, кнопка привязки задачи к проекту.
function projectIcon() {
  return icon(
    '<path d="M3 6a1 1 0 011-1h5l2 2h9a1 1 0 011 1v10a1 1 0 01-1 1H4a1 1 0 01-1-1V6z"/>',
    16
  );
}
