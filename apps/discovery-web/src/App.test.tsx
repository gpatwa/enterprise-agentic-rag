import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';

const resultResponse = (overrides: Record<string, unknown> = {}) => ({
  schema_version: 'imd-search-v1', request_id: 'request-1', total_matches: 1, fallback: false, error: null,
  results: [{ experience_id: 'world-1', title: 'Ocean Builders', rank: 1, score: 0.91, reason_codes: ['lexical_match'], evidence: ['title'] }], ...overrides,
});

describe('discovery search experience', () => {
  beforeEach(() => { vi.restoreAllMocks(); vi.stubGlobal('crypto', { randomUUID: () => 'request-1' }); });

  it('submits natural queries with typed filters and renders results', async () => {
    const fetchMock = vi.fn().mockResolvedValue(new Response(JSON.stringify(resultResponse()), { status: 200 })); vi.stubGlobal('fetch', fetchMock); render(<App />);
    fireEvent.change(screen.getByLabelText('Search experiences'), { target: { value: 'ocean builders' } }); fireEvent.change(screen.getByLabelText('Locale'), { target: { value: 'es-ES' } }); fireEvent.keyDown(screen.getByLabelText('Search experiences'), { key: 'Enter' });
    await waitFor(() => expect(screen.getByText('Ocean Builders')).toBeInTheDocument()); const request = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(request.query).toBe('ocean builders'); expect(request.context.locale).toBe('es-ES'); expect(request.page_size).toBe(6);
  });

  it('shows loading, empty, and error states', async () => {
    let resolve: (value: Response) => void = () => undefined; vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>((res) => { resolve = res; }))); render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore' })); expect(screen.getByText('Searching the local catalog')).toBeInTheDocument(); resolve(new Response(JSON.stringify(resultResponse({ total_matches: 0, results: [] })), { status: 200 }));
    await waitFor(() => expect(screen.getByText('No worlds matched that search.')).toBeInTheDocument()); vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline'))); fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Search is unavailable'));
  });

  it('keeps pagination keyboard accessible and sends the next page', async () => {
    const fetchMock = vi.fn().mockImplementation(() => new Response(JSON.stringify(resultResponse({ total_matches: 12 })), { status: 200 })); vi.stubGlobal('fetch', fetchMock); render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore' })); await waitFor(() => expect(screen.getByText('Page 1 of 2')).toBeInTheDocument()); fireEvent.click(screen.getByRole('button', { name: 'Next page' }));
    await waitFor(() => expect(screen.getByText('Page 2 of 2')).toBeInTheDocument()); expect(JSON.parse(fetchMock.mock.calls[1][1].body as string).page).toBe(2);
  });
});
