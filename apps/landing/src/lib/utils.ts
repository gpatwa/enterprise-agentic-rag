import { clsx, type ClassValue } from 'clsx';
import { twMerge } from 'tailwind-merge';

/** shadcn-style class composition helper. */
export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
