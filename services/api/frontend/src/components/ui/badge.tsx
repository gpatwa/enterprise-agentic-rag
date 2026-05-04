import * as React from 'react';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const badgeVariants = cva(
  'inline-flex items-center rounded px-1.5 py-0.5 text-xs font-medium transition-colors',
  {
    variants: {
      variant: {
        default: 'bg-accent/15 text-accent border border-accent/25',
        secondary: 'bg-surface-muted text-fg-secondary border border-border',
        success: 'bg-knowledge/15 text-knowledge border border-knowledge/25',
        warning: 'bg-governance/15 text-governance border border-governance/25',
        destructive: 'bg-destructive/15 text-destructive border border-destructive/25',
        outline: 'text-fg-secondary border border-border',
      },
    },
    defaultVariants: { variant: 'default' },
  }
);

export interface BadgeProps
  extends React.HTMLAttributes<HTMLSpanElement>,
    VariantProps<typeof badgeVariants> {}

export function Badge({ className, variant, ...props }: BadgeProps) {
  return <span className={cn(badgeVariants({ variant }), className)} {...props} />;
}
