import { GlowingEffect } from "./ui/glowing-effect";

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
          <h1 className="text-2xl font-black bg-gradient-to-r from-[#00ccb1] via-[#7b61ff] to-[#1ca0fb] bg-clip-text text-transparent tracking-tight">
            {title}
          </h1>
          {subtitle && (
            <p className="text-[14px] text-foreground/80 mt-1">{subtitle}</p>
          )}
        </div>
        {actions && <div className="flex items-center gap-3">{actions}</div>}
      </div>
      {description && (
        <div className="relative mt-4 rounded-[1.25rem] border-[0.75px] border-border p-2 md:rounded-[1.5rem] md:p-3">
          <GlowingEffect
            spread={40}
            glow
            disabled={false}
            proximity={64}
            inactiveZone={0.01}
            borderWidth={3}
          />
          <div className="relative px-5 py-3.5 rounded-xl border-[0.75px] border-border bg-background text-[14px] font-medium text-foreground/80 leading-relaxed shadow-sm dark:shadow-[0px_0px_27px_0px_rgba(45,45,45,0.3)]">
            {description}
          </div>
        </div>
      )}
    </div>
  );
}
