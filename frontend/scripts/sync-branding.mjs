import { cpSync, existsSync, mkdirSync, rmSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __filename = fileURLToPath(import.meta.url);
const __dirname = path.dirname(__filename);

const sourceDir = path.resolve(__dirname, "../../branding/web");
const targetDir = path.resolve(__dirname, "../static/branding");

if (!existsSync(sourceDir)) {
  console.error(`[sync:branding] Missing source directory: ${sourceDir}`);
  process.exit(1);
}

rmSync(targetDir, { recursive: true, force: true });
mkdirSync(targetDir, { recursive: true });
cpSync(sourceDir, targetDir, { recursive: true });

console.log(`[sync:branding] Synced ${sourceDir} -> ${targetDir}`);
