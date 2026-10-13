import { useState, useEffect } from "react";
import { Link, useLocation } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import { useProject } from "../context/ProjectContext";
import api from "../lib/api";
import { AdvisoryBadge } from "./StatusPill";
import Login from "../pages/Login";

const NAV = [
  { group: "Overview", items: [{ to: "/", label: "Dashboard", testId: "nav-dashboard" }] },
  {
    group: "Governance",
    items: [
      { to: "/projects", label: "Projects", testId: "nav-projects" },
      { to: "/agents", label: "Agents & SDLC Stages", testId: "nav-agents" },
      { to: "/harness", label: "Agent Harness", testId: "nav-harness" },
      { to: "/agent-flow", label: "Agent Flow", testId: "nav-agent-flow" },
      { to: "/model-settings", label: "Model Gateway Settings", testId: "nav-model-settings" },
      { to: "/mlops", label: "MLOps · Learning Harness", testId: "nav-mlops" },
      { to: "/controls", label: "Control Catalog", testId: "nav-controls" },
      { to: "/gates", label: "Gate Readiness", testId: "nav-gates" },
      { to: "/ai-governance", label: "AI Governance (ISO 42001)", testId: "nav-ai-governance" },
    ],
  },
  {
    group: "Assurance Pipeline",
    items: [
      { to: "/requirements", label: "Requirements Quality", testId: "nav-requirements" },
      { to: "/events", label: "Event Simulator", testId: "nav-events" },
      { to: "/findings", label: "Findings Explorer", testId: "nav-findings" },
      { to: "/traceability", label: "Traceability Matrix", testId: "nav-traceability" },
      { to: "/adjudication", label: "L2 Adjudication", testId: "nav-adjudication" },
    ],
  },
  {
    group: "Evidence & Audit",
    items: [
      { to: "/ledger", label: "Ledger / Audit Trail", testId: "nav-ledger" },
      { to: "/artifacts", label: "CMMI Artifacts", testId: "nav-artifacts" },
      { to: "/reports", label: "Reports", testId: "nav-reports" },
    ],
  },
  {
    group: "Edge & Simulation",
    items: [
      { to: "/edge-clients", label: "Edge Client Simulator", testId: "nav-edge-clients" },
      { to: "/repo-audit", label: "Repo Audit", testId: "nav-repo-audit" },
      { to: "/runtime", label: "Runtime Assurance", testId: "nav-runtime" },
    ],
  },
  { group: "", items: [{ to: "/about", label: "About & Assumptions", testId: "nav-about" }] },
];

function Logo() {
  return (
    <div className="flex items-center gap-2.5" data-testid="brand-logo">
      <div className="relative w-7 h-7 bg-black shrink-0">
        <span className="absolute -top-1 -right-1 w-2.5 h-2.5 rounded-full bg-[#FFE600]" />
      </div>
      <div className="leading-tight">
        <div className="font-[Chivo] font-black text-sm tracking-tight text-black">IV&amp;V GOVERNANCE</div>
        <div className="text-[9px] uppercase tracking-[0.25em] text-gray-400">Observe · Evidence · Advise</div>
      </div>
    </div>
  );
}

export function AppShell({ children }) {
  const { user, allRoles, isAdmin, role, setRole, signInAs, signOut, isAuthenticated, demoMode, ready } = useAuth();
  const { projects, projectId, setProjectId, currentProject } = useProject();
  const location = useLocation();
  const [users, setUsers] = useState([]);

  useEffect(() => {
    if (!ready || !(demoMode || isAuthenticated)) return;
    api.get("/auth/users").then((r) => setUsers(r.data)).catch(() => setUsers([]));
  }, [ready, demoMode, isAuthenticated]);

  const onSignInChange = (e) => {
    const uid = e.target.value;
    if (uid) signInAs(uid);
    else signOut();
  };

  if (!ready) return <div className="min-h-screen flex items-center justify-center text-sm text-gray-400">Loading…</div>;
  if (!demoMode && !isAuthenticated) return <Login />;

  return (
    <div className="min-h-screen bg-white flex">
      <aside className="hidden lg:flex flex-col w-64 border-r border-gray-200 shrink-0 h-screen sticky top-0 overflow-y-auto">
        <div className="h-16 flex items-center px-5 border-b border-gray-200">
          <Logo />
        </div>
        <nav className="flex-1 py-4">
          {NAV.map((group, gi) => (
            <div key={gi} className="mb-4">
              {group.group && (
                <div className="px-5 mb-1 text-[10px] uppercase tracking-[0.2em] font-bold text-gray-400">{group.group}</div>
              )}
              {group.items.map((item) => {
                const active = location.pathname === item.to;
                return (
                  <Link
                    key={item.to}
                    to={item.to}
                    data-testid={item.testId}
                    className={`block px-5 py-2 text-sm font-medium transition-colors duration-100 ease-in border-l-4 ${
                      active
                        ? "border-[#FFE600] bg-gray-50 text-black font-bold"
                        : "border-transparent text-gray-600 hover:bg-gray-50 hover:text-black"
                    }`}
                  >
                    {item.label}
                  </Link>
                );
              })}
            </div>
          ))}
          {isAdmin && (
            <div className="mb-4">
              <div className="px-5 mb-1 text-[10px] uppercase tracking-[0.2em] font-bold text-gray-400">Administration</div>
              <Link
                to="/admin"
                data-testid="nav-admin"
                className={`block px-5 py-2 text-sm font-medium transition-colors duration-100 ease-in border-l-4 ${
                  location.pathname === "/admin"
                    ? "border-[#FFE600] bg-gray-50 text-black font-bold"
                    : "border-transparent text-gray-600 hover:bg-gray-50 hover:text-black"
                }`}
              >
                Admin · Users & Tokens
              </Link>
            </div>
          )}
        </nav>
      </aside>

      <div className="flex-1 min-w-0">
        <header
          data-testid="app-header"
          className="sticky top-0 z-50 bg-white border-b border-gray-300 h-16 flex items-center justify-between px-4 sm:px-8 gap-4"
        >
          <div className="flex items-center gap-4 min-w-0">
            <AdvisoryBadge />
            {demoMode && (
              <span data-testid="demo-banner" className="text-[10px] font-bold uppercase tracking-wider bg-red-600 text-white px-2 py-1">Demo mode</span>
            )}
            {currentProject && (
              <span className="hidden md:inline text-xs text-gray-400 truncate">
                Project: <span className="text-black font-semibold">{currentProject.name}</span> · Tier {currentProject.integrity_tier}
              </span>
            )}
          </div>
          <div className="flex items-center gap-3 shrink-0">
            <select
              data-testid="project-switcher"
              value={projectId}
              onChange={(e) => setProjectId(e.target.value)}
              className="text-xs font-semibold border border-gray-300 rounded-none px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
            >
              {projects.map((p) => (
                <option key={p.id} value={p.id}>
                  {p.name}
                </option>
              ))}
            </select>
            <div className="flex items-center gap-2 border-l border-gray-200 pl-3">
              <span className="text-[10px] uppercase tracking-wider text-gray-400 hidden sm:inline">Signed in</span>
              {!demoMode ? (
                <>
                  <span data-testid="signed-in-name" className="text-xs font-semibold">{user?.name}</span>
                  <button data-testid="sign-out-btn" onClick={signOut} className="text-xs underline text-gray-500 hover:text-black">Sign out</button>
                </>
              ) : (
              <select
                data-testid="user-switcher"
                value={user?.id || ""}
                onChange={onSignInChange}
                className="text-xs font-semibold border border-gray-300 rounded-none px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
              >
                <option value="">Signed out</option>
                {users.map((u) => (
                  <option key={u.id} value={u.id}>
                    {u.name}
                  </option>
                ))}
              </select>
              )}
            </div>
            {isAuthenticated && (
              <div className="flex items-center gap-2 border-l border-gray-200 pl-3">
                <span className="text-[10px] uppercase tracking-wider text-gray-400 hidden sm:inline">Acting role</span>
                <select
                  data-testid="role-switcher"
                  value={role}
                  onChange={(e) => setRole(e.target.value)}
                  disabled={!allRoles.length}
                  className="text-xs font-bold border border-black rounded-none px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600] disabled:opacity-40"
                >
                  {allRoles.map((r) => (
                    <option key={r} value={r}>
                      {r}
                    </option>
                  ))}
                </select>
              </div>
            )}
          </div>
        </header>
        <main className="px-4 sm:px-8 py-6">{children}</main>
      </div>
    </div>
  );
}
