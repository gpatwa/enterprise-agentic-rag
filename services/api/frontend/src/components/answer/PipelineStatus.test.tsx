import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { PipelineStatus } from './PipelineStatus';

describe('PipelineStatus', () => {
  it('renders nothing while idle (no steps + not streaming)', () => {
    const { container } = render(<PipelineStatus steps={[]} streaming={false} />);
    expect(container).toBeEmptyDOMElement();
  });

  it('shows "Routing question…" placeholder while streaming with no steps', () => {
    render(<PipelineStatus steps={[]} streaming={true} />);
    expect(screen.getByText(/Routing question/i)).toBeInTheDocument();
  });

  it('renders a chip per pipeline step in order', () => {
    render(
      <PipelineStatus
        steps={[
          { node: 'planner', at: 1 },
          { node: 'data_analytics', at: 2 },
          { node: 'responder', at: 3 },
        ]}
        streaming={false}
      />
    );
    expect(screen.getByText('Plan')).toBeInTheDocument();
    expect(screen.getByText('Query data')).toBeInTheDocument();
    expect(screen.getByText('Synthesize')).toBeInTheDocument();
  });

  it('renders retry chip with destructive styling label', () => {
    render(
      <PipelineStatus
        steps={[
          { node: 'planner', at: 1 },
          { node: 'retry', at: 2 },
        ]}
        streaming={false}
      />
    );
    expect(screen.getByText('Retry')).toBeInTheDocument();
  });
});
