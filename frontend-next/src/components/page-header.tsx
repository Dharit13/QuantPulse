interface PageHeaderProps {
  title: string;
  subtitle?: string;
  description?: string;
  actions?: React.ReactNode;
}

export function PageHeader({ title, subtitle, description, actions }: PageHeaderProps) {
  return (
    <div className="mb-8">
      <div className="flex items-start justify-between">
        <div>
          <h1 className="text-[28px] font-bold text-text-primary tracking-tight">
            {title}
          </h1>
          {subtitle && (
            <p className="text-[14px] text-text-secondary mt-1">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-3">{actions}</div>}
      </div>
      {description && (
        <div className="mt-4 px-5 py-3.5 bg-card-alt rounded-xl border border-border text-[13px] text-text-body leading-relaxed">
          {description}
        </div>
      )}
    </div>
  );
}
