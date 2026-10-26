// Where the marketing site sends people. Product apps are separate deployables.
const env = (import.meta as unknown as { env?: Record<string, string | undefined> }).env ?? {};

/** The analytics product app (pilot: paste an access token). */
export const APP_URL = env.VITE_APP_URL ?? 'https://white-coast-0195be70f.2.azurestaticapps.net';
/** Where pilot requests go. */
export const PILOT_MAILTO =
  env.VITE_PILOT_MAILTO ?? 'mailto:demo@kavachiq.com?subject=Compass%20pilot%20request';
export const SITE_URL = env.VITE_SITE_URL ?? 'https://compass.example.com';
