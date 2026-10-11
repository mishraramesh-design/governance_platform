export function VerdictPill({ verdict }) {
  const map = {
    PASS: "bg-green-100 text-green-800 border-l-4 border-green-600",
    FAIL: "bg-red-100 text-red-800 border-l-4 border-red-600",
    NOT_ASSESSED: "bg-gray-100 text-gray-700 border-l-4 border-gray-400",
  };
  return (
    <span
      data-testid={`verdict-pill-${verdict}`}
      className={`inline-block px-2 py-1 text-[11px] font-bold uppercase tracking-wide ${map[verdict] || map.NOT_ASSESSED}`}
    >
      {verdict.replace("_", " ")}
    </span>
  );
}

export function SeverityPill({ severity }) {
  const map = {
    critical: "bg-black text-[#FFE600]",
    high: "bg-red-600 text-white",
    medium: "bg-[#FFE600] text-black",
    low: "bg-gray-200 text-gray-800",
    info: "bg-gray-100 text-gray-500",
  };
  return (
    <span
      data-testid={`severity-pill-${severity}`}
      className={`inline-block px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-sm ${map[severity] || map.info}`}
    >
      {severity}
    </span>
  );
}

export function ProvenancePill({ provenance }) {
  const map = {
    platform_service: { label: "Platform · Verified", cls: "bg-black text-[#FFE600]" },
    platform_model: { label: "Platform · Model", cls: "bg-gray-800 text-white" },
    client_model_unverified: { label: "Client Model · Unverified", cls: "bg-white text-gray-700 border border-dashed border-gray-400" },
    unattributed: { label: "Unattributed", cls: "bg-white text-gray-400 border border-gray-300" },
  };
  const c = map[provenance] || map.unattributed;
  return (
    <span data-testid={`provenance-pill-${provenance}`} className={`inline-block px-2 py-0.5 text-[10px] font-semibold uppercase tracking-wide rounded-sm ${c.cls}`}>
      {c.label}
    </span>
  );
}

export function RoutingPill({ routing }) {
  if (!routing) return null;
  const map = {
    DECIDE: "bg-[#FFE600] text-black",
    URGENT: "bg-red-600 text-white",
    RECEIVE: "bg-gray-800 text-white",
    INFORM: "bg-gray-100 text-gray-600",
  };
  return (
    <span data-testid={`routing-pill-${routing}`} className={`inline-block px-2 py-0.5 text-[10px] font-bold uppercase tracking-wider rounded-sm ${map[routing]}`}>
      You: {routing}
    </span>
  );
}

export function AdvisoryBadge() {
  return (
    <span
      data-testid="advisory-badge"
      className="inline-flex items-center gap-1.5 px-3 py-1 bg-[#111111] text-[#FFE600] text-[11px] font-bold uppercase tracking-wider rounded-full"
    >
      <span className="w-1.5 h-1.5 rounded-full bg-[#FFE600] animate-pulse" />
      Read-only · Advisory
    </span>
  );
}
