import { useState, useEffect } from "react";
import api from "../services/api";
import { AuthContext } from "./AuthContextObject";

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [token, setToken] = useState(localStorage.getItem("token"));

  const fetchCurrentUser = async () => {
    const res = await api.get("/auth/me");
    setUser(res.data);
  };

  useEffect(() => {
    async function rehydrateUser() {
      if (!token || user) return;

      try {
        await fetchCurrentUser();
      } catch {
        // Token invalid/expired and refresh failed — clear everything
        localStorage.removeItem("token");
        localStorage.removeItem("refresh_token");
        setToken(null);
        setUser(null);
      }
    }

    rehydrateUser();
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  const login = async (email, password) => {
    const res = await api.post("/auth/login", { email, password });
    localStorage.setItem("token", res.data.access_token);
    localStorage.setItem("refresh_token", res.data.refresh_token);
    setToken(res.data.access_token);
    await fetchCurrentUser();
  };

  // Self-registration always creates a patient; the backend decides the role.
  const register = async (name, email, password) => {
    await api.post("/auth/register", { name, email, password });
    await login(email, password);
  };

  const logout = async () => {
    const refreshToken = localStorage.getItem("refresh_token");
    if (refreshToken) {
      try {
        await api.post("/auth/logout", { refresh_token: refreshToken });
      } catch {
        // Ignore errors here — log out locally regardless
      }
    }
    localStorage.removeItem("token");
    localStorage.removeItem("refresh_token");
    setToken(null);
    setUser(null);
  };

  return (
    <AuthContext.Provider value={{ user, token, login, register, logout, fetchCurrentUser }}>
      {children}
    </AuthContext.Provider>
  );
}