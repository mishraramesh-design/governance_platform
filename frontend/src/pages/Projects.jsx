import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { PageHeader } from "../components/PageHeader";

export default function Projects() {
  const { setProjectId } = useProject();
  const navigate = useNavigate();
  const { data: projects, isLoading } = useQuery({
    queryKey: ["projects"],
    queryFn: () => api.get("/projects").then((r) => r.data),
  });

  return (
    <div data-testid="projects-page">
      <PageHeader title="Projects" subtitle="Registered engagements under IV&V governance, tiered T0 (lowest risk) to T4 (highest integrity)." />
      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}
      <div className="grid grid-cols-1 md:grid-cols-3 gap-4">
        {projects?.map((p) => (
          <div key={p.id} data-testid={`project-card-${p.id}`} className="border border-gray-200 p-5 hover:border-black transition-colors duration-100">
            <div className="flex items-center justify-between mb-2">
              <span className="text-[10px] font-bold uppercase tracking-wider bg-black text-[#FFE600] px-2 py-0.5">L{p.integrity_level}</span>
              <span className="text-[10px] text-gray-400 uppercase tracking-wide">{p.stage}</span>
            </div>
            <h3 className="font-[Chivo] text-lg font-bold tracking-tight mb-1">{p.name}</h3>
            <p className="text-sm text-gray-500 mb-4">{p.description}</p>
            <button
              data-testid={`project-select-btn-${p.id}`}
              onClick={() => {
                setProjectId(p.id);
                navigate("/");
              }}
              className="text-xs font-bold uppercase tracking-wide border border-black px-3 py-1.5 hover:bg-black hover:text-[#FFE600] transition-colors duration-100"
            >
              Set as Active Project
            </button>
          </div>
        ))}
      </div>
    </div>
  );
}
