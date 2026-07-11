/**
 * @param {unknown} value
 */
export function asDisplayValue(value) {
  if (value === null || value === undefined) return "Unknown";
  const trimmed = String(value).trim();
  return trimmed.length > 0 ? trimmed : "Unknown";
}

/**
 * @param {"known" | "unknown"} status
 */
export function nodeBadgeClass(status) {
  return status === "known"
    ? "bg-emerald-500/20 text-emerald-700 dark:text-emerald-300"
    : "bg-muted text-muted-foreground";
}
