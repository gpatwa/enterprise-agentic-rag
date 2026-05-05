import { useEffect } from 'react';

/**
 * Set page-level SEO meta tags client-side.
 *
 * Why client-side meta is acceptable here: Google executes JS and indexes
 * post-render content. For Bing/social-card scrapers we still ship sane
 * defaults in index.html, and serve a sitemap.xml + robots.txt so crawlers
 * have a static pickup path for every public URL.
 *
 * For maximum coverage at scale, a static prerender step (vite-plugin-ssg)
 * can be added later to bake `/welcome` into a real HTML file. This hook
 * is forward-compatible with that — same API, prerender just runs it once
 * at build time.
 */
export interface SEOMeta {
  title: string;
  description: string;
  /** Path-only canonical (e.g. "/welcome"). Origin is inferred at runtime. */
  canonicalPath?: string;
  /** Absolute URL or path to OG image. Defaults to /compass-og.svg. */
  ogImage?: string;
  /** "website" | "article" — defaults to website. */
  ogType?: string;
  /** schema.org JSON-LD object(s) to inject. */
  jsonLd?: object | object[];
  /** Block crawlers from indexing this page. */
  noindex?: boolean;
}

const DEFAULT_OG_IMAGE = '/compass-og.svg';
const SITE_NAME = 'Compass';

function setMeta(name: string, content: string, attr: 'name' | 'property' = 'name') {
  let el = document.head.querySelector<HTMLMetaElement>(`meta[${attr}="${name}"]`);
  if (!el) {
    el = document.createElement('meta');
    el.setAttribute(attr, name);
    document.head.appendChild(el);
  }
  el.setAttribute('content', content);
}

function setLink(rel: string, href: string) {
  let el = document.head.querySelector<HTMLLinkElement>(`link[rel="${rel}"]`);
  if (!el) {
    el = document.createElement('link');
    el.setAttribute('rel', rel);
    document.head.appendChild(el);
  }
  el.setAttribute('href', href);
}

export function useSEO(meta: SEOMeta) {
  useEffect(() => {
    const origin = typeof window !== 'undefined' ? window.location.origin : '';
    const canonical = meta.canonicalPath
      ? origin + meta.canonicalPath
      : (typeof window !== 'undefined' ? window.location.href : '');
    const ogImage = meta.ogImage ?? DEFAULT_OG_IMAGE;
    const ogImageAbs = ogImage.startsWith('http') ? ogImage : origin + ogImage;
    const ogType = meta.ogType ?? 'website';

    document.title = meta.title;
    setMeta('description', meta.description);
    setMeta('robots', meta.noindex ? 'noindex,nofollow' : 'index,follow');
    setLink('canonical', canonical);

    setMeta('og:title', meta.title, 'property');
    setMeta('og:description', meta.description, 'property');
    setMeta('og:type', ogType, 'property');
    setMeta('og:url', canonical, 'property');
    setMeta('og:image', ogImageAbs, 'property');
    setMeta('og:site_name', SITE_NAME, 'property');

    setMeta('twitter:card', 'summary_large_image');
    setMeta('twitter:title', meta.title);
    setMeta('twitter:description', meta.description);
    setMeta('twitter:image', ogImageAbs);

    const scriptIds: string[] = [];
    const lds = meta.jsonLd
      ? Array.isArray(meta.jsonLd)
        ? meta.jsonLd
        : [meta.jsonLd]
      : [];
    lds.forEach((obj, i) => {
      const id = `seo-jsonld-${i}`;
      let s = document.getElementById(id) as HTMLScriptElement | null;
      if (!s) {
        s = document.createElement('script');
        s.id = id;
        s.type = 'application/ld+json';
        document.head.appendChild(s);
      }
      s.textContent = JSON.stringify(obj);
      scriptIds.push(id);
    });

    return () => {
      scriptIds.forEach((id) => document.getElementById(id)?.remove());
    };
  }, [
    meta.title,
    meta.description,
    meta.canonicalPath,
    meta.ogImage,
    meta.ogType,
    meta.noindex,
    JSON.stringify(meta.jsonLd ?? null),
  ]);
}
