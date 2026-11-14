/**
 * i18n:check — fails if any enabled locale is missing a key from en-IN.json.
 * Run: npm run i18n:check
 */
import { readFileSync, readdirSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";

const LOCALES_DIR = join(
  dirname(fileURLToPath(import.meta.url)),
  "../src/i18n/locales",
);

/** ["login.signIn", "tech.signOut", ...] */
function flatten(obj, prefix = "") {
  const keys = [];
  for (const [key, value] of Object.entries(obj)) {
    if (key === "_meta") continue;
    const path = prefix ? `${prefix}.${key}` : key;
    if (value && typeof value === "object") keys.push(...flatten(value, path));
    else keys.push(path);
  }
  return keys;
}

const en = JSON.parse(
  readFileSync(join(LOCALES_DIR, "en-IN.json"), "utf8"),
);
const baseKeys = new Set(flatten(en));

const files = readdirSync(LOCALES_DIR).filter((f) => f.endsWith(".json"));
let failed = false;

for (const file of files) {
  if (file === "en-IN.json") continue;
  const locale = JSON.parse(readFileSync(join(LOCALES_DIR, file), "utf8"));
  const keys = new Set(flatten(locale));
  const missing = [...baseKeys].filter((k) => !keys.has(k));
  const extra = [...keys].filter((k) => !baseKeys.has(k));

  if (missing.length || extra.length) {
    failed = true;
    console.error(`✗ ${file}`);
    if (missing.length) console.error(`   missing: ${missing.join(", ")}`);
    if (extra.length) console.error(`   extra:   ${extra.join(", ")}`);
  } else {
    console.log(`✓ ${file} (${keys.size} keys)`);
  }
}

if (files.length < 11) {
  console.error(`Expected 11 enabled locales, found ${files.length}`);
  process.exit(1);
}

if (failed) {
  console.error("\ni18n:check FAILED");
  process.exit(1);
}
console.log("\ni18n:check OK — all locales complete");
