import { type LucideIcon } from 'lucide-react';

interface Props {
  icon: LucideIcon;
  title: string;
  description: string;
  ship?: string;
}

/** Reusable "coming in W2/W3" placeholder for sidebar links. */
export function StubPage({ icon: Icon, title, description, ship }: Props) {
  return (
    <div className="flex-1 flex items-center justify-center px-8">
      <div className="text-center max-w-md">
        <div className="w-14 h-14 rounded-xl glass mx-auto mb-5 flex items-center justify-center">
          <Icon className="w-6 h-6 text-fg-secondary" />
        </div>
        <h1 className="text-xl font-semibold tracking-tight">{title}</h1>
        <p className="text-fg-secondary mt-2 leading-relaxed">{description}</p>
        {ship && (
          <div className="mt-6 inline-flex items-center gap-2 px-3 py-1.5 rounded-full glass text-xs text-fg-muted">
            <span className="w-1.5 h-1.5 rounded-full bg-governance" />
            Ships {ship}
          </div>
        )}
      </div>
    </div>
  );
}
