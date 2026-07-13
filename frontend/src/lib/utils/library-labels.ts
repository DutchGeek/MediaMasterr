const titleCaseWord = (word: string): string => {
  if (!word) return "";
  if (word.length <= 2) return word.toUpperCase();
  return word.charAt(0).toUpperCase() + word.slice(1).toLowerCase();
};

const titleCaseSegment = (segment: string): string =>
  segment
    .split(/[\s_-]+/)
    .map((part) => titleCaseWord(part.trim()))
    .filter(Boolean)
    .join(" ");

export const formatLibraryDisplayName = (value: string): string => {
  const raw = (value || "").trim();
  if (!raw) return "Ungrouped";
  if (raw.toLowerCase() === "ungrouped") return "Ungrouped";

  const normalized = raw.replace(/[_]+/g, "-").replace(/\s*-\s*/g, "-");
  const parts = normalized.split("-").filter(Boolean);
  if (parts.length === 0) return titleCaseSegment(raw);

  const head = parts[0].toLowerCase();
  const tail = parts.slice(1).join(" ").trim();
  if (["movie", "movies"].includes(head)) {
    return tail ? `Movies – ${titleCaseSegment(tail)}` : "Movies";
  }
  if (["tv", "series", "show", "shows"].includes(head)) {
    return tail ? `TV – ${titleCaseSegment(tail)}` : "TV";
  }

  if (parts.length > 1) {
    return `${titleCaseSegment(parts[0])} – ${titleCaseSegment(parts.slice(1).join(" "))}`;
  }
  return titleCaseSegment(raw);
};