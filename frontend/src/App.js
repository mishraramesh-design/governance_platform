import "@/App.css";
import { BrowserRouter, Routes, Route } from "react-router-dom";
import { Toaster } from "@/components/ui/sonner";
import { AuthProvider } from "@/context/AuthContext";
import { ProjectProvider } from "@/context/ProjectContext";
import { AppShell } from "@/components/AppShell";

import Dashboard from "@/pages/Dashboard";
import Projects from "@/pages/Projects";
import Agents from "@/pages/Agents";
import AgentHarness from "@/pages/AgentHarness";
import AgentFlow from "@/pages/AgentFlow";
import ModelSettings from "@/pages/ModelSettings";
import Mlops from "@/pages/Mlops";
import Controls from "@/pages/Controls";
import Gates from "@/pages/Gates";
import AIGovernance from "@/pages/AIGovernance";
import Requirements from "@/pages/Requirements";
import Events from "@/pages/Events";
import Findings from "@/pages/Findings";
import Traceability from "@/pages/Traceability";
import Adjudication from "@/pages/Adjudication";
import Ledger from "@/pages/Ledger";
import Artifacts from "@/pages/Artifacts";
import Reports from "@/pages/Reports";
import EdgeClients from "@/pages/EdgeClients";
import RepoAudit from "@/pages/RepoAudit";
import Runtime from "@/pages/Runtime";
import About from "@/pages/About";
import Admin from "@/pages/Admin";
import Studio from "@/pages/Studio";

function App() {
  return (
    <AuthProvider>
      <ProjectProvider>
        <BrowserRouter>
          <AppShell>
            <Routes>
              <Route path="/" element={<Dashboard />} />
              <Route path="/studio" element={<Studio />} />
              <Route path="/projects" element={<Projects />} />
              <Route path="/agents" element={<Agents />} />
              <Route path="/harness" element={<AgentHarness />} />
              <Route path="/agent-flow" element={<AgentFlow />} />
              <Route path="/model-settings" element={<ModelSettings />} />
              <Route path="/mlops" element={<Mlops />} />
              <Route path="/controls" element={<Controls />} />
              <Route path="/gates" element={<Gates />} />
              <Route path="/ai-governance" element={<AIGovernance />} />
              <Route path="/requirements" element={<Requirements />} />
              <Route path="/events" element={<Events />} />
              <Route path="/findings" element={<Findings />} />
              <Route path="/traceability" element={<Traceability />} />
              <Route path="/adjudication" element={<Adjudication />} />
              <Route path="/ledger" element={<Ledger />} />
              <Route path="/artifacts" element={<Artifacts />} />
              <Route path="/reports" element={<Reports />} />
              <Route path="/edge-clients" element={<EdgeClients />} />
              <Route path="/repo-audit" element={<RepoAudit />} />
              <Route path="/runtime" element={<Runtime />} />
              <Route path="/about" element={<About />} />
              <Route path="/admin" element={<Admin />} />
            </Routes>
          </AppShell>
        </BrowserRouter>
        <Toaster />
      </ProjectProvider>
    </AuthProvider>
  );
}

export default App;
