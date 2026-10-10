import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import App from './App';
import { createDiscoveryClient, type SearchResponse } from './api/client';
import { HomeDetailsExperience } from './homeDetails';
import { safeHomeResponse, journeySearchResponses, forbiddenResultTitles } from './imd-069-e2e-fixtures';
import { PersonaFeedbackControls } from './personaFeedback';
import { RankingInspector } from './rankingInspector';

function responseFor(response: SearchResponse) {
  return new Response(JSON.stringify(response), { status: 200, headers: { 'content-type': 'application/json' } });
}

function focusableElements(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>('button, input, select')).filter((element) => !(element as HTMLButtonElement | HTMLInputElement | HTMLSelectElement).disabled);
}

describe('IMD-069 local API/web discovery journeys', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('crypto', { randomUUID: () => 'imd-069-request' });
  });

  it('runs exact, natural-language, filtered, and no-result search journeys deterministically', async () => {
    const fetchMock = vi.fn()
      .mockResolvedValueOnce(responseFor(journeySearchResponses.exact))
      .mockResolvedValueOnce(responseFor(journeySearchResponses.natural))
      .mockResolvedValueOnce(responseFor(journeySearchResponses.noResult));
    vi.stubGlobal('fetch', fetchMock);
    render(<App />);

    const search = screen.getByRole('textbox', { name: 'Search experiences' });
    fireEvent.change(search, { target: { value: 'Skybound Studio' } });
    fireEvent.keyDown(search, { key: 'Enter' });
    await waitFor(() => expect(screen.getByText('Skybound Studio')).toBeInTheDocument());
    expect(screen.getByText('exact id match')).toBeInTheDocument();

    fireEvent.change(search, { target: { value: 'a calm world to build with friends' } });
    fireEvent.change(screen.getByRole('combobox', { name: 'Device' }), { target: { value: 'mobile' } });
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
    await waitFor(() => expect(screen.getByText('Tiny Town Builders')).toBeInTheDocument());
    const naturalRequest = JSON.parse(fetchMock.mock.calls[1][1].body as string);
    expect(naturalRequest.query).toBe('a calm world to build with friends');
    expect(naturalRequest.context.device).toBe('mobile');

    fireEvent.change(search, { target: { value: 'does not exist locally' } });
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
    await waitFor(() => expect(screen.getByText('No worlds matched that search.')).toBeInTheDocument());
    expect(fetchMock).toHaveBeenCalledTimes(3);
    expect(journeySearchResponses.natural.results.length).toBeLessThanOrEqual(6);
    expect(journeySearchResponses.natural.schema_version).toBe('imd-search-v1');
  });

  it('enforces tenant, blocked, and unsafe exclusion at the typed API boundary', async () => {
    const safeResponse = { ...journeySearchResponses.safeFallback, results: journeySearchResponses.safeFallback.results.filter((item) => !forbiddenResultTitles.includes(item.title)) };
    const fetchMock = vi.fn().mockResolvedValue(responseFor(safeResponse));
    vi.stubGlobal('fetch', fetchMock);
    const client = createDiscoveryClient('http://local.test');
    const result = await client.search({
      query: 'adventure', blocked_ids: ['unsafe-combat-test'], page: 1, page_size: 6,
      context: { tenant_id: 'demo', principal_id: 'synthetic-user-1', request_id: 'imd-069-policy', locale: 'en-US', device: 'web', age_band: 'teen', purpose: 'search' },
    });

    const request = JSON.parse(fetchMock.mock.calls[0][1].body as string);
    expect(request.context.tenant_id).toBe('demo');
    expect(request.blocked_ids).toEqual(['unsafe-combat-test']);
    expect(result.results.every((item) => !forbiddenResultTitles.includes(item.title))).toBe(true);
    expect(result.results).toHaveLength(1);
    expect(result.fallback).toBe(true);
    expect(result.results[0].evidence).not.toContain('private-vector');
  });

  it('covers no-history consent, persona switch, typed feedback adaptation, and lineage', async () => {
    const { unmount } = render(<HomeDetailsExperience response={safeHomeResponse} />);
    expect(screen.getByRole('region', { name: 'Personalized home feed' })).toHaveTextContent('Personalization is off');
    expect(screen.getByRole('region', { name: 'Personalized home feed' })).toHaveTextContent('safe catalog fallback');
    fireEvent.click(screen.getByRole('button', { name: 'Open Skybound Studio' }));
    expect(screen.getByText(/Lineage: detail_imp_skybound_01/)).toBeInTheDocument();
    expect(screen.getByText('All featured content is fictional local demo data.')).toBeInTheDocument();
    unmount();

    const changes: Array<{ preferences: string[] }> = [];
    render(<PersonaFeedbackControls onChange={(state) => changes.push(state)} />);
    fireEvent.change(screen.getByRole('combobox', { name: 'Persona' }), { target: { value: 'social-builder' } });
    expect(screen.getByText('Persona: Social builder')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Good fit' }));
    const feedbackRegion = screen.getByRole('region', { name: 'Persona and feedback controls' });
    await waitFor(() => expect(feedbackRegion.querySelector('.notice')).toHaveTextContent('Future local requests will favor this world.'));
    expect(changes.at(-1)?.preferences).toEqual(['skybound-studio']);
    expect(screen.getByText('Lineage: imp_skybound_01')).toBeInTheDocument();
  });

  it('falls back after provider failure and keeps explanations redacted and keyboard reachable', async () => {
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('local provider unavailable')));
    const { container } = render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Search is unavailable'));

    const { unmount } = render(<RankingInspector />);
    const inspector = screen.getByRole('region', { name: 'Ranking inspector' });
    fireEvent.change(within(inspector).getByRole('combobox', { name: 'Ranking mode' }), { target: { value: 'full-rank' } });
    expect(within(inspector).getByText('full-rank-v1')).toBeInTheDocument();
    expect(within(inspector).getByText('Fallback active')).toBeInTheDocument();
    expect(within(inspector).queryByText('private-vector')).not.toBeInTheDocument();
    expect(focusableElements(container).length).toBeGreaterThan(10);
    focusableElements(container).forEach((element) => { element.focus(); expect(document.activeElement).toBe(element); });
    unmount();
  });
});
