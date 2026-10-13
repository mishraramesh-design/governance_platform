import { useState } from "react";
import { useQuery, useMutation, useQueryClient } from "@tanstack/react-query";
import { toast } from "sonner";
import api from "../lib/api";
import { useProject } from "../context/ProjectContext";
import { useAuth } from "../context/AuthContext";
import { PageHeader } from "../components/PageHeader";
import { ProvenancePill } from "../components/StatusPill";

const UNVERIFIED = { "EC-01": "Copilot in VS Code", "EC-02": "Droid (with Fabric)" };

export default function EdgeClients() {
  const { projectId } = useProject();
  const { role, isAuthenticated } = useAuth();
  const qc = useQueryClient();
  const [clientId, setClientId] = useState("");
  const [note, setNote] = useState("");

  // Signed-bundle submission form state
  const [bundle, setBundle] = useState({ client_id: "EC-01", prompt_hash: "", tool_calls: "", input_hashes: "", output_text: "" });
  const [verifyResults, setVerifyResults] = useState({});

  const { data: clients } = useQuery({ queryKey: ["edge-clients"], queryFn: () => api.get("/edge-clients").then((r) => r.data) });
  const { data: contributions } = useQuery({
    queryKey: ["edge-contributions", projectId],
    queryFn: () => api.get("/edge-clients/contributions", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });
  const { data: bundles } = useQuery({
    queryKey: ["edge-bundles", projectId],
    queryFn: () => api.get("/edge-clients/bundles", { params: { project_id: projectId } }).then((r) => r.data),
    enabled: !!projectId,
  });

  const simulate = useMutation({
    mutationFn: () => api.post("/edge-clients/simulate", { client_id: clientId, project_id: projectId, note, event_type: "commit_pushed" }),
    onSuccess: (res) => {
      toast.success(res.data.mode === "unverified_contribution" ? "Unverified client contribution recorded" : "Event routed through the platform pipeline");
      qc.invalidateQueries({ queryKey: ["edge-contributions", projectId] });
      qc.invalidateQueries({ queryKey: ["findings"] });
    },
  });

  const submitBundle = useMutation({
    mutationFn: () =>
      api.post("/edge-clients/submit", {
        client_id: bundle.client_id,
        project_id: projectId,
        role,
        prompt_hash: bundle.prompt_hash,
        tool_calls: bundle.tool_calls.split(",").map((s) => s.trim()).filter(Boolean).map((name) => ({ name })),
        input_hashes: bundle.input_hashes.split(",").map((s) => s.trim()).filter(Boolean),
        output_text: bundle.output_text,
      }),
    onSuccess: (res) => {
      const b = res.data.bundle;
      toast.success(`Bundle signed & anchored (ledger #${res.data.ledger_seq})${b.masked_values ? ` · ${b.masked_values} sensitive value(s) masked` : ""}`);
      setBundle((s) => ({ ...s, prompt_hash: "", tool_calls: "", input_hashes: "", output_text: "" }));
      qc.invalidateQueries({ queryKey: ["edge-bundles", projectId] });
    },
    onError: (err) => toast.error(err.response?.data?.detail || "Submission failed — sign in and pick an assigned role."),
  });

  const verify = useMutation({
    mutationFn: (id) => api.get(`/edge-clients/bundles/${id}/verify`).then((r) => r.data),
    onSuccess: (data) => {
      setVerifyResults((m) => ({ ...m, [data.bundle_id]: data }));
      if (data.valid) toast.success("Bundle verified — hash & signature intact");
      else toast.error("TAMPERED — stored hash does not match recomputed hash");
    },
  });

  return (
    <div data-testid="edge-clients-page">
      <PageHeader title="Edge Client Simulator" subtitle="Copilot/Droid/CLI/webhooks all reach the same one central platform - but only platform-routed clients may set a verdict." />

      <div className="grid grid-cols-1 md:grid-cols-2 lg:grid-cols-3 gap-3 mb-8">
        {clients?.map((c) => (
          <div key={c.id} data-testid={`edge-client-card-${c.id}`} className={`border p-4 ${clientId === c.id ? "border-black" : "border-gray-200"}`}>
            <div className="flex items-center justify-between mb-1">
              <span className="font-mono text-xs font-bold">{c.id}</span>
              <span className={`text-[10px] font-bold uppercase px-1.5 py-0.5 ${c.may_set_verdict ? "bg-black text-[#FFE600]" : "bg-gray-100 text-gray-600"}`}>
                {c.may_set_verdict ? "May set verdict" : "Never sets verdict"}
              </span>
            </div>
            <div className="font-[Chivo] font-bold text-sm mb-1">{c.name}</div>
            <div className="text-xs text-gray-500 mb-2">{c.who_uses_it} · {c.trust_class}</div>
            <button data-testid={`select-edge-client-btn-${c.id}`} onClick={() => setClientId(c.id)} className="text-[10px] font-bold uppercase border border-gray-400 px-2 py-1 hover:border-black">
              Select
            </button>
          </div>
        ))}
      </div>

      <div className="border border-gray-200 p-5 mb-8 flex flex-wrap items-end gap-3">
        <div className="flex-1 min-w-[200px]">
          <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Note / payload</label>
          <input data-testid="edge-client-note-input" value={note} onChange={(e) => setNote(e.target.value)} placeholder="e.g. Copilot suggests a fix for CTRL-06" className="w-full border border-gray-300 px-3 py-2 text-sm" />
        </div>
        <button data-testid="simulate-edge-client-btn" onClick={() => simulate.mutate()} disabled={!clientId || simulate.isPending} className="bg-[#FFE600] text-black hover:bg-[#F0D800] font-bold tracking-tight rounded-none px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-50">
          {simulate.isPending ? "Submitting…" : "Simulate Contribution"}
        </button>
      </div>

      {/* Signed, tamper-evident edge-client bundles (EC-01 Copilot / EC-02 Droid) */}
      <div className="border-2 border-black p-5 mb-8" data-testid="edge-bundle-panel">
        <div className="flex items-center justify-between mb-1">
          <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500">Submit Signed Client Bundle</div>
          <ProvenancePill provenance="client_model_unverified" />
        </div>
        <p className="text-xs text-gray-500 mb-4">
          Prompt text is never stored (hash only). Output is masked for secrets/PII before storage, SHA-256 hashed, HMAC-signed and anchored in the ledger. These bundles can never set a verdict.
        </p>
        <div className="grid grid-cols-1 md:grid-cols-2 gap-3">
          <div>
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Client</label>
            <select data-testid="bundle-client-select" value={bundle.client_id} onChange={(e) => setBundle((s) => ({ ...s, client_id: e.target.value }))} className="w-full border border-gray-300 px-3 py-2 text-sm">
              {Object.entries(UNVERIFIED).map(([id, name]) => <option key={id} value={id}>{id} · {name}</option>)}
            </select>
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Prompt hash</label>
            <input data-testid="bundle-prompt-hash-input" value={bundle.prompt_hash} onChange={(e) => setBundle((s) => ({ ...s, prompt_hash: e.target.value }))} placeholder="sha256:abc123…" className="w-full border border-gray-300 px-3 py-2 text-sm font-mono" />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Tool calls (comma-separated)</label>
            <input data-testid="bundle-tool-calls-input" value={bundle.tool_calls} onChange={(e) => setBundle((s) => ({ ...s, tool_calls: e.target.value }))} placeholder="read_file, grep, edit" className="w-full border border-gray-300 px-3 py-2 text-sm" />
          </div>
          <div>
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Input hashes (comma-separated)</label>
            <input data-testid="bundle-input-hashes-input" value={bundle.input_hashes} onChange={(e) => setBundle((s) => ({ ...s, input_hashes: e.target.value }))} placeholder="h1, h2" className="w-full border border-gray-300 px-3 py-2 text-sm font-mono" />
          </div>
          <div className="md:col-span-2">
            <label className="block text-[10px] uppercase tracking-wider font-bold text-gray-500 mb-1">Output text (masked on store)</label>
            <textarea data-testid="bundle-output-text-input" value={bundle.output_text} onChange={(e) => setBundle((s) => ({ ...s, output_text: e.target.value }))} rows={3} placeholder="Model output. Any Aadhaar/PAN/secret is masked before storage." className="w-full border border-gray-300 px-3 py-2 text-sm font-mono" />
          </div>
        </div>
        <div className="flex items-center gap-3 mt-3">
          <button data-testid="submit-bundle-btn" onClick={() => submitBundle.mutate()} disabled={!isAuthenticated || !bundle.prompt_hash || submitBundle.isPending} className="bg-black text-[#FFE600] hover:bg-gray-800 font-bold tracking-tight rounded-none px-4 py-2 text-xs border border-black transition-colors duration-100 disabled:opacity-40">
            {submitBundle.isPending ? "Signing…" : "Sign & Anchor Bundle"}
          </button>
          {!isAuthenticated && <span className="text-xs text-gray-400">Sign in (top-right) with an assigned role to submit.</span>}
          {isAuthenticated && <span className="text-xs text-gray-400">Acting role: <span className="font-semibold text-black">{role}</span></span>}
        </div>
      </div>

      <div className="mb-8">
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Signed Bundles</div>
        <div className="space-y-2">
          {bundles?.map((b) => {
            const vr = verifyResults[b.id];
            return (
              <div key={b.id} data-testid={`edge-bundle-row-${b.id}`} className="border border-gray-200 p-3">
                <div className="flex items-start justify-between gap-3">
                  <div className="min-w-0">
                    <div className="flex items-center gap-2 mb-1 flex-wrap">
                      <span className="font-mono text-xs font-bold">{b.client_id}</span>
                      <span className="text-sm font-semibold">{b.client_name}</span>
                      <ProvenancePill provenance={b.provenance} />
                      {b.masked_values > 0 && <span className="text-[10px] font-bold uppercase bg-gray-100 text-gray-600 px-1.5 py-0.5">{b.masked_values} masked</span>}
                    </div>
                    <div className="text-xs text-gray-500">by {b.submitted_by_user_name} · {b.role}</div>
                    <div className="font-mono text-[11px] text-gray-400 truncate mt-1" data-testid={`bundle-hash-${b.id}`}>hash: {b.bundle_hash}</div>
                    {b.output_text && <div className="font-mono text-[11px] text-gray-500 truncate mt-0.5">out: {b.output_text}</div>}
                  </div>
                  <div className="flex flex-col items-end gap-2 shrink-0">
                    <button data-testid={`verify-bundle-btn-${b.id}`} onClick={() => verify.mutate(b.id)} disabled={verify.isPending} className="text-[10px] font-bold uppercase border border-black px-3 py-1.5 hover:bg-black hover:text-[#FFE600] transition-colors duration-100">
                      Verify
                    </button>
                    {vr && (
                      <span data-testid={`verify-result-${b.id}`} className={`text-[10px] font-bold uppercase px-2 py-0.5 ${vr.valid ? "bg-black text-[#FFE600]" : "bg-red-600 text-white"}`}>
                        {vr.valid ? "Verified" : "Tampered"}
                      </span>
                    )}
                  </div>
                </div>
              </div>
            );
          })}
          {bundles && !bundles.length && <div className="text-sm text-gray-400 italic">No signed bundles yet.</div>}
        </div>
      </div>

      <div>
        <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500 mb-2">Unverified Client Contributions</div>
        <div className="space-y-2">
          {contributions?.contributions?.map((c) => (
            <div key={c.id} data-testid={`edge-contribution-row-${c.id}`} className="border border-dashed border-gray-400 p-3 flex items-center justify-between">
              <div>
                <span className="font-mono text-xs font-bold mr-2">{c.client_id}</span>
                <span className="text-sm">{c.note || "(no note)"}</span>
              </div>
              <ProvenancePill provenance={c.provenance} />
            </div>
          ))}
          {contributions && !contributions.contributions?.length && <div className="text-sm text-gray-400 italic">No unverified contributions yet.</div>}
        </div>
      </div>
    </div>
  );
}
