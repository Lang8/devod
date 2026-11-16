import * as Sentry from "@sentry/react";

/** Initialise Sentry only when VITE_SENTRY_DSN is set; otherwise a no-op. Returns true when enabled. */
export function initSentry(dsn = import.meta.env.VITE_SENTRY_DSN) {
  if (!dsn || !String(dsn).trim()) return false;
  Sentry.init({ dsn: String(dsn).trim(), environment: import.meta.env.MODE, tracesSampleRate: 0 });
  return true;
}
