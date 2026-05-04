import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import { AnswerText } from './AnswerText';

describe('AnswerText', () => {
  it('renders plain markdown', () => {
    render(<AnswerText content="**Hello** world" />);
    expect(screen.getByText('Hello')).toBeInTheDocument();
    // tagName check — bold wraps in <strong>
    expect(screen.getByText('Hello').tagName.toLowerCase()).toBe('strong');
  });

  it('extracts [Source: …] tokens into source badges', () => {
    render(
      <AnswerText content="Revenue grew 14% YoY [Source: olist_orders] [Source: payments.csv]" />
    );
    // Source tokens should not appear in the rendered prose
    expect(screen.queryByText(/\[Source:/)).toBeNull();
    // But should appear as badges
    expect(screen.getByText('olist_orders')).toBeInTheDocument();
    expect(screen.getByText('payments.csv')).toBeInTheDocument();
  });

  it('renders a streaming caret when streaming=true', () => {
    const { container } = render(<AnswerText content="partial answer" streaming />);
    const caret = container.querySelector('span.animate-pulse');
    expect(caret).not.toBeNull();
  });
});
