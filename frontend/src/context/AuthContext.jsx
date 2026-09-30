import { useCallback, useEffect, useMemo, useState } from "react";
import api, {
  csrfHeaders,
  mayHaveSession,
  refreshAccessToken,
  setAccessToken,
  setSessionExpiredHandler,
} from "../services/api";
import { AuthContext } from "./AuthContextObject";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  // True until the first session-restore attempt finishes, so guarded routes
  // don't bounce a logged-in user to /login during a page reload.
  // A visitor with no session cookie has nothing to restore.
  const [initializing, setInitializing] = useState(mayHaveSession);

  const fetchCurrentUser = useCallback(async () => {
    const res = await api.get("/auth/me");
    setUser(res.data);
    return res.data;
  }, []);

  const clearSession = useCallback(() => {
    setAccessToken(null);
    setUser(null);
  }, []);

  useEffect(() => {
    setSessionExpiredHandler(clearSession);

    if (!mayHaveSession()) return;
    // Restore the session from the HttpOnly refresh cookie.
    refreshAccessToken()
      .then(fetchCurrentUser)
      .catch(clearSession)
      .finally(() => setInitializing(false));
  }, [clearSession, fetchCurrentUser]);

  const login = useCallback(
    async (email, password) => {
      const res = await api.post("/auth/login", { email, password });
      setAccessToken(res.data.access_token);
      return fetchCurrentUser();
    },
    [fetchCurrentUser]
  );

  // Self-registration always creates a patient (login + profile); the backend decides the role.
  const register = useCallback(
    async (data) => {
      await api.post("/auth/register", data);
      return login(data.email, data.password);
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
