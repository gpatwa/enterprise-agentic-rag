import { fireEvent, render, screen, waitFor } from '@testing-library/react';
import { describe, expect, it, vi } from 'vitest';
import { applyLocalFeedback, initialPersonaFeedbackState, PersonaFeedbackControls } from './personaFeedback';

describe('persona and feedback controls', () => {
  it('keeps persona, mode, consent, and demo labeling explicit', () => {
    render(<PersonaFeedbackControls />);
    expect(screen.getByLabelText('Persona')).toHaveValue('new-explorer');
    expect(screen.getByLabelText('Personalization mode')).toHaveValue('cold-start');
    expect(screen.getByLabelText('Consent state')).toHaveValue('granted');
    expect(screen.getByText('Synthetic demo')).toBeInTheDocument();
    expect(screen.getByText('Lineage: imp_skybound_01')).toBeInTheDocument();
  });

  it('submits typed local feedback and updates later requests deterministically', async () => {
    const onChange = vi.fn();
    render(<PersonaFeedbackControls onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Good fit' }));
    await waitFor(() => expect(screen.getByText('Saved. Future local requests will favor this world.')).toBeInTheDocument());
    expect(onChange).toHaveBeenCalledWith(expect.objectContaining({ mode: 'personalized', preferences: ['skybound-studio'], feedback: [expect.objectContaining({ kind: 'like', synthetic: true, impression_token: 'imp_skybound_01' })] }));
  });

  it('fails closed when consent is withdrawn and applies no preference', async () => {
    const onChange = vi.fn();
    render(<PersonaFeedbackControls state={{ ...initialPersonaFeedbackState, consent: 'withdrawn' }} onChange={onChange} />);
    fireEvent.click(screen.getByRole('button', { name: 'Not for me' }));
    expect(await screen.findByText('Feedback was not saved because consent is off.')).toBeInTheDocument();
    expect(onChange).not.toHaveBeenCalled();
    expect(applyLocalFeedback({ ...initialPersonaFeedbackState, consent: 'withdrawn' }, { kind: 'like', experience_id: 'skybound-studio', impression_token: 'imp_skybound_01', principal_id: 'synthetic-user-1', consent: 'withdrawn', synthetic: true })).toEqual({ ...initialPersonaFeedbackState, consent: 'withdrawn' });
  });
});
