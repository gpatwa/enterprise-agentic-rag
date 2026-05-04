/**
 * Theme provider.
 *
 * Modes:
 *   - "system" → follow prefers-color-scheme (default)
 *   - "dark"   → force dark
 *   - "light"  → force light
 *
 * The actual class applied to <html> is always "dark" or "light"
 * (no "system" class). Persisted to localStorage as `compass.theme`.
 */
import * as React from 'react';

export type ThemePreference = 'system' | 'dark' | 'light';
export type ResolvedTheme = 'dark' | 'light';

const STORAGE_KEY = 'compass.theme';

interface ThemeContextValue {
  preference: ThemePreference;
  resolved: ResolvedTheme;
  setPreference: (p: ThemePreference) => void;
}

const ThemeContext = React.createContext<ThemeContextValue | undefined>(undefined);

function readPreference(): ThemePreference {
  if (typeof window === 'undefined') return 'dark';
  const v = window.localStorage.getItem(STORAGE_KEY);
  if (v === 'dark' || v === 'light' || v === 'system') return v;
  return 'system';
}

function systemTheme(): ResolvedTheme {
  if (typeof window === 'undefined') return 'dark';
  return window.matchMedia('(prefers-color-scheme: light)').matches ? 'light' : 'dark';
}

function applyTheme(resolved: ResolvedTheme) {
  const root = document.documentElement;
  if (resolved === 'light') {
    root.classList.add('light');
    root.classList.remove('dark');
    root.style.colorScheme = 'light';
  } else {
    root.classList.add('dark');
    root.classList.remove('light');
    root.style.colorScheme = 'dark';
  }
}

export function ThemeProvider({ children }: { children: React.ReactNode }) {
  const [preference, setPreferenceState] = React.useState<ThemePreference>(() => readPreference());
  const [resolved, setResolved] = React.useState<ResolvedTheme>(() =>
    preference === 'system' ? systemTheme() : preference
  );

  // Apply on mount + when resolved changes
  React.useEffect(() => {
    applyTheme(resolved);
  }, [resolved]);

  // Watch system preference changes when in "system" mode
  React.useEffect(() => {
    if (preference !== 'system') {
      setResolved(preference);
      return;
    }
    const mq = window.matchMedia('(prefers-color-scheme: light)');
    const update = () => setResolved(mq.matches ? 'light' : 'dark');
    update();
    mq.addEventListener('change', update);
    return () => mq.removeEventListener('change', update);
  }, [preference]);

  const setPreference = React.useCallback((p: ThemePreference) => {
    setPreferenceState(p);
    window.localStorage.setItem(STORAGE_KEY, p);
  }, []);

  const value = React.useMemo(() => ({ preference, resolved, setPreference }), [
    preference,
    resolved,
    setPreference,
  ]);

  return <ThemeContext.Provider value={value}>{children}</ThemeContext.Provider>;
}

export function useTheme() {
  const ctx = React.useContext(ThemeContext);
  if (!ctx) throw new Error('useTheme must be used inside <ThemeProvider>');
  return ctx;
}
