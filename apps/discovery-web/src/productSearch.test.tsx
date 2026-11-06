import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import type { ProductSearchResponse } from './api/client';
import { ProductSearch } from './productSearch';

const item = (n: number) => ({ product_id: `P${n}`, title: `Running shoe ${n}`, brand: 'Acme', color: 'red', snippet: `bullet ${n}`, rank: n, score: 2 });
const page = (over: Partial<ProductSearchResponse> = {}): ProductSearchResponse => ({ schema_version: 'product-search-v1', results: [item(1), item(2)], total_matches: 25, page: 1, page_size: 10, match: 'all', error: null, ...over });
const search = () => screen.getByRole('textbox', { name: 'Search products' });

describe('ProductSearch', () => {
  it('does not call the API until the user searches', () => {
    const client = { searchProducts: vi.fn() };
    render(<ProductSearch client={client} />);
    expect(client.searchProducts).not.toHaveBeenCalled();
    expect(screen.getByRole('button', { name: 'Search' })).toBeDisabled();
  });

  it('searches, shows results, and pages', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(page()) };
    render(<ProductSearch client={client} />);
    fireEvent.change(search(), { target: { value: ' shoes ' } });
    fireEvent.keyDown(search(), { key: 'Enter' });
    expect(await screen.findByText('Running shoe 1')).toBeInTheDocument();
    expect(client.searchProducts).toHaveBeenCalledWith({ query: 'shoes', page: 1, page_size: 10 });
    expect(screen.getByText('25 products')).toBeInTheDocument();
    expect(screen.getByText('Page 1 of 3')).toBeInTheDocument();
    expect(screen.getByRole('button', { name: 'Previous products page' })).toBeDisabled();
    fireEvent.click(screen.getByRole('button', { name: 'Next products page' }));
    await waitFor(() => expect(client.searchProducts).toHaveBeenLastCalledWith({ query: 'shoes', page: 2, page_size: 10 }));
  });

  it('sends the locale and returns to page 1 when it changes', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(page()) };
    render(<ProductSearch client={client} />);
    fireEvent.change(search(), { target: { value: 'shoes' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    await screen.findByText('Running shoe 1');
    fireEvent.change(screen.getByRole('combobox', { name: 'Product locale' }), { target: { value: 'es' } });
    await waitFor(() => expect(client.searchProducts).toHaveBeenLastCalledWith({ query: 'shoes', page: 1, page_size: 10, locale: 'es' }));
  });

  it('says so when only some of the words matched', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(page({ match: 'any' })) };
    render(<ProductSearch client={client} />);
    fireEvent.change(search(), { target: { value: 'red shoes' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByText(/No product matched every word/)).toBeInTheDocument();
  });

  it('shows an empty state', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValue(page({ results: [], total_matches: 0 })) };
    render(<ProductSearch client={client} />);
    fireEvent.change(search(), { target: { value: 'zzz' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByText('No products matched that search.')).toBeInTheDocument();
  });

  it('shows the API error message and a generic message when the request fails', async () => {
    const client = { searchProducts: vi.fn().mockResolvedValueOnce(page({ results: [], total_matches: 0, error: { code: 'not_configured', message: 'Product search needs the OpenSearch backend.' } })).mockRejectedValueOnce(new Error('boom')) };
    render(<ProductSearch client={client} />);
    fireEvent.change(search(), { target: { value: 'shoes' } });
    fireEvent.click(screen.getByRole('button', { name: 'Search' }));
    expect(await screen.findByRole('alert')).toHaveTextContent('needs the OpenSearch backend');
    fireEvent.click(screen.getByRole('button', { name: 'Retry' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('unavailable right now'));
    expect(screen.getByRole('alert')).not.toHaveTextContent('boom');
  });
});
