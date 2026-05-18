import { useEffect, useState } from "react";
import { api } from "@/api/client";

/**
 * Singleton hook for the four login-page branding fields plus the SMTP-configured
 * flag (drives whether to show the "Forgot password?" link).
 *
 * Values are primed from `/settings/bootstrap` by `primeBootstrap()` immediately
 * after auth — but the login page is unauthenticated, so we also fall back to
 * fetching the same public bootstrap endpoint directly on cache miss.
 *
 * Follows the inflight-promise pattern from `useAppTitle` so concurrent mounts
 * in the same tick share a single network request.
 */

export interface LoginBranding {
  tagline: string;
  taglineHidden: boolean;
  helpText: string;
  helpLink: string;
  smtpConfigured: boolean;
}

const DEFAULT: LoginBranding = {
  tagline: "",
  taglineHidden: false,
  helpText: "",
  helpLink: "",
  smtpConfigured: false,
};

let _cache: LoginBranding | null = null;
let _inflight: Promise<void> | null = null;
const _listeners = new Set<(b: LoginBranding) => void>();

interface BootstrapShape {
  login_tagline?: string;
  login_tagline_hidden?: boolean;
  login_help_text?: string;
  login_help_link?: string;
  smtp_configured?: boolean;
}

function fromBootstrap(r: BootstrapShape): LoginBranding {
  return {
    tagline: (r.login_tagline || "").trim(),
    taglineHidden: Boolean(r.login_tagline_hidden),
    helpText: (r.login_help_text || "").trim(),
    helpLink: (r.login_help_link || "").trim(),
    smtpConfigured: Boolean(r.smtp_configured),
  };
}

function notify(value: LoginBranding) {
  _cache = value;
  for (const fn of _listeners) fn(value);
}

function loadOnce() {
  if (_cache !== null) return;
  if (_inflight) return;
  _inflight = api
    .get<BootstrapShape>("/settings/bootstrap")
    .then((r) => {
      notify(fromBootstrap(r));
    })
    .catch(() => {
      // Best-effort — leave defaults in place.
      notify(DEFAULT);
    })
    .finally(() => {
      _inflight = null;
    });
}

export function useLoginBranding(): LoginBranding {
  const [value, setValue] = useState<LoginBranding>(_cache || DEFAULT);

  useEffect(() => {
    _listeners.add(setValue);
    loadOnce();
    return () => {
      _listeners.delete(setValue);
    };
  }, []);

  return value;
}

/** Broadcast a freshly saved login-branding value to all mounted consumers. */
export function invalidateLoginBranding(value: Partial<LoginBranding>): void {
  const base = _cache || DEFAULT;
  notify({
    tagline: (value.tagline ?? base.tagline).trim(),
    taglineHidden: value.taglineHidden ?? base.taglineHidden,
    helpText: (value.helpText ?? base.helpText).trim(),
    helpLink: (value.helpLink ?? base.helpLink).trim(),
    smtpConfigured: value.smtpConfigured ?? base.smtpConfigured,
  });
}

/** Reset for tests. */
export function _resetLoginBrandingCache(): void {
  _cache = null;
  _inflight = null;
}

/**
 * Normalize a user-entered contact link.
 *
 * - Empty → empty.
 * - Already has a URL scheme (`https://`, `mailto:`, `tel:`, etc.) → returned as-is.
 * - Looks like a bare email (contains `@` but no scheme) → prepended with `mailto:`.
 * - Anything else → returned as-is so the browser can decide what to do.
 */
export function normalizeContactLink(raw: string): string {
  const trimmed = (raw || "").trim();
  if (!trimmed) return "";
  if (/^[a-z][a-z0-9+.-]*:/i.test(trimmed)) return trimmed;
  if (/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(trimmed)) return `mailto:${trimmed}`;
  return trimmed;
}
