import { useEffect, useState } from "react";
import { readDraft, writeDraft } from "../services/drafts";

/**
 * useState that survives leaving the page: the value is kept in memory for the
 * signed-in user (services/drafts.js) and restored when the component mounts
 * again under the same `key`. A null `key` behaves exactly like useState.
 */
export function useDraft(key, initial) {
  const [value, setValue] = useState(() => {
    const saved = key == null ? undefined : readDraft(key);
    if (saved !== undefined) return saved;
    return typeof initial === "function" ? initial() : initial;
  });
  useEffect(() => {
    if (key != null) writeDraft(key, value);
  }, [key, value]);
  return [value, setValue];
}
