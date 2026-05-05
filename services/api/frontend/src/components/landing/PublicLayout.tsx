import { type ReactNode } from 'react';
import { Link } from 'react-router-dom';
import { Button } from '@/components/ui/button';

/**
 * Minimal layout for public marketing pages — no Sidebar, no TopBar.
 * Header is just brand mark + nav + CTA. Keeps the surface focused on
 * conversion and avoids leaking signed-in chrome to anonymous visitors.
 */
export function PublicLayout({ children }: { children: ReactNode }) {
  return (
    <div className="min-h-screen flex flex-col bg-bg text-fg">
      <a
        href="#main"
        className="sr-only focus:not-sr-only focus:absolute focus:top-2 focus:left-2 focus:z-50 focus:rounded-md focus:bg-accent focus:text-accent-fg focus:px-3 focus:py-1.5 focus:text-sm focus:font-medium"
      >
        Skip to main content
      </a>
      <PublicHeader />
      <main id="main" tabIndex={-1} className="flex-1">
        {children}
      </main>
      <PublicFooter />
    </div>
  );
}

function PublicHeader() {
  return (
    <header className="sticky top-0 z-30 backdrop-blur-md bg-bg/70 border-b border-border/40">
      <nav
        aria-label="Primary"
        className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 h-14 flex items-center gap-6"
      >
        <Link to="/welcome" className="flex items-center gap-2 group" aria-label="Compass home">
          <img src="/compass-mark.svg" alt="" width={22} height={22} aria-hidden="true" />
          <span className="font-semibold tracking-tight text-fg group-hover:text-accent transition">
            Compass
          </span>
        </Link>
        <ul className="hidden md:flex items-center gap-1 text-sm">
          <li>
            <Link
              to="/solutions/everyone"
              className="px-3 py-1.5 rounded-md text-fg-secondary hover:text-fg hover:bg-surface-muted transition"
            >
              Solutions
            </Link>
          </li>
          <li>
            <a
              href="#how-it-works"
              className="px-3 py-1.5 rounded-md text-fg-secondary hover:text-fg hover:bg-surface-muted transition"
            >
              How it works
            </a>
          </li>
          <li>
            <a
              href="#trust"
              className="px-3 py-1.5 rounded-md text-fg-secondary hover:text-fg hover:bg-surface-muted transition"
            >
              Security
            </a>
          </li>
          <li>
            <a
              href="#faq"
              className="px-3 py-1.5 rounded-md text-fg-secondary hover:text-fg hover:bg-surface-muted transition"
            >
              FAQ
            </a>
          </li>
        </ul>
        <div className="flex-1" />
        <Button asChild variant="ghost" size="sm" className="hidden sm:inline-flex">
          <Link to="/">Sign in</Link>
        </Button>
        <Button asChild size="sm">
          <a href="#book-demo">Book a demo</a>
        </Button>
      </nav>
    </header>
  );
}

function PublicFooter() {
  const year = new Date().getFullYear();
  return (
    <footer className="border-t border-border/40 mt-24">
      <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-10 grid grid-cols-2 md:grid-cols-4 gap-8 text-sm">
        <div className="col-span-2 md:col-span-1">
          <Link to="/welcome" className="flex items-center gap-2" aria-label="Compass home">
            <img src="/compass-mark.svg" alt="" width={20} height={20} aria-hidden="true" />
            <span className="font-semibold">Compass</span>
          </Link>
          <p className="text-fg-muted mt-3 leading-relaxed">
            Ask. Verify. Act. The unified answer-and-action layer for enterprise data.
          </p>
        </div>
        <FooterColumn
          heading="Product"
          links={[
            { label: 'Try Compass', href: '/' },
            { label: 'How it works', href: '#how-it-works' },
            { label: 'Security', href: '#trust' },
            { label: 'FAQ', href: '#faq' },
          ]}
        />
        <FooterColumn
          heading="Solutions"
          links={[
            { label: 'For Finance', href: '/solutions/finance' },
            { label: 'For RevOps', href: '/solutions/revops' },
            { label: 'For Data teams', href: '/solutions/data' },
            { label: 'For Security', href: '/solutions/security' },
          ]}
        />
        <FooterColumn
          heading="Company"
          links={[
            { label: 'Book a demo', href: '#book-demo' },
            { label: 'Sign in', href: '/' },
          ]}
        />
      </div>
      <div className="border-t border-border/40">
        <div className="max-w-6xl mx-auto px-4 sm:px-6 lg:px-8 py-5 flex flex-col sm:flex-row items-start sm:items-center justify-between gap-2 text-xs text-fg-muted">
          <span>&copy; {year} Compass. All rights reserved.</span>
          <span>SOC 2 Type II in progress · GDPR-ready · Tenant-isolated by default</span>
        </div>
      </div>
    </footer>
  );
}

function FooterColumn({
  heading,
  links,
}: {
  heading: string;
  links: { label: string; href: string }[];
}) {
  return (
    <div>
      <h2 className="text-xs uppercase tracking-widest text-fg-muted font-medium mb-3">
        {heading}
      </h2>
      <ul className="space-y-2">
        {links.map((l) => {
          const isExternal = l.href.startsWith('http');
          const isHash = l.href.startsWith('#');
          if (isHash || isExternal) {
            return (
              <li key={l.href}>
                <a
                  href={l.href}
                  className="text-fg-secondary hover:text-fg transition"
                  {...(isExternal ? { target: '_blank', rel: 'noreferrer' } : {})}
                >
                  {l.label}
                </a>
              </li>
            );
          }
          return (
            <li key={l.href}>
              <Link to={l.href} className="text-fg-secondary hover:text-fg transition">
                {l.label}
              </Link>
            </li>
          );
        })}
      </ul>
    </div>
  );
}
