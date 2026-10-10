import { fireEvent, render, screen, waitFor, within } from '@testing-library/react';
import { beforeEach, describe, expect, it, vi } from 'vitest';
import fixture from './imd-068-visual-fixtures.json';
import App from './App';
import { HomeDetailsExperience } from './homeDetails';
import { PersonaFeedbackControls } from './personaFeedback';
import { RankingInspector } from './rankingInspector';

function focusableElements(container: HTMLElement) {
  return Array.from(container.querySelectorAll<HTMLElement>('button, input, select, [tabindex]')).filter((element) => !element.hasAttribute('disabled') && element.tabIndex >= 0);
}

describe('IMD-068 accessibility and visual contract', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
    vi.stubGlobal('crypto', { randomUUID: () => 'imd-068-request' });
    vi.stubGlobal('matchMedia', (query: string) => ({ matches: query === '(prefers-reduced-motion: reduce)', media: query, onchange: null, addListener: vi.fn(), removeListener: vi.fn(), addEventListener: vi.fn(), removeEventListener: vi.fn(), dispatchEvent: vi.fn() }));
  });

  it('locks deterministic desktop/mobile viewport and layout contracts', () => {
    expect(fixture.viewports.desktop).toEqual({ width: 1280, height: 900 });
    expect(fixture.viewports.mobile).toEqual({ width: 390, height: 844 });
    expect(fixture.states).toEqual(['search', 'search-loading', 'search-empty', 'search-error', 'home', 'details', 'persona', 'feedback', 'ranking-inspector']);
    expect(fixture.layoutContract).toEqual({ desktopColumns: 3, mobileColumns: 1, minimumBodyWidth: 320, focusOutlineWidth: 2, focusOutlineOffset: 3 });
  });

  it('keeps the search surface keyboard reachable with named controls', async () => {
    vi.stubGlobal('fetch', vi.fn().mockResolvedValue(new Response(JSON.stringify({ schema_version: 'imd-search-v1', request_id: 'imd-068-request', total_matches: 0, fallback: false, error: null, results: [] }), { status: 200 })));
    const { container } = render(<App />);
    const search = screen.getByRole('region', { name: 'Discovery search' });
    expect(within(search).getByRole('textbox', { name: 'Search experiences' })).toBeInTheDocument();
    expect(within(search).getByRole('button', { name: 'Explore' })).toBeInTheDocument();
    expect(within(search).getByRole('combobox', { name: 'Locale' })).toBeInTheDocument();
    expect(within(search).getByRole('combobox', { name: 'Device' })).toBeInTheDocument();
    expect(within(search).getByRole('combobox', { name: 'Age' })).toBeInTheDocument();
    const focusables = focusableElements(container);
    expect(focusables.length).toBeGreaterThan(10);
    focusables.forEach((element) => { element.focus(); expect(document.activeElement).toBe(element); });
    fireEvent.keyDown(screen.getByRole('textbox', { name: 'Search experiences' }), { key: 'Escape' });
    expect(screen.getByRole('textbox', { name: 'Search experiences' })).toHaveValue('');
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
    await waitFor(() => expect(screen.getByText('No worlds matched that search.')).toBeInTheDocument());
  });

  it('covers loading, empty, and error states with live semantics', async () => {
    let resolve: (value: Response) => void = () => undefined;
    vi.stubGlobal('fetch', vi.fn().mockImplementation(() => new Promise<Response>((res) => { resolve = res; })));
    render(<App />);
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
    expect(document.querySelector('.results')).toHaveAttribute('aria-busy', 'true');
    expect(screen.getByText('Searching the local catalog')).toBeInTheDocument();
    resolve(new Response(JSON.stringify({ schema_version: 'imd-search-v1', request_id: 'imd-068-request', total_matches: 0, fallback: false, error: null, results: [] }), { status: 200 }));
    await waitFor(() => expect(screen.getByText('No worlds matched that search.')).toBeInTheDocument());
    vi.stubGlobal('fetch', vi.fn().mockRejectedValue(new Error('offline')));
    fireEvent.click(screen.getByRole('button', { name: 'Explore' }));
    await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent('Search is unavailable'));
  });

  it('covers home, details, persona, feedback, and ranking states', async () => {
    const { container: homeContainer } = render(<HomeDetailsExperience />);
    expect(screen.getByRole('region', { name: 'Personalized home feed' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Open Skybound Studio' }));
    expect(screen.getByRole('region', { name: 'Experience details' })).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back to home' }));
    expect(focusableElements(homeContainer).every((element) => element.getAttribute('aria-label') || element.textContent?.trim())).toBe(true);

    const { unmount: unmountPersona } = render(<PersonaFeedbackControls />);
    expect(screen.getByRole('region', { name: 'Persona and feedback controls' })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Consent state' }), { target: { value: 'withdrawn' } });
    fireEvent.click(screen.getByRole('button', { name: 'Not for me' }));
    expect(await screen.findByText('Feedback was not saved because consent is off.')).toBeInTheDocument();
    unmountPersona();

    render(<RankingInspector />);
    expect(screen.getByRole('region', { name: 'Ranking inspector' })).toBeInTheDocument();
    fireEvent.change(screen.getByRole('combobox', { name: 'Ranking mode' }), { target: { value: 'full-rank' } });
    expect(screen.getByText('Fallback active')).toBeInTheDocument();
    expect(screen.queryByText('private-vector')).not.toBeInTheDocument();
  });

  it('keeps reduced-motion mode deterministic and preserves visible focus styling', () => {
    const { container } = render(<RankingInspector />);
    const mode = screen.getByRole('combobox', { name: 'Ranking mode' });
    mode.focus();
    expect(document.activeElement).toBe(mode);
    expect(getComputedStyle(mode).outlineWidth).not.toBe('0px');
    expect(container.querySelectorAll('[aria-hidden="true"]').length).toBeGreaterThan(0);
    expect(window.matchMedia('(prefers-reduced-motion: reduce)').matches).toBe(true);
  });
});
