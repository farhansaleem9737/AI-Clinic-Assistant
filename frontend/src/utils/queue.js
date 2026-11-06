// An estimated wait as words: always a range from the server, never a promise.
export const waitText = (wait) =>
  wait ? (wait.max_minutes <= 5 ? "Next, in a few minutes" : `About ${wait.min_minutes}–${wait.max_minutes} min (estimate)`) : "";
