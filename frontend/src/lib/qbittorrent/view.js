/**
 * @param {number} seconds
 */
export function formatTorrentEta(seconds) {
  if (seconds < 0) return "∞";
  if (!Number.isFinite(seconds)) return "—";
  if (seconds === 0) return "Done";

  const hours = Math.floor(seconds / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  if (hours > 0) return `${hours}h ${minutes}m`;
  return `${minutes}m`;
}

/**
 * @param {number} value
 */
export function formatTorrentProgress(value) {
  return `${Math.round((value || 0) * 100)}%`;
}
