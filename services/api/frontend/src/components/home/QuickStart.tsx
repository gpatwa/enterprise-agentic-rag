import { TrendingUp, ShoppingBag, Star, Truck, type LucideIcon } from 'lucide-react';
import type { QuickStartCategory } from '@/types';

const iconMap: Record<string, LucideIcon> = {
  revenue: TrendingUp,
  products: ShoppingBag,
  reviews: Star,
  delivery: Truck,
};

const tonesByIndex = [
  { ring: 'ring-accent/20', bg: 'bg-accent/15', text: 'text-accent' },
  { ring: 'ring-data/20', bg: 'bg-data/15', text: 'text-data' },
  { ring: 'ring-knowledge/20', bg: 'bg-knowledge/15', text: 'text-knowledge' },
  { ring: 'ring-governance/20', bg: 'bg-governance/15', text: 'text-governance' },
];

interface Props {
  categories: QuickStartCategory[];
  onPickQuestion?: (text: string) => void;
}

export function QuickStart({ categories, onPickQuestion }: Props) {
  return (
    <section>
      <SectionHead label="Quick start" />
      <div className="grid grid-cols-2 gap-3">
        {categories.map((cat, i) => {
          const tone = tonesByIndex[i % tonesByIndex.length];
          const Icon = iconMap[cat.id] ?? TrendingUp;
          const firstQuestion = cat.questions[0]?.text;
          return (
            <button
              key={cat.id}
              onClick={() => firstQuestion && onPickQuestion?.(firstQuestion)}
              className="glass rounded-xl p-4 text-left group hover:border-border-strong transition"
            >
              <div className="flex items-start gap-3">
                <div
                  className={`w-9 h-9 rounded-lg ${tone.bg} flex items-center justify-center ${tone.text} ring-1 ${tone.ring}`}
                >
                  <Icon className="w-4 h-4" />
                </div>
                <div className="flex-1 min-w-0">
                  <div className="font-semibold text-sm text-fg">{cat.title}</div>
                  <div className="text-xs text-fg-muted mt-0.5">{cat.description}</div>
                  {firstQuestion && (
                    <div className="text-xs text-fg-secondary mt-3 truncate group-hover:text-fg transition">
                      › {firstQuestion}
                    </div>
                  )}
                </div>
              </div>
            </button>
          );
        })}
      </div>
    </section>
  );
}

function SectionHead({ label }: { label: string }) {
  return (
    <div className="mb-3 flex items-center gap-2">
      <h2 className="text-xs uppercase tracking-wider text-fg-muted font-medium">{label}</h2>
      <div className="flex-1 h-px bg-white/5" />
    </div>
  );
}
