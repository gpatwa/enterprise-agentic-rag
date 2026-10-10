import { fireEvent, render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { RankingInspector } from './rankingInspector';

describe('ranking inspector', () => {
  it('compares a governed mode with metrics, stages, and redacted evidence', () => {
    render(<RankingInspector />);
    expect(screen.getByRole('region', { name: 'Ranking inspector' })).toBeInTheDocument();
    expect(screen.getByText('hybrid-v1')).toBeInTheDocument();
    expect(screen.getByText('RRF fusion')).toBeInTheDocument();
    expect(screen.getAllByText('fused-signal')).toHaveLength(2);
    expect(screen.getByText(/Private features, raw queries, vectors/)).toBeInTheDocument();
  });

  it('switches modes and exposes fallback state without private internals', () => {
    render(<RankingInspector />);
    fireEvent.change(screen.getByLabelText('Ranking mode'), { target: { value: 'full-rank' } });
    expect(screen.getByText('full-rank-v1')).toBeInTheDocument();
    expect(screen.getByText('Fallback active')).toBeInTheDocument();
    expect(screen.getAllByText('ranker unavailable; safe ordering')).toHaveLength(2);
    expect(screen.queryByText('raw-query')).not.toBeInTheDocument();
    expect(screen.queryByText('private-vector')).not.toBeInTheDocument();
  });
});
