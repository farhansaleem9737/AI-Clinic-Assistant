import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import api, {
  csrfHeaders,
  mayHaveSession,
  refreshAccessToken,
  setAccessToken,
  setSessionExpiredHandler,
} from "../services/api";
import { clearDrafts, setDraftOwner } from "../services/drafts";
import { setCacheOwner } from "../services/queryClient";
import { AuthContext } from "./AuthContextObject";

// A server or network failure (e.g. a dropped database connection) gets one
// more try; a refused session (401/403) does not.
const transient = (err) => !err?.response || err.response.status >= 500;
async function getMe() {
  try {
    return await api.get("/auth/me");
  } catch (err) {
    if (!transient(err)) throw err;
    await new Promise((resolve) => setTimeout(resolve, 800));
    return api.get("/auth/me");
  }
}

// Cached server data and drafts belong to one user: set before the user is.
function setOwner(userId) {
  setCacheOwner(userId);
  setDraftOwner(userId);
}

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // True until the first session-restore attempt finishes, so guarded routes
  // don't bounce a logged-in user to /login during a page reload.
  // A visitor with no session cookie has nothing to restore.
  const [initializing, setInitializing] = useState(mayHaveSession);

  const fetchCurrentUser = useCallback(async () => {
    const res = await getMe();
    setOwner(res.data.id);
    setUser(res.data);
    return res.data;
  }, []);

  // Sign-out or an expired session: nothing of this user stays in memory.
  const clearSession = useCallback(() => {
    setAccessToken(null);
    setOwner(null);
    clearDrafts();
    setUser(null);
  }, []);

  // One restore per provider, although development mode runs effects twice.
  const restoring = useRef(null);
  useEffect(() => {
    setSessionExpiredHandler(clearSession);

    if (!mayHaveSession()) return;
    let live = true;
    // Restore the session from the HttpOnly refresh cookie.
    restoring.current ??= refreshAccessToken().then(getMe);
    restoring.current
      .then((res) => {
        if (!live) return;
        setOwner(res.data.id);
        setUser(res.data);
      })
      .catch(() => live && clearSession())
      .finally(() => live && setInitializing(false));
    return () => {
      live = false;
    };
  }, [clearSession]);

  const login = useCallback(
    // rememberMe: keep the session after the browser closes. Only this flag is
    // sent; the password is used for this one request and never stored.
    async (email, password, rememberMe = false) => {
      const res = await api.post("/auth/login", { email, password, remember_me: rememberMe });
      setAccessToken(res.data.access_token);
      return fetchCurrentUser();
    },
    [fetchCurrentUser]
  );

  // Self-registration always creates a patient (login + profile); the backend decides the role.
  const register = useCallback(
    async (data) => {
      await api.post("/auth/register", data);
      try {
        // Established flow: create the account, then sign in.
        return await login(data.email, data.password);
      } catch (err) {
        // The account exists; only the sign-in step failed. Callers must not
        // report this as a failed registration (the user would retry and be
        // told the email is taken).
        err.accountCreated = true;
        throw err;
      }
    },
    [login]
  );

  const logout = useCallback(async () => {
    try {
      await api.post("/auth/logout", null, { headers: csrfHeaders() });
    } catch {
      // Log out locally regardless.
    }
    clearSession();
  }, [clearSession]);

  // UX only: hides menu items. The backend enforces every permission.
  const can = useCallback((permission) => Boolean(user?.permissions?.includes(permission)), [user]);
  const hasRole = useCallback((role) => Boolean(user?.roles?.includes(role)), [user]);

  const value = useMemo(
    () => ({ user, initializing, login, register, logout, fetchCurrentUser, can, hasRole }),
    [user, initializing, login, register, logout, fetchCurrentUser, can, hasRole]
  );

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}
