import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const sourceDir = path.resolve(__dirname, "../../branding/web");
const targetDir = path.resolve(__dirname, "../static/branding");
const requiredAssets = [
  "logo.png",
  "logo-icon.png",
  "favicon-16x16.png",
  "favicon-32x32.png",
  "favicon-48x48.png",
  "favicon-64x64.png",
  "favicon-128x128.png",
  "favicon-256x256.png",
  "apple-touch-icon.png",
  "android-chrome-192x192.png",
  "android-chrome-512x512.png",
  "site.webmanifest",
  "browserconfig.xml",
  "media-placeholder.png",
];

const syncRuntimeBrandingAssets = (source, target, assets) => {
  mkdirSync(target, { recursive: true });

  const expectedAssets = new Set(assets);
  for (const targetEntry of readdirSync(target)) {
    if (!expectedAssets.has(targetEntry)) {
      rmSync(path.join(target, targetEntry), { recursive: true, force: true });
    }
  }

  for (const assetName of assets) {
    copyFileSync(path.join(source, assetName), path.join(target, assetName));
  }
};

if (!existsSync(sourceDir)) {
  console.error(`[sync:branding] Missing source directory: ${sourceDir}`);
  process.exit(1);
}

for (const assetName of requiredAssets) {
  const assetPath = path.join(sourceDir, assetName);
  if (!existsSync(assetPath)) {
    console.error(`[sync:branding] Missing required asset: ${assetPath}`);
    process.exit(1);
  }
}

syncRuntimeBrandingAssets(sourceDir, targetDir, requiredAssets);

console.log(`[sync:branding] Synced ${sourceDir} -> ${targetDir}`);
