const BASE_URL = (
  ((import.meta as { env?: { BASE_URL?: string } }).env?.BASE_URL || "/")
).replace(/\/?$/, "/");

const withBase = (path: string): string => {
  const normalized = path.replace(/^\/+/, "");
  return `${BASE_URL}${normalized}`;
};

export const BRANDING = {
  applicationName: "MediaMasterr",
  applicationTitle: "MediaMasterr",
  tagline: "Unify • Manage • Optimize",
  primaryColor: "#6366f1",
  accentColor: "#5658f3",
  assets: {
    logo: withBase("branding/logo.png"),
    favicon: withBase("branding/favicon-32x32.png"),
    appleTouchIcon: withBase("branding/apple-touch-icon.png"),
    androidChrome192: withBase("branding/android-chrome-192x192.png"),
    androidChrome512: withBase("branding/android-chrome-512x512.png"),
    openGraphImage: withBase("branding/logo.png"),
    mediaPlaceholder: withBase("branding/media-placeholder.png"),
  },
} as const;
