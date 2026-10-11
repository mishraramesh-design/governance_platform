import { useState, useEffect } from "react";
import { useQuery, useQueryClient } from "@tanstack/react-query";
import api from "../lib/api";
import { PageHeader } from "../components/PageHeader";
import { Switch } from "../components/ui/switch";
import { toast } from "sonner";

const PROFILE_META = {
  primary: {
    label: "Primary",
    note: "Level-1 checks. The main model for requirement rewrites and report narratives.",
  },
  "independent-reviewer": {
    label: "Independent Reviewer",
    note: "Level-2 review. MUST be a different model family than primary for genuine independence.",
  },
};

function ProfileEditor({ name, profile, availableModels, onChange }) {
  const meta = PROFILE_META[name] || { label: name, note: "" };
  const providers = Object.keys(availableModels);
  const provider = profile?.provider || providers[0];
  const models = availableModels[provider] || [];

  return (
    <div className="border border-gray-200 p-4" data-testid={`profile-editor-${name}`}>
      <div className="flex items-center justify-between mb-1">
        <div className="font-[Chivo] font-bold text-sm">{meta.label}</div>
        <span className="font-mono text-[10px] uppercase tracking-wider text-gray-400">{name}</span>
      </div>
      <p className="text-xs text-gray-500 mb-3">{meta.note}</p>
      <div className="grid grid-cols-2 gap-2">
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-gray-400">Provider</span>
          <select
            data-testid={`profile-provider-${name}`}
            value={provider}
            onChange={(e) => {
              const p = e.target.value;
              onChange(name, { provider: p, model: (availableModels[p] || [])[0] });
            }}
            className="w-full mt-0.5 text-sm border border-gray-300 px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
          >
            {providers.map((p) => (
              <option key={p} value={p}>{p}</option>
            ))}
          </select>
        </label>
        <label className="block">
          <span className="text-[10px] uppercase tracking-wider text-gray-400">Model</span>
          <select
            data-testid={`profile-model-${name}`}
            value={profile?.model || models[0]}
            onChange={(e) => onChange(name, { provider, model: e.target.value })}
            className="w-full mt-0.5 text-sm border border-gray-300 px-2 py-1.5 bg-white focus:outline-none focus:ring-2 focus:ring-[#FFE600]"
          >
            {models.map((m) => (
              <option key={m} value={m}>{m}</option>
            ))}
          </select>
        </label>
      </div>
    </div>
  );
}

export default function ModelSettings() {
  const qc = useQueryClient();
  const { data: config, isLoading } = useQuery({
    queryKey: ["harness-config"],
    queryFn: () => api.get("/harness/config").then((r) => r.data),
  });
  const { data: callsData } = useQuery({
    queryKey: ["llm-calls"],
    queryFn: () => api.get("/harness/llm-calls?limit=25").then((r) => r.data),
    refetchInterval: 5000,
  });

  const [profiles, setProfiles] = useState(null);
  const [zeroLlm, setZeroLlm] = useState(false);
  const [saving, setSaving] = useState(false);

  useEffect(() => {
    if (config) {
      setProfiles(config.capability_profiles);
      setZeroLlm(config.zero_llm_mode);
    }
  }, [config]);

  const onChange = (name, prof) => setProfiles((p) => ({ ...p, [name]: prof }));

  const sameFamily =
    profiles?.primary && profiles?.["independent-reviewer"] &&
    profiles.primary.provider === profiles["independent-reviewer"].provider;

  const save = async () => {
    setSaving(true);
    try {
      await api.put("/harness/config", { capability_profiles: profiles, zero_llm_mode: zeroLlm });
      qc.invalidateQueries({ queryKey: ["harness-config"] });
      toast.success("Gateway configuration saved");
    } catch (e) {
      toast.error(e?.response?.data?.detail || "Save failed");
    } finally {
      setSaving(false);
    }
  };

  if (isLoading || !profiles) return <div className="text-sm text-gray-400">Loading…</div>;

  return (
    <div data-testid="model-settings-page">
      <PageHeader
        title="Model Gateway Settings"
        subtitle="Configure the capability profiles the harness routes through. All agent and task calls go through this single gateway — nothing calls a model directly."
      />

      <div className="mb-4 flex items-center gap-2 text-xs">
        <span className="text-gray-400 uppercase tracking-wider">Key mode:</span>
        <span className="font-bold px-2 py-0.5 bg-gray-100" data-testid="key-mode">
          {config.key_mode === "emergent_universal"
            ? "Emergent Universal Key (multi-provider)"
            : config.key_mode === "openai_only"
            ? "OpenAI key only"
            : "No key configured"}
        </span>
      </div>

      <div className="grid grid-cols-1 md:grid-cols-2 gap-3 mb-4">
        <ProfileEditor name="primary" profile={profiles.primary} availableModels={config.available_models} onChange={onChange} />
        <ProfileEditor name="independent-reviewer" profile={profiles["independent-reviewer"]} availableModels={config.available_models} onChange={onChange} />
      </div>

      {sameFamily && (
        <div className="mb-4 text-xs text-red-700 bg-red-50 border-l-4 border-red-600 px-3 py-2" data-testid="independence-warning">
          ⚠ Primary and Independent Reviewer use the same provider family. Level-2 review will not be
          model-independent. Choose a different provider for the reviewer.
        </div>
      )}

      <div className="border border-gray-200 p-4 flex items-center justify-between mb-6" data-testid="zero-llm-toggle">
        <div>
          <div className="font-[Chivo] font-bold text-sm">Zero-LLM mode</div>
          <p className="text-xs text-gray-500 max-w-xl">
            Disables all generation. Every agent and report falls back to deterministic output only — proving
            the platform works without any model call.
          </p>
        </div>
        <Switch data-testid="zero-llm-switch" checked={zeroLlm} onCheckedChange={setZeroLlm} />
      </div>

      <button
        data-testid="save-config-btn"
        onClick={save}
        disabled={saving}
        className="px-5 py-2 text-sm font-bold bg-black text-white hover:bg-[#FFE600] hover:text-black transition-colors disabled:opacity-50 mb-8"
      >
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
                {["Time", "Task", "Agent", "Level", "Profile", "Provider", "Model", "Mode", "Latency", "Input hash"].map((h) => (
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
                  <td className="border-b border-gray-200 py-1.5 px-3 font-mono text-[10px] text-gray-400">{(c.masked_input_hash || "").slice(0, 10)}…</td>
                </tr>
              ))}
              {!callsData?.calls?.length && (
                <tr><td colSpan={10} className="py-6 text-center text-sm text-gray-400">No calls logged yet. Run an agent in the Harness sandbox.</td></tr>
              )}
            </tbody>
          </table>
        </div>
      </div>
    </div>
  );
}
