import { describe, expect, it } from 'vitest';
import { formatCount, formatRelative } from './format';

describe('formatCount', () => {
  it('returns em-dash for null/undefined', () => {
    expect(formatCount(null)).toBe('—');
    expect(formatCount(undefined)).toBe('—');
  });
  it('returns string for small numbers', () => {
    expect(formatCount(5)).toBe('5');
    expect(formatCount(999)).toBe('999');
  });
  it('formats thousands with K suffix', () => {
    expect(formatCount(1_000)).toBe('1.0K');
    expect(formatCount(2_412)).toBe('2.4K');
  });
  it('formats millions with M suffix', () => {
    expect(formatCount(1_500_000)).toBe('1.5M');
    expect(formatCount(1_550_851)).toBe('1.6M');
  });
});

describe('formatRelative', () => {
  it('returns empty string for invalid input', () => {
    expect(formatRelative(null)).toBe('');
    expect(formatRelative(undefined)).toBe('');
    expect(formatRelative('not-a-date')).toBe('');
  });
  it('returns "just now" for sub-minute differences', () => {
    expect(formatRelative(new Date().toISOString())).toBe('just now');
  });
  it('formats minutes', () => {
    const t = new Date(Date.now() - 5 * 60_000).toISOString();
    expect(formatRelative(t)).toBe('5m ago');
  });
  it('formats hours', () => {
    const t = new Date(Date.now() - 3 * 3600_000).toISOString();
    expect(formatRelative(t)).toBe('3h ago');
  });
  it('formats days', () => {
    const t = new Date(Date.now() - 2 * 86_400_000).toISOString();
    expect(formatRelative(t)).toBe('2d ago');
  });
});
