import { createContext, useContext, useState, useEffect, useCallback } from "react";
import api, { setAuthToken } from "../lib/api";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [user, setUser] = useState(null);
  const [allRoles, setAllRoles] = useState([]);
  const [isAdmin, setIsAdmin] = useState(false);
  const [role, setRole] = useState(() => sessionStorage.getItem("gov_acting_role") || "");
  const [ready, setReady] = useState(false);
  const [demoMode, setDemoMode] = useState(false);

  useEffect(() => {
    if (role) sessionStorage.setItem("gov_acting_role", role);
  }, [role]);

  const applyMe = useCallback((me) => {
    setUser(me.user);
    setAllRoles(me.all_roles || []);
    setIsAdmin(!!me.is_admin);
    setRole((prev) => (prev && (me.all_roles || []).includes(prev) ? prev : (me.all_roles || [])[0] || ""));
  }, []);

  // Restore an existing session (token in sessionStorage) on first load.
  useEffect(() => {
    (async () => {
      try {
        const cfg = await api.get("/auth/config").then((r) => r.data);
        setDemoMode(!!cfg.demo_mode);
      } catch {
        setDemoMode(false);
      }
      if (sessionStorage.getItem("gov_token")) {
        try {
          const me = await api.get("/auth/me").then((r) => r.data);
          applyMe(me);
        } catch {
          setAuthToken(null);
        }
      }
      setReady(true);
    })();
  }, [applyMe]);

  const signInAs = useCallback(async (userId) => {
    const res = await api.post("/auth/demo-login", { user_id: userId }).then((r) => r.data);
    setAuthToken(res.token);
    const me = await api.get("/auth/me").then((r) => r.data);
    applyMe(me);
    return me;
  }, [applyMe]);

  const signInWithToken = useCallback(async (token) => {
    setAuthToken(token.trim());
    try {
      const me = await api.get("/auth/me").then((r) => r.data);
      applyMe(me);
      return me;
    } catch (e) {
      setAuthToken(null);
      throw e;
    }
  }, [applyMe]);

  const signOut = useCallback(() => {
    setAuthToken(null);
    sessionStorage.removeItem("gov_acting_role");
    setUser(null);
    setAllRoles([]);
    setIsAdmin(false);
    setRole("");
  }, []);

  return (
    <AuthContext.Provider
      value={{ user, allRoles, isAdmin, role, setRole, signInAs, signInWithToken, signOut, ready, demoMode, isAuthenticated: !!user }}
    >
      {children}
    </AuthContext.Provider>
  );
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used within AuthProvider");
  return ctx;
}
