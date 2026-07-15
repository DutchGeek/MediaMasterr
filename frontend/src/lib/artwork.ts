import { BRANDING } from "$lib/branding";

const TMDB_POSTER_BASE = "https://image.tmdb.org/t/p/w342";

export function resolvePosterUrl(posterUrl: string | null | undefined): string {
  const raw = (posterUrl ?? "").trim();
  if (!raw) return BRANDING.assets.mediaPlaceholder;

  const lower = raw.toLowerCase();
  if (
    lower.startsWith("http://") ||
    lower.startsWith("https://") ||
    raw.startsWith("/branding/")
  ) {
    return raw;
  }

  const normalized = raw.startsWith("/") ? raw : `/${raw}`;
  return `${TMDB_POSTER_BASE}${normalized}`;
}
