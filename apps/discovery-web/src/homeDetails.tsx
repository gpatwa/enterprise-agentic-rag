import { ArrowLeft, Bookmark, CircleAlert, Compass, Play, ShieldCheck, Sparkles, Users } from 'lucide-react';
import { useState } from 'react';

export type HomeExperience = {
  experience_id: string;
  title: string;
  description: string;
  creator: string;
  genres: string[];
  age_rating: string;
  safety: string;
  source: string;
  reason: string;
  score: number;
  impression_token: string;
  accent: string;
  players: string;
  generated_intro: string;
};

export type HomeResponse = {
  schema_version: 'imd-home-v1';
  persona: string;
  personalization_allowed: boolean;
  fallback: boolean;
  sources: string[];
  reasons: string[];
  impression_token: string;
  results: HomeExperience[];
};

export type ExperienceDetails = HomeExperience & {
  active_players: string;
  session_length: string;
  content_note: string;
  generated_description: string;
  detail_impression_token: string;
};

export const demoHomeResponse: HomeResponse = {
  schema_version: 'imd-home-v1',
  persona: 'explicit-preference',
  personalization_allowed: true,
  fallback: false,
  sources: ['personalized', 'trending', 'similarity'],
  reasons: ['preference_match', 'quality', 'creator_diversity'],
  impression_token: 'imp_demo_home_7f3a',
  results: [
    {
      experience_id: 'skybound-studio', title: 'Skybound Studio',
      description: 'Build a floating workshop above a living cloud city.', creator: 'Northstar Collective',
      genres: ['Building', 'Co-play'], age_rating: 'E10', safety: 'Approved', source: 'personalized',
      reason: 'Because you explore creative building worlds', score: 0.96, impression_token: 'imp_skybound_01',
      accent: 'mint', players: '1-8 players', generated_intro: 'A bright, open-ended maker world for curious crews.',
    },
    {
      experience_id: 'reef-runners', title: 'Reef Runners',
      description: 'Race solar skiffs through a shifting coral maze.', creator: 'Blue Current',
      genres: ['Racing', 'Adventure'], age_rating: 'E', safety: 'Approved', source: 'trending',
      reason: 'Rising with players in your region', score: 0.84, impression_token: 'imp_reef_02',
      accent: 'coral', players: '2-12 players', generated_intro: 'Fast, friendly races with a new route every round.',
    },
    {
      experience_id: 'tiny-town', title: 'Tiny Town Builders',
      description: 'Shape a cozy riverside town one thoughtful street at a time.', creator: 'Moss & Main',
      genres: ['Simulation', 'Building'], age_rating: 'E', safety: 'Approved', source: 'similarity',
      reason: 'Similar to worlds you enjoyed', score: 0.79, impression_token: 'imp_tiny_03',
      accent: 'violet', players: '1-4 players', generated_intro: 'A gentle town sandbox where every small choice matters.',
    },
  ],
};

export const noHistoryHomeResponse: HomeResponse = {
  ...demoHomeResponse,
  persona: 'no-personalization',
  personalization_allowed: false,
  fallback: true,
  sources: ['safe_catalog_fallback'],
  reasons: ['no_history', 'safe_catalog_fallback'],
  results: demoHomeResponse.results.map((item) => ({ ...item, source: 'safe_catalog_fallback', reason: 'A safe catalog pick for a fresh start' })),
};

function detailsFor(experience: HomeExperience): ExperienceDetails {
  return {
    ...experience,
    active_players: experience.players.replace('players', 'playing now'),
    session_length: experience.experience_id === 'reef-runners' ? '10-15 minutes' : '20-30 minutes',
    content_note: 'All featured content is fictional local demo data.',
    generated_description: `${experience.generated_intro} ${experience.description} Meet other players at your own pace, with safety rules applied before this world appears.`,
    detail_impression_token: `detail_${experience.impression_token}`,
  };
}

function reasonLabel(value: string) { return value.replaceAll('_', ' '); }

type HomeDetailsProps = { response?: HomeResponse };

export function HomeDetailsExperience({ response = demoHomeResponse }: HomeDetailsProps) {
  const [selected, setSelected] = useState<HomeExperience | null>(null);
  const [saved, setSaved] = useState<string[]>([]);

  if (selected) {
    const detail = detailsFor(selected);
    return <section className="experience-details" aria-label="Experience details">
      <button className="back-button" type="button" onClick={() => setSelected(null)}><ArrowLeft size={17} aria-hidden="true" /> Back to home</button>
      <div className={`detail-art ${detail.accent}`}><span>{detail.title.slice(0, 1)}</span><small>LOCAL FICTIONAL PREVIEW</small></div>
      <div className="detail-heading"><div><p className="eyebrow">EXPERIENCE DETAILS</p><h2>{detail.title}</h2><p className="detail-creator">By {detail.creator}</p></div><button className="save-button" type="button" aria-pressed={saved.includes(detail.experience_id)} onClick={() => setSaved((current) => current.includes(detail.experience_id) ? current.filter((id) => id !== detail.experience_id) : [...current, detail.experience_id])}><Bookmark size={17} aria-hidden="true" /> {saved.includes(detail.experience_id) ? 'Saved' : 'Save'}</button></div>
      <p className="detail-description">{detail.generated_description}</p>
      <div className="metadata-row"><span><Users size={15} aria-hidden="true" /> {detail.players}</span><span><Play size={15} aria-hidden="true" /> {detail.session_length}</span><span><ShieldCheck size={15} aria-hidden="true" /> {detail.age_rating} · {detail.safety}</span></div>
      <div className="detail-columns"><section><p className="eyebrow">WHY THIS WORLD</p><p className="reason-line"><Sparkles size={16} aria-hidden="true" /> {detail.reason}</p><div className="tag-list">{detail.genres.map((genre) => <span key={genre}>{genre}</span>)}</div></section><aside className="provenance"><p className="eyebrow">TRUST SIGNALS</p><p>Source: <strong>{reasonLabel(detail.source)}</strong></p><p>Safety and age checks passed before ranking.</p><p className="lineage">Lineage: {detail.detail_impression_token}</p></aside></div>
      <p className="demo-note"><CircleAlert size={15} aria-hidden="true" /> {detail.content_note}</p>
    </section>;
  }

  return <section className="home-feed" aria-label="Personalized home feed">
    <div className="home-heading"><div><p className="eyebrow">YOUR HOME FEED</p><h2>{response.fallback ? 'A good place to begin.' : 'Made for your next session.'}</h2><p>{response.fallback ? 'Personalization is off, so these picks come from the safe catalog.' : 'A varied set of worlds selected with your preferences and policy context.'}</p></div><span className="home-status"><Compass size={15} aria-hidden="true" /> {response.fallback ? 'Safe catalog' : 'Personalized'}</span></div>
    <div className="feed-signal"><span><Sparkles size={14} aria-hidden="true" /> {response.reasons.map(reasonLabel).join(' · ')}</span><span>{response.sources.length} sources represented</span></div>
    <div className="home-grid">{response.results.map((item) => <article className="home-card" key={item.experience_id}><button className={`home-art ${item.accent}`} type="button" onClick={() => setSelected(item)} aria-label={`Open ${item.title}`}><span>{item.title.slice(0, 1)}</span><small>{item.source}</small></button><div className="home-card-copy"><div className="card-title"><div><h3>{item.title}</h3><p>By {item.creator}</p></div><span className="score">{Math.round(item.score * 100)}%</span></div><p className="card-description">{item.description}</p><div className="tag-list">{item.genres.map((genre) => <span key={genre}>{genre}</span>)}<span>{item.age_rating}</span><span>{item.safety}</span></div><p className="card-reason"><Sparkles size={13} aria-hidden="true" /> {item.reason}</p><button className="text-action" type="button" onClick={() => setSelected(item)}>View details <ArrowLeft size={14} aria-hidden="true" /></button></div></article>)}</div>
  </section>;
}
