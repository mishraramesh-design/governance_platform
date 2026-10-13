export const ROLES = [
  "IV&V Lead",
  "Developer",
  "BA Lead",
  "Architect",
  "Security & Privacy Lead",
  "Test Lead",
  "Release Manager",
  "Business Owner",
  "Quality / Process Owner",
];

export const ROUTING_MATRIX = {
  requirements: { decide: ["BA Lead"], receive: ["Architect", "IV&V Lead"], inform: ["Business Owner"], urgent: [] },
  security: { decide: ["Security & Privacy Lead"], receive: ["Developer", "IV&V Lead"], inform: ["Release Manager"], urgent: ["Security & Privacy Lead"] },
  privacy: { decide: ["Security & Privacy Lead"], receive: ["Developer", "IV&V Lead"], inform: ["Business Owner"], urgent: ["Security & Privacy Lead"] },
  code_quality: { decide: ["Developer"], receive: ["Test Lead", "IV&V Lead"], inform: [], urgent: [] },
  testing: { decide: ["Test Lead"], receive: ["Developer", "IV&V Lead"], inform: [], urgent: [] },
  traceability: { decide: ["IV&V Lead"], receive: ["BA Lead", "Test Lead"], inform: ["Business Owner"], urgent: [] },
  release: { decide: ["Release Manager"], receive: ["IV&V Lead", "Business Owner"], inform: ["Developer"], urgent: ["Release Manager"] },
  not_implemented: { decide: ["IV&V Lead"], receive: [], inform: [], urgent: [] },
};

export function routingFor(tags = [], role) {
  for (const tag of tags) {
    const m = ROUTING_MATRIX[tag];
    if (!m) continue;
    if (m.urgent.includes(role)) return "URGENT";
    if (m.decide.includes(role)) return "DECIDE";
    if (m.receive.includes(role)) return "RECEIVE";
    if (m.inform.includes(role)) return "INFORM";
  }
  return null;
}
