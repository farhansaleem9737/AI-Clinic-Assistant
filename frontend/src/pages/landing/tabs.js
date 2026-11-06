// Arrow keys, Home and End move between tabs (WAI-ARIA tabs pattern).
export function moveTab(event, items, current, select, idPrefix) {
  const index = items.findIndex((item) => item.id === current);
  const next = { ArrowRight: index + 1, ArrowLeft: index - 1, Home: 0, End: items.length - 1 }[event.key];
  if (next === undefined) return;
  event.preventDefault();
  const item = items[(next + items.length) % items.length];
  select(item.id);
  document.getElementById(`${idPrefix}${item.id}`)?.focus();
}
