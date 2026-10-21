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
      try { setDemoMode((await api.get('/auth/status')).data.demo_mode === true); } catch { setDemoMode(false); }
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

  const signOut = useCallback(() => {
    setAuthToken(null);
    sessionStorage.removeItem("gov_acting_role");
    setUser(null);
    setAllRoles([]);
    setIsAdmin(false);
    setRole("");
    sessionStorage.removeItem('testing_workspace_session');
  }, []);

  useEffect(() => {
    window.addEventListener('gov-auth-expired', signOut);
    return () => window.removeEventListener('gov-auth-expired', signOut);
  }, [signOut]);

  const signInWithToken = useCallback(async (token) => {
    setAuthToken(token.trim());
    try {
      const me = (await api.get('/auth/me')).data;
      applyMe(me);
    } catch (error) { setAuthToken(null); throw error; }
  }, [applyMe]);

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
