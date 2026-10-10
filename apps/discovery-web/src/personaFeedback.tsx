import { Check, CircleAlert, FlaskConical, MessageSquare, ShieldCheck, UserRound } from 'lucide-react';
import { useMemo, useState } from 'react';

export type PersonaId = 'new-explorer' | 'social-builder' | 'solo-creator';
export type PersonalizationMode = 'personalized' | 'cold-start';
export type ConsentState = 'granted' | 'withdrawn';
export type FeedbackKind = 'like' | 'not-for-me';

export type LocalFeedback = {
  kind: FeedbackKind;
  experience_id: string;
  impression_token: string;
  principal_id: string;
  consent: ConsentState;
  synthetic: true;
};

export type PersonaFeedbackState = {
  persona: PersonaId;
  mode: PersonalizationMode;
  consent: ConsentState;
  preferences: string[];
  feedback: LocalFeedback[];
};

export const personaLabels: Record<PersonaId, string> = {
  'new-explorer': 'New explorer',
  'social-builder': 'Social builder',
  'solo-creator': 'Solo creator',
};

export const initialPersonaFeedbackState: PersonaFeedbackState = {
  persona: 'new-explorer', mode: 'cold-start', consent: 'granted', preferences: [], feedback: [],
};

export function applyLocalFeedback(state: PersonaFeedbackState, feedback: LocalFeedback): PersonaFeedbackState {
  if (state.consent !== 'granted' || feedback.consent !== 'granted') return state;
  const nextFeedback = [...state.feedback.filter((item) => item.experience_id !== feedback.experience_id), feedback];
  const preference = feedback.kind === 'like' ? feedback.experience_id : `avoid:${feedback.experience_id}`;
  return { ...state, mode: 'personalized', feedback: nextFeedback, preferences: [...state.preferences.filter((item) => !item.endsWith(feedback.experience_id)), preference] };
}

type PersonaFeedbackProps = {
  state?: PersonaFeedbackState;
  onChange?: (state: PersonaFeedbackState) => void;
};

export function PersonaFeedbackControls({ state = initialPersonaFeedbackState, onChange }: PersonaFeedbackProps) {
  const [current, setCurrent] = useState(state);
  const [feedbackStatus, setFeedbackStatus] = useState<'idle' | 'pending' | 'success' | 'error'>('idle');
  const [lastFeedback, setLastFeedback] = useState<FeedbackKind | null>(null);

  function update(next: PersonaFeedbackState) { setCurrent(next); onChange?.(next); }
  function submitFeedback(kind: FeedbackKind) {
    setFeedbackStatus('pending'); setLastFeedback(kind);
    const feedback: LocalFeedback = { kind, experience_id: 'skybound-studio', impression_token: 'imp_skybound_01', principal_id: 'synthetic-user-1', consent: current.consent, synthetic: true };
    if (current.consent !== 'granted') { setFeedbackStatus('error'); return; }
    const next = applyLocalFeedback(current, feedback);
    window.setTimeout(() => { update(next); setFeedbackStatus('success'); }, 80);
  }

  const statusMessage = useMemo(() => {
    if (feedbackStatus === 'pending') return 'Saving feedback locally...';
    if (feedbackStatus === 'success') return `Saved. Future local requests will ${lastFeedback === 'like' ? 'favor' : 'avoid'} this world.`;
    if (feedbackStatus === 'error') return 'Feedback was not saved because consent is off.';
    return 'Feedback is local to this synthetic demo user.';
  }, [feedbackStatus, lastFeedback]);

  return <section className="search-panel" aria-label="Persona and feedback controls">
    <div className="home-heading"><div><p className="eyebrow">DEMO CONTEXT</p><h2>Choose how discovery should feel</h2><p>Persona and personalization are explicit. No private identity is inferred.</p></div><span className="home-status"><FlaskConical size={15} aria-hidden="true" /> Synthetic demo</span></div>
    <div className="filter-row">
      <label><UserRound size={15} aria-hidden="true" /> Persona<select aria-label="Persona" value={current.persona} onChange={(event) => update({ ...current, persona: event.target.value as PersonaId })}>{Object.entries(personaLabels).map(([value, label]) => <option key={value} value={value}>{label}</option>)}</select></label>
      <label>Mode<select aria-label="Personalization mode" value={current.mode} onChange={(event) => update({ ...current, mode: event.target.value as PersonalizationMode })}><option value="cold-start">Cold start</option><option value="personalized">Personalized</option></select></label>
      <label><ShieldCheck size={15} aria-hidden="true" /> Consent<select aria-label="Consent state" value={current.consent} onChange={(event) => update({ ...current, consent: event.target.value as ConsentState })}><option value="granted">Granted</option><option value="withdrawn">Withdrawn</option></select></label>
    </div>
    <div className="chips"><span>{current.mode === 'cold-start' ? 'Cold-start catalog' : `${current.preferences.length} local preference${current.preferences.length === 1 ? '' : 's'}`}</span><span>Consent: {current.consent}</span><span>Persona: {personaLabels[current.persona]}</span></div>
    <div className="notice" aria-live="polite"><MessageSquare size={16} aria-hidden="true" /><span>{statusMessage}</span>{feedbackStatus === 'success' && <Check size={16} aria-label="Feedback saved" />}{feedbackStatus === 'error' && <CircleAlert size={16} aria-label="Feedback not saved" />}</div>
    <div className="filter-row" aria-label="Local feedback for Skybound Studio"><span className="filter-label">Skybound Studio</span><button type="button" onClick={() => submitFeedback('like')} disabled={feedbackStatus === 'pending'}>Good fit</button><button type="button" onClick={() => submitFeedback('not-for-me')} disabled={feedbackStatus === 'pending'}>Not for me</button><small>Lineage: imp_skybound_01</small></div>
  </section>;
}
