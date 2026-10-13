import { createContext, useContext, useState, useEffect } from "react";
import api from "../lib/api";
import { useAuth } from "./AuthContext";

const ProjectContext = createContext(null);

export function ProjectProvider({ children }) {
  const [projects, setProjects] = useState([]);
  const [projectId, setProjectId] = useState(() => localStorage.getItem("gov_project_id") || "");

  const refreshProjects = () => api.get("/projects").then((res) => { setProjects(res.data); return res.data; });

  const { ready, demoMode, isAuthenticated } = useAuth();

  useEffect(() => {
    if (!ready || !(demoMode || isAuthenticated)) { setProjects([]); return; }
    api.get("/projects").then((res) => {
      setProjects(res.data);
      // The remembered project may not exist on this server (new database, redeploy): fall back to the first one.
      if (res.data.length && !res.data.some((p) => p.id === projectId)) {
        setProjectId(res.data[0].id);
      } else if (!res.data.length) {
        setProjectId("");
        try { localStorage.removeItem("gov_project_id"); } catch (e) { /* ignore */ }
      }
    }).catch(() => setProjects([]));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [ready, demoMode, isAuthenticated]);

  useEffect(() => {
    if (projectId) localStorage.setItem("gov_project_id", projectId);
  }, [projectId]);

  const currentProject = projects.find((p) => p.id === projectId);

  return (
    <ProjectContext.Provider value={{ projects, projectId, setProjectId, currentProject, refreshProjects }}>
      {children}
    </ProjectContext.Provider>
  );
}

export function useProject() {
  const ctx = useContext(ProjectContext);
  if (!ctx) throw new Error("useProject must be used within ProjectProvider");
  return ctx;
}
