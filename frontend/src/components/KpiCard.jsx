export function KpiCard({ label, value, hint, testId }) {
  return (
    <div data-testid={testId} className="border border-gray-200 p-4 sm:p-5 bg-white">
      <div className="text-[10px] uppercase tracking-[0.2em] font-bold text-gray-500">{label}</div>
      <div className="mt-2 text-3xl font-black tracking-tighter tabular-nums text-black">{value}</div>
      {hint && <div className="mt-1 text-xs text-gray-400">{hint}</div>}
    </div>
  );
}
