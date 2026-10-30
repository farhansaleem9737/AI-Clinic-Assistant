// The weekly schedule as the page edits it: per day, `enabled` and a list of
// { start, end } wall-clock times ("HH:MM") in the doctor's timezone.

export function draftFrom(schedule) {
  return schedule.days.map((d) => ({
    weekday: d.weekday,
    enabled: d.enabled,
    slot_minutes: d.slot_minutes,
    intervals: d.intervals.map((i) => ({ start: i.start_time.slice(0, 5), end: i.end_time.slice(0, 5) })),
  }));
}

// What PUT /weekly-schedule takes. A day that is off sends no hours.
export function payloadFrom(days) {
  return days.map((d) => ({
    weekday: d.weekday,
    enabled: d.enabled,
    slot_minutes: d.slot_minutes,
    intervals: d.enabled ? d.intervals.map((i) => ({ start_time: i.start, end_time: i.end })) : [],
  }));
}

// Problems with one day's time ranges, or "" when they are fine. The API
// checks the same rules again.
export function intervalsError(intervals) {
  if (intervals.length === 0) return "Add working hours, or switch the day off.";
  for (const i of intervals) {
    if (!i.start || !i.end) return "Enter a start and an end time.";
    if (i.start >= i.end) return "The end time must be after the start time.";
  }
  const sorted = [...intervals].sort((a, b) => a.start.localeCompare(b.start));
  for (let k = 1; k < sorted.length; k += 1) {
    if (sorted[k].start < sorted[k - 1].end) return "Time ranges on one day must not overlap.";
  }
  return "";
}
