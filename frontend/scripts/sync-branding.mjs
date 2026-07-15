import {
  copyFileSync,
  existsSync,
  mkdirSync,
  readdirSync,
  rmSync,
  statSync,
} from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const sourceDir = path.resolve(__dirname, "../../branding/web");
const targetDir = path.resolve(__dirname, "../static/branding");
const requiredAssets = [
  "logo.svg",
  "logo.png",
  "favicon.ico",
  "favicon-32x32.png",
  "apple-touch-icon.png",
  "android-chrome-192x192.png",
  "android-chrome-512x512.png",
  "site.webmanifest",
  "browserconfig.xml",
  "media-placeholder.svg",
];

const syncDirectory = (source, target) => {
  mkdirSync(target, { recursive: true });

  const sourceEntries = readdirSync(source);
  const sourceNames = new Set(sourceEntries);

  for (const targetEntry of readdirSync(target)) {
    if (!sourceNames.has(targetEntry)) {
      rmSync(path.join(target, targetEntry), { recursive: true, force: true });
    }
  }

  for (const entry of sourceEntries) {
    const sourcePath = path.join(source, entry);
    const targetPath = path.join(target, entry);
    const sourceStats = statSync(sourcePath);

    if (sourceStats.isDirectory()) {
      syncDirectory(sourcePath, targetPath);
      continue;
    }

    copyFileSync(sourcePath, targetPath);
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

syncDirectory(sourceDir, targetDir);

console.log(`[sync:branding] Synced ${sourceDir} -> ${targetDir}`);
