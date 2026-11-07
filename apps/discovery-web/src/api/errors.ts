/** Why sign-in could not produce a token. Never carries token content or provider error text. */
export type AuthRequiredReason = 'signin_required' | 'redirect_error' | 'no_access' | 'interaction_in_progress';
export type AuthFailure = 'expired' | 'no-access';

/** Thrown by the token source when a person has to act (or has no access) instead of the app retrying. */
export class AuthRequiredError extends Error {
  readonly reason: AuthRequiredReason;
  constructor(reason: AuthRequiredReason) {
    super(`Sign-in required (${reason})`);
    this.name = 'AuthRequiredError';
    this.reason = reason;
  }
}

/** A non-success answer from the API. The status is for logic and logs; it is never shown to people. */
export class DiscoveryApiError extends Error {
  readonly status: number;
  constructor(message: string, status: number) {
    super(message);
    this.name = 'DiscoveryApiError';
    this.status = status;
  }
}

/** Maps any error to a designed auth state, or null when it is an ordinary failure (the API is down, bad input). */
export function authFailureOf(error: unknown): AuthFailure | null {
  if (error instanceof DiscoveryApiError) return error.status === 401 ? 'expired' : error.status === 403 ? 'no-access' : null;
  if (error instanceof AuthRequiredError) return error.reason === 'no_access' ? 'no-access' : 'expired';
  return null;
}
