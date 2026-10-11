export function PageHeader({ title, subtitle, actions }) {
  return (
    <div className="flex items-start justify-between gap-4 mb-6 pb-4 border-b border-gray-200">
      <div>
        <h1 className="font-[Chivo] text-3xl sm:text-4xl tracking-tighter font-black text-black">{title}</h1>
        {subtitle && <p className="mt-1.5 text-sm text-gray-500 max-w-2xl">{subtitle}</p>}
      </div>
      {actions && <div className="flex items-center gap-2 shrink-0">{actions}</div>}
    </div>
  );
}
