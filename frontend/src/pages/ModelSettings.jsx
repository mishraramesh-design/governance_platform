import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { Switch } from "../components/ui/switch";
import { toast } from "sonner";
import { useProject } from "../context/ProjectContext";

const ROLE_META = {
  maker: { label: "Maker", note: "Generative authoring — proposes findings, requirement rewrites, scenarios and report narrative." },
  checker: { label: "Checker", note: "Independent review — re-performs and challenges peer work. Use a different model family." },
  security: { label: "Security", note: "Security, privacy, data-protection, supplier and AI-risk assessment (may be kept on-prem)." },
  verifier: { label: "Verifier", note: "Recomputes numbers, reconciles totals and verifies evidence integrity and citations." },
};

function RoleEditor({ name, profile, config, roleCount, onChange }) {
  const meta = ROLE_META[name] || { label: name, note: "" };
  const providers = config.providers;
  const provider = profile?.provider || providers[0];
  const isCustom = provider === "custom";
  const models = config.available_models[provider] || [];

  return (
    <div className="border border-gray-200 p-4" data-testid={`role-editor-${name}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="flex items-center gap-2">
          <span className="font-[Chivo] font-bold text-sm">{meta.label}</span>
          <span className="text-[10px] font-bold uppercase bg-black text-[#FFE600] px-1.5 py-0.5">{roleCount ?? 0} agents</span>
        </div>
        <span className="font-mono text-[10px] uppercase tracking-wider text-gray-400">{name}</span>
      </div>
      <p className="text-xs text-gray-500 mb-3">{meta.note}</p>

      <div className="grid grid-cols-2 gap-2 mb-2">
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-gray-400">Provider</span>
          <select
            data-testid={`role-provider-${name}`}
            value={provider}
            onChange={(e) => {
              const p = e.target.value;
              const m = p === "custom" ? "" : (config.available_models[p] || [])[0];
              onChange(name, { ...profile, provider: p, model: m });
            }}
            className="w-full mt-0.5 text-sm border border-gray-300 px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
          >
            {providers.map((p) => <option key={p} value={p}>{p === "custom" ? "custom / on-prem" : p}</option>)}
          </select>
        </label>
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-gray-400">Model</span>
          {isCustom ? (
            <input
              data-testid={`role-model-${name}`}
              value={profile?.model || ""}
              onChange={(e) => onChange(name, { ...profile, model: e.target.value })}
              placeholder="e.g. llama-3.1-70b-instruct"
              className="w-full mt-0.5 text-sm border border-gray-300 px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
            />
          ) : (
            <select
              data-testid={`role-model-${name}`}
              value={profile?.model || models[0]}
              onChange={(e) => onChange(name, { ...profile, model: e.target.value })}
              className="w-full mt-0.5 text-sm border border-gray-300 px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
            >
              {models.map((m) => <option key={m} value={m}>{m}</option>)}
            </select>
          )}
        </label>
      </div>

      {isCustom && (
        <label className="block mb-2">
          <span className="text-[10px] uppercase tracking-wider text-gray-400">Base URL (OpenAI-compatible)</span>
          <input
            data-testid={`role-baseurl-${name}`}
            value={profile?.base_url || ""}
            onChange={(e) => onChange(name, { ...profile, base_url: e.target.value })}
            placeholder="http://10.0.0.5:8000/v1"
            className="w-full mt-0.5 text-sm border border-gray-300 px-2 py-1.5 bg-white font-mono focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
          />
        </label>
      )}

      <label className="block mb-2">
        <span className="text-[10px] uppercase tracking-wider text-gray-400">
          API key {profile?.api_key_set ? "· stored" : config.provider_env_keys_available?.[profile?.provider] && !isCustom ? "· optional (uses server environment key)" : ""}
        </span>
        <div className="flex gap-1.5 mt-0.5">
          <input
            data-testid={`role-key-${name}`}
            type="password"
            value={profile?.api_key === "__stored__" || profile?.api_key === "__clear__" ? "" : (profile?.api_key || "")}
            onChange={(e) => onChange(name, { ...profile, api_key: e.target.value })}
            placeholder={profile?.api_key === "__clear__" ? "will use server environment key if configured" : profile?.api_key_set ? "•••••••• (leave blank to keep)" : "paste key…"}
            className="flex-1 text-sm border border-gray-300 px-2 py-1.5 bg-white font-mono focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
          />
          {(profile?.api_key_set || (profile?.api_key && profile.api_key !== "__clear__")) && (
            <button
              type="button"
              data-testid={`role-clearkey-${name}`}
              onClick={() => onChange(name, { ...profile, api_key: "__clear__", api_key_set: false })}
              className="text-[10px] uppercase font-bold border border-gray-400 px-2 hover:border-black hover:text-black text-gray-600"
            >
              Clear / use server environment key
            </button>
          )}
        </div>
      </label>

      <label className="flex items-center gap-2 text-xs text-gray-600" data-testid={`role-localonly-${name}`}>
        <input
          type="checkbox"
          checked={!!profile?.local_only}
          onChange={(e) => onChange(name, { ...profile, local_only: e.target.checked })}
          className="accent-black"
        />
        Local-only (block any external cloud call for this role)
      </label>
      {profile?.local_only && provider !== "custom" && (
        <div className="mt-1 text-[11px] text-red-700">⚠ Local-only is on but provider is a cloud family — calls will be blocked and fall back to deterministic.</div>
      )}
    </div>
  );
}

export default function ModelSettings() {
  const qc = useQueryClient();
  const { projectId, currentProject } = useProject();
  const { data: config, isLoading } = useQuery({ queryKey: ["harness-config", projectId], queryFn: () => api.get("/harness/config", { params: { project_id: projectId || undefined } }).then((r) => r.data) });
  const { data: agentsData } = useQuery({ queryKey: ["harness-agents"], queryFn: () => api.get("/harness/agents").then((r) => r.data) });
  const { data: callsData } = useQuery({ queryKey: ["llm-calls", projectId], queryFn: () => api.get("/harness/llm-calls", { params: { limit: 25, project_id: projectId || undefined } }).then((r) => r.data), refetchInterval: 5000 });

  const [profiles, setProfiles] = useState(null);
  const [zeroLlm, setZeroLlm] = useState(false);
  const [maxCallsPerRun, setMaxCallsPerRun] = useState(2);
  const [sovereignty, setSovereignty] = useState(null);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config) {
      setProfiles(config.capability_profiles);
      setZeroLlm(config.zero_llm_mode);
      setSovereignty(config.sovereignty);
      setMaxCallsPerRun(config.max_llm_calls_per_run ?? 2);
    }
  }, [config]);

  const onChange = (name, prof) => setProfiles((p) => ({ ...p, [name]: prof }));

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/harness/config", { capability_profiles: profiles, zero_llm_mode: zeroLlm, sovereignty, max_llm_calls_per_run: maxCallsPerRun, project_id: projectId || null });
      qc.invalidateQueries({ queryKey: ["harness-config", projectId] });
      qc.invalidateQueries({ queryKey: ["agent-flow"] });
      toast.success("Gateway configuration saved");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally { setSaving(false); }
  };

  if (isLoading || !profiles) return <div className="text-sm text-gray-400">Loading…</div>;
  const byRole = agentsData?.summary?.by_role || {};

  return (
    <div data-testid="model-settings-page">
      <PageHeader
        title="Model Gateway Settings"
        subtitle={`${currentProject ? `${currentProject.name} · ` : "Default profile · "}Four model capability roles route advisory tasks across configured providers. Deterministic controls establish findings first; language models help interpret and explain. Run-level call limits cap model use, and model output alone never establishes a control verdict.`}
      />

      <div className="mb-4 text-[11px] text-gray-500 bg-gray-50 border-l-4 border-[#FFE600] px-3 py-2" data-testid="key-storage-note">
        Prototype note: keys you paste here are stored in the application database in plain text. Do not use production secrets in this demo environment.
      </div>

      <div className="grid grid-cols-1 lg:grid-cols-2 gap-3 mb-4">
        {config.roles.map((r) => (
          <RoleEditor key={r} name={r} profile={profiles[r]} config={config} roleCount={byRole[r]} onChange={onChange} />
        ))}
      </div>

      <div className="border border-gray-200 p-4 mb-4" data-testid="sovereignty-section">
        <div className="font-[Chivo] font-bold text-sm mb-1">Data Sovereignty Routing</div>
        <p className="text-xs text-gray-500 mb-3 max-w-2xl">Tiers marked <span className="font-bold">on-prem required</span> may only be processed by a role pointed at a local (custom) endpoint. If the role is on a cloud provider, the call is blocked and falls back to deterministic advisory — regulated data never leaves on-prem.</p>
        <div className="grid grid-cols-5 gap-2">
          {["T0", "T1", "T2", "T3", "T4"].map((t) => (
            <label key={t} data-testid={`sovereignty-${t}`} className={`border p-2 cursor-pointer text-center ${sovereignty?.[t] ? "border-black bg-gray-50" : "border-gray-200"}`}>
              <div className="font-mono text-xs font-bold">{t}</div>
              <div className="text-[9px] uppercase tracking-wider text-gray-400 mb-1">{t === "T0" ? "secrets" : t === "T1" ? "high-risk PII" : t === "T2" ? "other PII" : t === "T3" ? "confidential" : "public"}</div>
              <input type="checkbox" checked={!!sovereignty?.[t]} onChange={(e) => setSovereignty((s) => ({ ...s, [t]: e.target.checked }))} className="accent-black" />
              <div className="text-[9px] text-gray-500 mt-0.5">{sovereignty?.[t] ? "on-prem only" : "cloud ok"}</div>
            </label>
          ))}
        </div>
      </div>

      <div className="border border-gray-200 p-4 flex items-center justify-between mb-6" data-testid="zero-llm-toggle">
        <div>
          <div className="font-[Chivo] font-bold text-sm">Zero-LLM mode</div>
          <p className="text-xs text-gray-500 max-w-xl">Disables all generation. Every agent and report falls back to deterministic output only.</p>
        </div>
        <Switch data-testid="zero-llm-switch" checked={zeroLlm} onCheckedChange={setZeroLlm} />
      </div>

      <div className="border border-gray-200 p-4 mb-6" data-testid="llm-budget-control">
        <label className="flex flex-wrap items-center justify-between gap-4">
          <span>
            <span className="block font-[Chivo] font-bold text-sm">Maximum model calls per governance run</span>
            <span className="mt-1 block max-w-2xl text-xs text-gray-500">When the limit is reached, deterministic checks continue. Model-only work is recorded as not assessed instead of silently treated as reviewed. Set to zero for deterministic-only runs.</span>
          </span>
          <input
            data-testid="llm-budget-input"
            type="number"
            min="0"
            max="100"
            step="1"
            value={maxCallsPerRun}
            onChange={(e) => setMaxCallsPerRun(Math.max(0, Math.min(100, Number(e.target.value) || 0)))}
            className="w-24 border border-gray-300 px-3 py-2 text-sm font-mono"
          />
        </label>
        <p className="mt-2 text-[11px] text-gray-400">This controls call count, not a guaranteed dollar spend. Exact token and provider pricing metering is a later gateway enhancement.</p>
      </div>

      <button data-testid="save-config-btn" onClick={save} disabled={saving}
        className="px-5 py-2 text-sm font-bold bg-black text-white hover:bg-[#FFE600] hover:text-black transition-colors disabled:opacity-50 mb-8">
        {saving ? "Saving…" : "Save configuration"}
      </button>

      <div className="mt-2">
        <div className="flex items-center justify-between border-b border-gray-200 pb-1 mb-2">
          <h2 className="font-[Chivo] font-bold text-lg">LLM Call Audit Log</h2>
          <span className="text-xs text-gray-400">{callsData?.total ?? 0} total calls · hashes only, never raw text</span>
        </div>
        <div className="overflow-x-auto border border-gray-200">
          <table className="w-full text-sm">
            <thead>
              <tr className="bg-gray-50 border-y border-gray-300">
                {["Time", "Task", "Agent", "Level", "Role", "Provider", "Model", "Mode", "Latency"].map((h) => (
                  <th key={h} className="text-left text-[10px] uppercase tracking-wider text-gray-600 font-bold py-2 px-3">{h}</th>
                ))}
              </tr>
            </thead>
            <tbody>
              {(callsData?.calls || []).map((c) => (
                <tr key={c.id} data-testid={`llm-call-${c.id}`} className="hover:bg-gray-50">
                  <td className="border-b border-gray-200 py-1.5 px-3 text-[11px] text-gray-500 font-mono">{(c.timestamp || "").slice(11, 19)}</td>
                  <td className="border-b border-gray-200 py-1.5 px-3 text-xs">{c.task}</td>
                  <td className="border-b border-gray-200 py-1.5 px-3 font-mono text-xs">{c.agent_id || "—"}</td>
                  <td className="border-b border-gray-200 py-1.5 px-3 text-xs">{c.level ?? "—"}</td>
                  <td className="border-b border-gray-200 py-1.5 px-3 text-xs">{c.capability_profile}</td>
                  <td className="border-b border-gray-200 py-1.5 px-3 text-xs">{c.provider}</td>
                  <td className="border-b border-gray-200 py-1.5 px-3 text-xs font-mono">{c.model_used}</td>
                  <td className="border-b border-gray-200 py-1.5 px-3 text-xs">{c.mode}</td>
                  <td className="border-b border-gray-200 py-1.5 px-3 text-xs">{c.latency_ms ?? 0} ms</td>
                </tr>
              ))}
              {!callsData?.calls?.length && (
                <tr><td colSpan={9} className="py-6 text-center text-sm text-gray-400">No calls logged yet. Run an agent in the Harness sandbox.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
