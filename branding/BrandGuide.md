MediaMasterr Branding Guide

1. Canonical ownership
- branding/source contains editable source artwork.
- branding/web contains exported runtime assets and is the canonical source for
	app branding distribution.

2. Runtime serving model
- Frontend and desktop runtime assets are served from /branding.
- frontend/static/branding is a generated mirror of branding/web.
- Do not hand-edit files in frontend/static/branding.

3. Required runtime assets
- logo.svg and logo.png
- favicon.ico and favicon-*.png variants
- apple-touch-icon.png
- android-chrome-192x192.png and android-chrome-512x512.png
- site.webmanifest
- browserconfig.xml

4. Update procedure
1. Update source files in branding/source if design edits are needed.
2. Export runtime formats into branding/web.
3. Run npm run sync:branding in frontend.
4. Run npm run check, npm test, npm run build.
5. Verify branding renders across dashboard, movies, series, protection,
	 settings, system, about, login, and sidebar.

5. Stability policy
- No page should reference legacy branding locations outside /branding.
- No runtime path should bypass the branding sync flow.
