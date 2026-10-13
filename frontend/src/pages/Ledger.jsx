import { useState } from "react";
import { useQuery } from "@tanstack/react-query";
import { useNavigate } from "react-router-dom";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";

const MLOPS_TYPES = ["mlops_registry_initialised", "mlops_shadow_compare", "registry_promotion", "registry_shadow", "eval_run"];

export default function Ledger() {
  const navigate = useNavigate();
  const PS = 100;
  const [chain, setChain] = useState("_global");
  const [page, setPage] = useState(null); // null = newest page
  const cp = chain === "_global" ? {} : { project_id: chain };
  const { data: chains } = useQuery({ queryKey: ["ledger-chains"], queryFn: () => api.get("/ledger/chains").then((r) => r.data) });
  const { data: total } = useQuery({ queryKey: ["ledger-total", chain], queryFn: () => api.get("/ledger", { params: { ...cp, page: 1, page_size: 1 } }).then((r) => Number(r.headers["x-total-count"] || 0)) });
  const pages = Math.max(1, Math.ceil((total || 0) / PS));
  const cur = page || pages;
  const { data: entries, isLoading } = useQuery({
    queryKey: ["ledger", chain, cur, total], enabled: total !== undefined,
    queryFn: () => api.get("/ledger", { params: { ...cp, page: cur, page_size: PS } }).then((r) => r.data),
  });
  const { data: verify, refetch, isFetching } = useQuery({ queryKey: ["ledger-verify", chain], queryFn: () => api.get("/ledger/verify", { params: cp }).then((r) => r.data), enabled: false });

  return (
    <div data-testid="ledger-page">
      <PageHeader
        title="Ledger / Audit Trail"
        subtitle="Append-only, SHA-256 hash-chained record of every event, finding, triage decision, adjudication, report and artifact."
        actions={
          <button data-testid="verify-ledger-btn" onClick={() => refetch()} disabled={isFetching} className="bg-[#FFE600] text-black hover:bg-[#F0D800] font-bold tracking-tight rounded-none px-4 py-2 text-xs border border-black transition-colors duration-100">
            {isFetching ? "Verifying…" : "Verify Ledger Integrity"}
          </button>
        }
      />

      <div className="mb-4 flex items-center gap-2 text-xs">
        <label className="uppercase tracking-wider font-bold text-gray-500">Chain</label>
        <select data-testid="ledger-chain" value={chain} onChange={(e) => { setChain(e.target.value); setPage(null); }} className="border border-gray-300 px-2 py-1.5">
          {(chains || [{ chain: "_global", entries: 0 }]).map((c) => <option key={c.chain} value={c.chain}>{c.chain === "_global" ? "Platform (global)" : `Project ${c.chain.slice(0, 8)}…`} · {c.entries}</option>)}
        </select>
      </div>
      {verify && (
        <div data-testid="ledger-verify-result" className={`mb-6 border p-4 ${verify.valid ? "border-green-600 bg-green-50" : "border-red-600 bg-red-50"}`}>
          <div className={`font-black text-lg ${verify.valid ? "text-green-700" : "text-red-700"}`}>{verify.valid ? "✓ Chain Valid" : "✗ Chain Broken"}</div>
          <div className="text-xs text-gray-600">{verify.total_entries} entries verified{!verify.valid && ` - break at seq ${verify.broken_at_seq}`}</div>
        </div>
      )}

      {isLoading && <div className="text-sm text-gray-400">Loading…</div>}

      <div className="overflow-x-auto border border-gray-200">
        <table className="w-full text-xs font-mono">
          <thead>
            <tr className="bg-gray-50 border-y border-gray-300">
              {["Seq", "Type", "Ref", "Prev Hash", "Hash", "Timestamp"].map((h) => (
                <th key={h} className="text-left text-xs uppercase tracking-wider text-gray-600 font-bold py-2 px-3 not-italic">{h}</th>
              ))}
            </tr>
          </thead>
          <tbody>
            {[...(entries || [])].reverse().map((e) => {
              const isMlops = MLOPS_TYPES.includes(e.payload_type);
              return (
              <tr key={e.id} data-testid={`ledger-row-${e.seq}`}
                  onClick={isMlops ? () => navigate("/mlops") : undefined}
                  className={`transition-colors duration-100 ${isMlops ? "cursor-pointer hover:bg-[#FFFBe6]" : "hover:bg-gray-50"}`}>
                <td className="border-b border-gray-200 py-1.5 px-3">{e.seq}</td>
                <td className="border-b border-gray-200 py-1.5 px-3">
                  {isMlops ? (
                    <span data-testid={`ledger-mlops-link-${e.seq}`} className="text-black underline decoration-[#FFE600] decoration-2 font-bold">
                      {e.payload_type} ↗
                    </span>
                  ) : e.payload_type}
                </td>
                <td className="border-b border-gray-200 py-1.5 px-3 truncate max-w-[120px]">{e.payload_ref}</td>
                <td className="border-b border-gray-200 py-1.5 px-3 truncate max-w-[140px] text-gray-400">{e.prev_hash.slice(0, 16)}…</td>
                <td className="border-b border-gray-200 py-1.5 px-3 truncate max-w-[140px]">{e.hash.slice(0, 16)}…</td>
                <td className="border-b border-gray-200 py-1.5 px-3 text-gray-500">{e.timestamp.slice(0, 19)}</td>
              </tr>
              );
            })}
          </tbody>
        </table>
        <div className="flex items-center gap-3 mt-3 text-xs" data-testid="ledger-pager">
          <button disabled={cur <= 1} onClick={() => setPage(cur - 1)} className="border border-black px-2 py-1 disabled:opacity-30">← Older</button>
          <span>Page {cur} of {pages} · {total ?? 0} entries</span>
          <button disabled={cur >= pages} onClick={() => setPage(cur + 1 >= pages ? null : cur + 1)} className="border border-black px-2 py-1 disabled:opacity-30">Newer →</button>
        </div>
      </div>
    </div>
  );
}
