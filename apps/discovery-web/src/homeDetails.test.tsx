import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { HomeDetailsExperience, noHistoryHomeResponse } from './homeDetails';

describe('home and details experience', () => {
  it('renders typed home results with source diversity and safe metadata', () => {
    render(<HomeDetailsExperience />);
    expect(screen.getByRole('region', { name: 'Personalized home feed' })).toBeInTheDocument();
    expect(screen.getByText('3 sources represented')).toBeInTheDocument();
    expect(screen.getByText(/Northstar Collective/)).toBeInTheDocument();
    expect(screen.getAllByText('Approved').length).toBeGreaterThan(0);
  });

  it('opens details and preserves redacted impression lineage', () => {
    render(<HomeDetailsExperience />);
    fireEvent.click(screen.getByRole('button', { name: 'Open Skybound Studio' }));
    expect(screen.getByRole('region', { name: 'Experience details' })).toBeInTheDocument();
    expect(screen.getByText('Skybound Studio')).toBeInTheDocument();
    expect(screen.getByText('Lineage: detail_imp_skybound_01')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: 'Back to home' }));
    expect(screen.getByRole('region', { name: 'Personalized home feed' })).toBeInTheDocument();
  });

  it('shows the no-personalization fallback state without private features', () => {
    render(<HomeDetailsExperience response={noHistoryHomeResponse} />);
    expect(screen.getByText('A good place to begin.')).toBeInTheDocument();
    expect(screen.getByText('Safe catalog')).toBeInTheDocument();
    expect(screen.getAllByText('A safe catalog pick for a fresh start')).toHaveLength(3);
    expect(screen.queryByText('Made for your next session.')).not.toBeInTheDocument();
  });
});
