import { act, fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import type { ProductSearchResponse } from './api/client';
import { ProductSearch } from './productSearch';

const item = (n: number, title = `Running shoe ${n}`) => ({ product_id: `P${n}`, title, brand: 'Acme', color: 'red', snippet: `bullet ${n}`, rank: n, score: 2 });
const reply = (over: Partial<ProductSearchResponse> = {}): ProductSearchResponse => ({ schema_version: 'product-search-v1', results: [item(1), item(2)], total_matches: 25, page: 1, page_size: 10, match: 'all', error: null, ...over });
const box = () => screen.getByRole('textbox', { name: 'Search products' });
const searchFor = (text: string) => { fireEvent.change(box(), { target: { value: text } }); fireEvent.keyDown(box(), { key: 'Enter' }); };
const deferred = <T,>() => { let resolve!: (value: T) => void; let reject!: (reason?: unknown) => void; const promise = new Promise<T>((res, rej) => { resolve = res; reject = rej; }); return { promise, resolve, reject }; };

/** Everything a keyboard user can reach: enabled native controls, in DOM order. */
function focusable(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>('button, input, select, [tabindex]')).filter((el) => !el.hasAttribute('disabled') && el.tabIndex >= 0);
}

describe('Search products: keyboard and names', () => {
  it('is a named region whose every enabled control is reachable and has an accessible name', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply()) };
    const { container } = render(<ProductSearch client={client} />);
    const section = screen.getByRole('region', { name: 'Product search' });
    expect(within(section).getByRole('heading', { level: 2, name: 'Search products' })).toBeInTheDocument();
    expect(within(section).getByRole('textbox', { name: 'Search products' })).toBeInTheDocument();
    expect(within(section).getByRole('combobox', { name: 'Product locale' })).toBeInTheDocument();
    expect(within(section).getByRole('button', { name: 'Search' })).toBeDisabled(); // nothing to search for yet

    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    const controls = focusable(container);
    expect(controls.length).toBeGreaterThanOrEqual(4); // input, locale, pager (next is enabled), results region
    for (const element of controls) {
      element.focus();
      expect(document.activeElement).toBe(element);
      const name = element.getAttribute('aria-label') ?? element.textContent?.trim() ?? '';
      const labelled = element instanceof HTMLInputElement && element.labels?.length;
      expect(name.length > 0 || labelled).toBeTruthy();
    }
    expect(within(section).getByRole('button', { name: 'Previous products page' })).toBeDisabled();
    expect(within(section).getByRole('button', { name: 'Next products page' })).toBeEnabled();
    expect(within(section).getByRole('navigation', { name: 'Product result pages' })).toBeInTheDocument();
  });

  it('searches with Enter, clears with Escape, and gives decorative icons and rank numbers no name', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply()) };
    const { container } = render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    fireEvent.keyDown(box(), { key: 'Escape' });
    expect(box()).toHaveValue('');
    expect(container.querySelectorAll('svg:not([aria-hidden="true"])')).toHaveLength(0);
    expect(container.querySelectorAll('.product-rank[aria-hidden="true"]')).toHaveLength(2);
    expect(screen.getAllByRole('listitem')).toHaveLength(2); // an ordered list: the order is conveyed without the numbers
    expect(screen.getByRole('list').tagName).toBe('OL');
  });

  it('moves keyboard focus to the new results after paging, because the pressed button may be disabled', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValueOnce(reply()).mockResolvedValueOnce(reply({ page: 2, results: [item(11)] })) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    expect(screen.getByRole('region', { name: 'Product results' })).not.toHaveFocus(); // a first search leaves focus where it was
    const next = screen.getByRole('button', { name: 'Next products page' });
    next.focus();
    fireEvent.click(next);
    await screen.findByText('Running shoe 11');
    await waitFor(() => expect(screen.getByRole('region', { name: 'Product results' })).toHaveFocus());
  });
});

describe('Search products: states and live regions', () => {
  it('has a live region from the first render, so later changes are announced, and keeps results out of it', async () => {
    const pending = deferred<ProductSearchResponse>();
    const client = { searchProducts: vi.fn().mockReturnValue(pending.promise) };
    render(<ProductSearch client={client} />);
    const status = screen.getByRole('status');
    expect(status).toHaveAttribute('aria-live', 'polite');
    expect(status).toBeEmptyDOMElement();

    searchFor('shoes');
    expect(screen.getByRole('status')).toBe(status); // the same node: it was not unmounted and remounted
    expect(status).toHaveTextContent('Searching products…');
    expect(screen.getByRole('button', { name: 'Searching' })).toBeDisabled();

    await act(async () => { pending.resolve(reply()); });
    expect(screen.getByRole('status')).toBe(status);
    expect(status).toHaveTextContent('25 products');
    expect(status).not.toHaveTextContent('Running shoe'); // announcing every title and snippet on each search would be noise
    expect(within(screen.getByRole('region', { name: 'Product results' })).getAllByRole('heading', { level: 3 })).toHaveLength(2);
  });

  it('marks the results busy while the next page loads and announces it', async () => {
    const second = deferred<ProductSearchResponse>();
    const client = { searchProducts: vi.fn().mockResolvedValueOnce(reply()).mockReturnValueOnce(second.promise) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    expect(screen.getByRole('region', { name: 'Product results' })).toHaveAttribute('aria-busy', 'false');

    fireEvent.click(screen.getByRole('button', { name: 'Next products page' }));
    expect(screen.getByRole('region', { name: 'Product results' })).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByRole('status')).toHaveTextContent('Searching products…');
    expect(screen.getByRole('button', { name: 'Next products page' })).toBeDisabled();

    await act(async () => { second.resolve(reply({ page: 2, results: [item(11)] })); });
    expect(screen.getByRole('region', { name: 'Product results' })).toHaveAttribute('aria-busy', 'false');
    expect(screen.getByRole('status')).toHaveTextContent('25 products');
  });

  it('announces an empty result and shows the empty state', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply({ results: [], total_matches: 0 })) };
    render(<ProductSearch client={client} />);
    searchFor('zzz');
    expect(await screen.findByText('No products matched that search.')).toBeInTheDocument();
    expect(screen.getByRole('status')).toHaveTextContent('0 products');
    expect(screen.queryByRole('list')).not.toBeInTheDocument();
    expect(screen.getByText('Page 1 of 1')).toBeInTheDocument();
  });

  it('says a single match is a product, not products', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply({ results: [item(1)], total_matches: 1 })) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    expect(screen.getByRole('status')).toHaveTextContent(/^1 product$/);
  });

  it('puts the partial-match notice inside the live region so it is announced with the count', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply({ match: 'any' })) };
    render(<ProductSearch client={client} />);
    searchFor('red shoes');
    await screen.findByText('Running shoe 1');
    expect(screen.getByRole('status')).toHaveTextContent('No product matched every word, so these match some of them.');
  });

  it('shows no partial-match notice when nothing matched at all', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply({ match: 'any', results: [], total_matches: 0 })) };
    render(<ProductSearch client={client} />);
    searchFor('zzz qqq');
    await screen.findByText('No products matched that search.');
    expect(screen.queryByText(/No product matched every word/)).not.toBeInTheDocument();
  });

  it('shows an assertive alert for a failed request, hides the stale results, and never leaks the cause', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValueOnce(reply()).mockRejectedValueOnce(new Error('connect ECONNREFUSED 10.0.0.4')) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    fireEvent.click(screen.getByRole('button', { name: 'Next products page' }));
    const alert = await screen.findByRole('alert');
    expect(alert).toHaveTextContent('Product search is unavailable right now');
    expect(alert).not.toHaveTextContent('ECONNREFUSED');
    expect(screen.queryByText('Running shoe 1')).not.toBeInTheDocument();
    expect(screen.getByRole('status')).toBeEmptyDOMElement();
    expect(within(alert).getByRole('button', { name: 'Retry' })).toBeInTheDocument();
  });

  it('retries the request that failed, not an earlier page or whatever was typed since', async () => {
    const client = {
      searchProducts: vi.fn()
        .mockResolvedValueOnce(reply())
        .mockRejectedValueOnce(new Error('boom'))
        .mockResolvedValueOnce(reply({ page: 2, results: [item(11)] })),
    };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    fireEvent.click(screen.getByRole('button', { name: 'Next products page' }));
    await screen.findByRole('alert');
    fireEvent.change(box(), { target: { value: 'something else typed meanwhile' } });
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Running shoe 11');
    expect(client.searchProducts).toHaveBeenLastCalledWith({ query: 'shoes', page: 2, page_size: 10 });
    expect(screen.getByText('Page 2 of 3')).toBeInTheDocument();
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
  });

  it('can retry a first search that failed', async () => {
    const client = { searchProducts: vi.fn().mockRejectedValueOnce(new Error('boom')).mockResolvedValueOnce(reply()) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByRole('alert');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await screen.findByText('Running shoe 1');
    expect(client.searchProducts).toHaveBeenLastCalledWith({ query: 'shoes', page: 1, page_size: 10 });
  });
});

describe('Search products: query, locale and paging', () => {
  it('returns to page 1 when the locale changes from a later page, keeping the searched words', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply()) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    fireEvent.click(screen.getByRole('button', { name: 'Next products page' }));
    await waitFor(() => expect(screen.getByText('Page 2 of 3')).toBeInTheDocument());
    fireEvent.change(screen.getByRole('combobox', { name: 'Product locale' }), { target: { value: 'jp' } });
    await waitFor(() => expect(screen.getByText('Page 1 of 3')).toBeInTheDocument());
    expect(client.searchProducts).toHaveBeenLastCalledWith({ query: 'shoes', page: 1, page_size: 10, locale: 'jp' });
    // and back to every locale: the locale key is omitted, not sent empty
    fireEvent.change(screen.getByRole('combobox', { name: 'Product locale' }), { target: { value: '' } });
    await waitFor(() => expect(client.searchProducts).toHaveBeenCalledTimes(4));
    expect(client.searchProducts).toHaveBeenLastCalledWith({ query: 'shoes', page: 1, page_size: 10 });
  });

  it('does not search when the locale is chosen before any search has been made', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply()) };
    render(<ProductSearch client={client} />);
    fireEvent.change(box(), { target: { value: 'shoes' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Product locale' }), { target: { value: 'es' } });
    expect(client.searchProducts).not.toHaveBeenCalled();
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(client.searchProducts).toHaveBeenCalledWith({ query: 'shoes', page: 1, page_size: 10, locale: 'es' });
    await screen.findByText('Running shoe 1');
  });

  it('pages and re-filters the search that was sent, not words typed afterwards', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply()) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    await screen.findByText('Running shoe 1');
    fireEvent.change(box(), { target: { value: 'boots' } }); // typed but not submitted
    fireEvent.click(screen.getByRole('button', { name: 'Next products page' }));
    await waitFor(() => expect(client.searchProducts).toHaveBeenCalledTimes(2));
    expect(client.searchProducts).toHaveBeenLastCalledWith({ query: 'shoes', page: 2, page_size: 10 });
    fireEvent.change(screen.getByRole('combobox', { name: 'Product locale' }), { target: { value: 'es' } });
    await waitFor(() => expect(client.searchProducts).toHaveBeenCalledTimes(3));
    expect(client.searchProducts).toHaveBeenLastCalledWith({ query: 'shoes', page: 1, page_size: 10, locale: 'es' });
  });

  it('ignores a slow earlier response that arrives after a newer one', async () => {
    const first = deferred<ProductSearchResponse>();
    const second = deferred<ProductSearchResponse>();
    const client = { searchProducts: vi.fn().mockReturnValueOnce(first.promise).mockReturnValueOnce(second.promise) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    fireEvent.keyDown(box(), { key: 'Enter' }); // a second request while the first is still in flight
    await act(async () => { second.resolve(reply({ results: [item(7, 'Newest answer')], total_matches: 1 })); });
    expect(await screen.findByText('Newest answer')).toBeInTheDocument();
    await act(async () => { first.resolve(reply({ results: [item(8, 'Stale answer')], total_matches: 1 })); });
    expect(screen.queryByText('Stale answer')).not.toBeInTheDocument();
    expect(screen.getByText('Newest answer')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Search' })).toBeEnabled(); // the late reply did not leave a stuck "Searching"
  });

  it('does not let a failed earlier request replace a newer answer with an error', async () => {
    const first = deferred<ProductSearchResponse>();
    const client = { searchProducts: vi.fn().mockReturnValueOnce(first.promise).mockResolvedValueOnce(reply({ results: [item(7, 'Newest answer')], total_matches: 1 })) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    fireEvent.keyDown(box(), { key: 'Enter' });
    await screen.findByText('Newest answer');
    await act(async () => { first.reject(new Error('timeout')); });
    expect(screen.queryByRole('alert')).not.toBeInTheDocument();
    expect(screen.getByText('Newest answer')).toBeInTheDocument();
  });

  it('shows the server-supplied error text from the API body in the alert', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(reply({ results: [], total_matches: 0, error: { code: 'search_unavailable', message: 'Product search is unavailable right now.' } })) };
    render(<ProductSearch client={client} />);
    searchFor('shoes');
    expect(await screen.findByRole('alert')).toHaveTextContent('Product search is unavailable right now.');
    expect(screen.queryByRole('region', { name: 'Product results' })).not.toBeInTheDocument();
  });
});

describe('Search products: journey through App', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('crypto', { randomUUID: () => 'product-journey' });
  });

  const json = (body: unknown, status = 200) => new Response(JSON.stringify(body), { status, headers: { 'content-type': 'application/json' } });

  it('searches, pages, narrows by locale, sees a partial match, recovers from an outage, and never touches experience search', async () => {
    const calls: Array<{ url: string; body: Record<string, unknown> }> = [];
    const answers = [
      () => json(reply()),                                                              // 1. search
      () => json(reply({ page: 2, results: [item(11)] })),                                // 2. next page
      () => json(reply({ results: [item(21, 'Zapatilla roja')], total_matches: 1 })),     // 3. locale es, back to page 1
      () => json(reply({ match: 'any', results: [item(31, 'Blue boot')], total_matches: 1 })), // 4. new words, partial match
      () => json({}, 503),                                                              // 5. outage
      () => json(reply({ match: 'any', results: [item(31, 'Blue boot')], total_matches: 1 })), // 6. retry works
    ];
    vi.stubGlobal('fetch', vi.fn().mockImplementation(async (url: string, init: RequestInit) => {
      calls.push({ url, body: JSON.parse(init.body as string) });
      return answers[calls.length - 1]();
    }));
    render(<App />);
    const section = screen.getByRole('region', { name: 'Product search' });
    const find = within(section);

    fireEvent.change(find.getByRole('textbox', { name: 'Search products' }), { target: { value: 'running shoes' } });
    fireEvent.click(find.getByRole('button', { name: 'Search' }));
    expect(await find.findByText('Running shoe 1')).toBeInTheDocument();
    expect(calls[0]).toEqual({ url: '/api/discovery/v1/products/search', body: { query: 'running shoes', page: 1, page_size: 10 } });
    expect(find.getByRole('status')).toHaveTextContent('25 products');

    fireEvent.click(find.getByRole('button', { name: 'Next products page' }));
    expect(await find.findByText('Running shoe 11')).toBeInTheDocument();
    expect(find.getByText('Page 2 of 3')).toBeInTheDocument();
    expect(calls[1].body).toEqual({ query: 'running shoes', page: 2, page_size: 10 });

    fireEvent.change(find.getByRole('combobox', { name: 'Product locale' }), { target: { value: 'es' } });
    expect(await find.findByText('Zapatilla roja')).toBeInTheDocument();
    expect(calls[2].body).toEqual({ query: 'running shoes', page: 1, page_size: 10, locale: 'es' });
    expect(find.getByText('Page 1 of 1')).toBeInTheDocument();
    expect(find.getByRole('status')).toHaveTextContent(/^1 product$/);

    fireEvent.change(find.getByRole('textbox', { name: 'Search products' }), { target: { value: 'blue boots' } });
    fireEvent.keyDown(find.getByRole('textbox', { name: 'Search products' }), { key: 'Enter' });
    expect(await find.findByText('Blue boot')).toBeInTheDocument();
    expect(calls[3].body).toEqual({ query: 'blue boots', page: 1, page_size: 10, locale: 'es' });
    expect(find.getByRole('status')).toHaveTextContent('No product matched every word');

    fireEvent.click(find.getByRole('button', { name: 'Search' }));
    expect(await find.findByRole('alert')).toHaveTextContent('Product search is unavailable right now');
    fireEvent.click(find.getByRole('button', { name: 'Retry' }));
    expect(await find.findByText('Blue boot')).toBeInTheDocument();
    expect(calls).toHaveLength(6);

    // every call went to the product route; the experience search on the same page was never used
    expect(calls.every((call) => call.url.endsWith('/v1/products/search'))).toBe(true);
    expect(screen.getByRole('region', { name: 'Discovery search' })).toBeInTheDocument();
    expect(screen.getAllByText('Skybound Studio').length).toBeGreaterThan(0); // the static experience demo is untouched
  });

  it('keeps the product and experience searches separately named and operable on one page', () => {
    vi.stubGlobal('fetch', vi.fn());
    render(<App />);
    expect(screen.getByRole('textbox', { name: 'Search products' })).toBeInTheDocument();
    expect(screen.getByRole('textbox', { name: 'Search experiences' })).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled(); // products: nothing typed
    expect(screen.getByRole('button', { name: 'Explore' })).toBeEnabled(); // experiences
    expect(screen.getAllByRole('status')).toHaveLength(1); // one product live region; the experience results use their own aria-live section
    expect(fetch).not.toHaveBeenCalled(); // nothing is fetched on load
  });
});
