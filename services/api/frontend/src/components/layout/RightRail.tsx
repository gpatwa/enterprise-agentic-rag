import { ShieldCheck } from 'lucide-react';
import type {
  SourceHealth,
  KnowledgeCounts,
  Governance,
  Tenant,
  User,
} from '@/types';

interface Props {
  sources: SourceHealth[];
  knowledge: KnowledgeCounts;
  governance: Governance;
  tenant: Tenant;
  user: User;
}

const statusDot = {
  fresh: 'bg-knowledge',
  stale: 'bg-governance',
  error: 'bg-destructive',
  not_connected: 'bg-white/20',
} as const;

export function RightRail({ sources, knowledge, governance, tenant, user }: Props) {
  return (
    <aside className="w-[300px] glass border-l overflow-auto">
      <div className="px-5 py-5">
        {/* Sources */}
        <section className="mb-6">
          <div className="flex items-center justify-between mb-3">
            <div className="text-xs uppercase tracking-wider text-fg-muted font-medium">Sources</div>
            <button className="text-xs text-fg-muted hover:text-fg transition">Manage</button>
          </div>
          <div className="space-y-2">
            {sources.map((s) => (
              <div key={s.name} className="flex items-center justify-between py-1">
                <div className="flex items-center gap-2">
                  <span
                    className={`w-1.5 h-1.5 rounded-full ${statusDot[s.status]}`}
                    aria-label={s.status}
                  />
                  <span className={s.status === 'not_connected' ? 'text-sm text-fg-muted' : 'text-sm'}>
                    {s.name}
                  </span>
                </div>
                <span className="font-mono text-xs text-fg-muted">
                  {s.row_count
                    ? formatCount(s.row_count)
                    : s.chunk_count
                      ? `${s.chunk_count} chunks`
                      : s.node_count
                        ? `${s.node_count} nodes`
                        : '—'}
                </span>
              </div>
            ))}
          </div>
        </section>

        {/* Knowledge layers */}
        <section className="mb-6 glass rounded-md p-3">
          <div className="text-xs uppercase tracking-wider text-fg-muted font-medium mb-3">
            Knowledge layers
          </div>
          <div className="grid grid-cols-3 gap-2 text-center">
            <KnowledgeStat value={knowledge.glossary} label="Glossary" />
            <KnowledgeStat value={knowledge.business_rules} label="Rules" />
            <KnowledgeStat value={knowledge.code_context} label="Code" />
          </div>
        </section>

        {/* Governance */}
        <section>
          <div className="text-xs uppercase tracking-wider text-fg-muted font-medium mb-3 flex items-center gap-1.5">
            <ShieldCheck className="w-3 h-3" />
            Governance
          </div>
          <dl className="text-xs text-fg-secondary space-y-1.5">
            <Row label="Tenant" value={tenant.id} mono />
            <Row label="Role" value={user.role} mono />
            {tenant.residency && <Row label="Residency" value={tenant.residency} mono />}
            <Row
              label="PII redaction"
              value={governance.pii_redaction ? 'on' : 'off'}
              valueClass={governance.pii_redaction ? 'text-knowledge' : 'text-fg-muted'}
            />
            <Row
              label="Audit log"
              value={governance.audit_logging ? 'on' : 'off'}
              valueClass={governance.audit_logging ? 'text-knowledge' : 'text-fg-muted'}
            />
          </dl>
        </section>
      </div>
    </aside>
  );
}

function KnowledgeStat({ value, label }: { value: number; label: string }) {
  return (
    <a href="#" className="block hover:text-fg transition">
      <div className="font-serif text-2xl font-medium text-fg">{value}</div>
      <div className="text-[10px] text-fg-muted mt-0.5">{label}</div>
    </a>
  );
}

function Row({
  label,
  value,
  mono,
  valueClass = 'text-fg',
}: {
  label: string;
  value: string;
  mono?: boolean;
  valueClass?: string;
}) {
  return (
    <div className="flex items-center justify-between">
      <dt>{label}</dt>
      <dd className={`${mono ? 'font-mono' : ''} ${valueClass}`}>{value}</dd>
    </div>
  );
}

function formatCount(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(1)}K`;
  return String(n);
}
