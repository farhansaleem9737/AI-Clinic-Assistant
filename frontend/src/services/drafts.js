// Unfinished work (a booking in progress, a list's search and page) kept for
// the signed-in user while they visit other pages (D107).
//
// - In memory by default: gone on sign-out, on another account, or on reload.
// - A few non-sensitive fields may also survive a reload (sessionStorage, this
//   tab only): versioned, scoped to the user, with an expiry, and validated by
//   the caller when read back. Never passwords, tokens, files or medical text.

const memory = new Map();
let owner = null;

const PREFIX = "clinic-draft:";
const VERSION = 1;

/** Whose drafts these are; another user (or none) starts empty. */
export function setDraftOwner(userId) {
  const next = userId ?? null;
  if (next === owner) return;
  memory.clear();
  owner = next;
}

/** Sign-out: forget every draft, including those kept for a reload. */
export function clearDrafts() {
  memory.clear();
  try {
    for (const key of Object.keys(sessionStorage)) if (key.startsWith(PREFIX)) sessionStorage.removeItem(key);
  } catch {
    // Storage unavailable (private mode, blocked): nothing was kept there.
  }
}

const memoryKey = (key) => `${owner}:${key}`;
export const readDraft = (key) => memory.get(memoryKey(key));
export function writeDraft(key, value) {
  if (value === undefined) memory.delete(memoryKey(key));
  else memory.set(memoryKey(key), value);
}
export function forgetDrafts(prefix) {
  for (const key of [...memory.keys()]) if (key.startsWith(memoryKey(prefix))) memory.delete(key);
  removeStoredDraft(prefix);
}

const storageKey = (key) => `${PREFIX}${owner}:${key}`;

/** Keep `value` (plain, non-sensitive JSON) for a reload of this tab, for `ttlMs`. */
export function storeDraft(key, value, ttlMs) {
  if (!owner) return;
  try {
    sessionStorage.setItem(storageKey(key), JSON.stringify({ v: VERSION, owner, expires: Date.now() + ttlMs, value }));
  } catch {
    // Full or unavailable: the draft is still kept in memory.
  }
}

/** The stored value if it is this user's, current and passes `isValid`; otherwise null (and removed). */
export function loadStoredDraft(key, isValid) {
  if (!owner) return null;
  try {
    const raw = sessionStorage.getItem(storageKey(key));
    if (raw == null) return null;
    const saved = JSON.parse(raw);
    if (saved?.v === VERSION && saved.owner === owner && saved.expires > Date.now() && isValid(saved.value)) return saved.value;
  } catch {
    // Malformed or unreadable: treated as absent.
  }
  removeStoredDraft(key);
  return null;
}

export function removeStoredDraft(key) {
  try {
    sessionStorage.removeItem(storageKey(key));
  } catch {
    // Unavailable: nothing to remove.
  }
}
