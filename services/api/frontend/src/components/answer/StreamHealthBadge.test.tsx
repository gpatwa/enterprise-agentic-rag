import { render, screen } from '@testing-library/react';
import { describe, expect, it } from 'vitest';
import { StreamHealthBadge } from './StreamHealthBadge';

describe('StreamHealthBadge', () => {
  it('shows client-observed TTFT once the first token arrives', () => {
    render(
      <StreamHealthBadge
        streaming
        lastUpdate={Date.now()}
        startedAt={Date.now() - 742}
        firstTokenMs={742}
        serverFirstTokenMs={710}
      />
    );

    expect(screen.getByRole('status')).toHaveTextContent('TTFT 742ms');
    expect(screen.getByRole('status')).toHaveTextContent('server 710ms');
  });

  it('shows a live waiting TTFT before the first token arrives', () => {
    render(
      <StreamHealthBadge
        streaming
        lastUpdate={Date.now()}
        startedAt={Date.now() - 450}
        firstTokenMs={null}
      />
    );

    expect(screen.getByRole('status')).toHaveTextContent(/TTFT \d+ms waiting/);
  });
});
