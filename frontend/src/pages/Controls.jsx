import { useQuery } from "@tanstack/react-query";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";

export default function Controls() {
  const { data: controls, isLoading } = useQuery({ queryKey: ["controls"], queryFn: () => api.get("/controls").then((r) => r.data) });

  return (
    <div data-testid="controls-page">
      <PageHeader title="Control Catalog" subtitle="20 controls spanning the SDLC. Each control is observe-advise only and tagged to the standard(s) it supports." />
      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}
      <div className="overflow-x-auto border border-gray-200">
        <table className="w-full text-sm">
          <thead>
            <tr className="bg-gray-50 border-y border-gray-300">
              {["ID", "Name", "Stage", "Trigger", "Executor", "Independence", "Integrity Level", "Standards"].map((h) => (
                <th key={h} className="text-left text-xs uppercase tracking-wider text-gray-600 font-bold py-2 px-3">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {controls?.map((c) => (
              <tr key={c.id} data-testid={`control-row-${c.id}`} className="hover:bg-gray-50 transition-colors duration-100">
                <td className="border-b border-gray-200 py-2 px-3 font-mono text-xs font-bold">{c.id}</td>
                <td className="border-b border-gray-200 py-2 px-3 font-semibold">{c.name}</td>
                <td className="border-b border-gray-200 py-2 px-3 text-gray-600">{c.stage}</td>
                <td className="border-b border-gray-200 py-2 px-3 text-gray-600 font-mono text-xs">{c.trigger}</td>
                <td className="border-b border-gray-200 py-2 px-3 font-mono text-xs">{c.executor}</td>
                <td className="border-b border-gray-200 py-2 px-3 text-gray-600 text-xs">{c.independence_method.replaceAll("_", " ")}</td>
                <td className="border-b border-gray-200 py-2 px-3 text-xs">{c.integrity_level}</td>
                <td className="border-b border-gray-200 py-2 px-3">
                  <div className="flex gap-1 flex-wrap">
                    {c.standards_tags.map((t) => (
                      <span key={t} className="text-[10px] bg-gray-100 px-1.5 py-0.5 text-gray-600">{t}</span>
                    ))}
                  </div>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </div>
  );
}
