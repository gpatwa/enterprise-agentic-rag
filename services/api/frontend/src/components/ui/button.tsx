import * as React from 'react';
import { Slot } from '@radix-ui/react-slot';
import { cva, type VariantProps } from 'class-variance-authority';
import { cn } from '@/lib/utils';

const buttonVariants = cva(
  'inline-flex items-center justify-center gap-2 whitespace-nowrap rounded-md text-sm font-medium ring-offset-bg transition-[transform,box-shadow,border-color,background] active:scale-[0.98] focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-ring focus-visible:ring-offset-2 disabled:pointer-events-none disabled:opacity-50 cursor-pointer',
  {
    variants: {
      variant: {
        default:
          'bg-accent-grad text-accent-fg shadow-[0_4px_20px_-4px_hsl(var(--accent-from)/0.40),0_0_0_1px_rgba(255,255,255,0.06)_inset] hover:shadow-[0_6px_24px_-4px_hsl(var(--accent-from)/0.50),0_0_0_1px_rgba(255,255,255,0.10)_inset]',
        secondary: 'glass text-fg hover:border-border-strong',
        outline:
          'border border-border bg-transparent text-fg hover:bg-surface-muted hover:border-border-strong',
        ghost: 'text-fg-secondary hover:bg-surface-muted hover:text-fg',
        destructive: 'bg-destructive text-white hover:opacity-90',
        link: 'text-fg-secondary underline-offset-4 hover:underline hover:text-fg',
      },
      size: {
        default: 'h-9 px-4 py-2',
        sm: 'h-8 rounded-md px-3 text-xs',
        lg: 'h-11 rounded-lg px-6 text-base',
        icon: 'h-9 w-9',
      },
    },
    defaultVariants: {
      variant: 'default',
      size: 'default',
    },
  }
);

export interface ButtonProps
  extends React.ButtonHTMLAttributes<HTMLButtonElement>,
    VariantProps<typeof buttonVariants> {
  asChild?: boolean;
}

export const Button = React.forwardRef<HTMLButtonElement, ButtonProps>(
  ({ className, variant, size, asChild = false, ...props }, ref) => {
    const Comp = asChild ? Slot : 'button';
    return (
      <Comp
        className={cn(buttonVariants({ variant, size, className }))}
        ref={ref}
        {...props}
      />
    );
  }
);
Button.displayName = 'Button';

export { buttonVariants };
