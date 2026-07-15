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
    logo: withBase("branding/logo.svg"),
    faviconSvg: withBase("branding/favicon.ico"),
    faviconPng: withBase("branding/favicon-32x32.png"),
    appleTouchIcon: withBase("branding/apple-touch-icon.png"),
    androidChrome192: withBase("branding/android-chrome-192x192.png"),
    androidChrome512: withBase("branding/android-chrome-512x512.png"),
    manifest: withBase("branding/site.webmanifest"),
    openGraphImage: withBase("branding/logo.png"),
    mediaPlaceholder: withBase("branding/media-placeholder.svg"),
  },
} as const;
