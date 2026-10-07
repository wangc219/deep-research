/* One-off: the workbench grew a family of blue accents (#536bd2, #4563d6,
   #5d5adf …) that predate the platform brand violet (#625ff0), so the embedded
   workbench reads as a different product. Rotate every *accent* blue onto the
   brand hue while keeping its lightness, so depth and contrast are preserved.
   Slate text/border greys are left alone. */

import fs from 'node:fs';
import path from 'node:path';

const BRAND = '#625ff0';

const hexToRgb = (hex) => [1, 3, 5].map((index) => parseInt(hex.slice(index, index + 2), 16));

const rgbToHsl = ([r, g, b]) => {
  const rn = r / 255;
  const gn = g / 255;
  const bn = b / 255;
  const max = Math.max(rn, gn, bn);
  const min = Math.min(rn, gn, bn);
  const l = (max + min) / 2;
  const d = max - min;
  if (!d) return [0, 0, l];
  const s = l > 0.5 ? d / (2 - max - min) : d / (max + min);
  let h;
  if (max === rn) h = ((gn - bn) / d + (gn < bn ? 6 : 0)) / 6;
  else if (max === gn) h = ((bn - rn) / d + 2) / 6;
  else h = ((rn - gn) / d + 4) / 6;
  return [h, s, l];
};

const hslToRgb = ([h, s, l]) => {
  if (!s) {
    const v = Math.round(l * 255);
    return [v, v, v];
  }
  const q = l < 0.5 ? l * (1 + s) : l + s - l * s;
  const p = 2 * l - q;
  const channel = (t) => {
    let tt = t;
    if (tt < 0) tt += 1;
    if (tt > 1) tt -= 1;
    if (tt < 1 / 6) return p + (q - p) * 6 * tt;
    if (tt < 1 / 2) return q;
    if (tt < 2 / 3) return p + (q - p) * (2 / 3 - tt) * 6;
    return p;
  };
  return [channel(h + 1 / 3), channel(h), channel(h - 1 / 3)].map((v) => Math.round(v * 255));
};

const toHex = ([r, g, b]) =>
  `#${[r, g, b].map((v) => Math.max(0, Math.min(255, v)).toString(16).padStart(2, '0')).join('')}`;

const [brandHue, brandSat] = rgbToHsl(hexToRgb(BRAND));

// Accent, not slate: clearly blue-dominant and bright enough in blue to be a
// decorative/interactive colour rather than body text or a hairline.
const isAccentBlue = ([r, g, b]) => b - r >= 60 && b >= 170 && b > g;

const align = (hex) => {
  const rgb = hexToRgb(hex);
  if (!isAccentBlue(rgb)) return null;
  const [, s, l] = rgbToHsl(rgb);
  const next = toHex(hslToRgb([brandHue, Math.min(s, brandSat), l]));
  return next.toLowerCase() === hex.toLowerCase() ? null : next;
};

const roots = process.argv.slice(2);
const files = [];
const walk = (target) => {
  const stat = fs.statSync(target);
  if (stat.isDirectory()) {
    for (const entry of fs.readdirSync(target)) walk(path.join(target, entry));
  } else if (target.endsWith('.css')) {
    files.push(target);
  }
};
roots.forEach(walk);

const dryRun = process.env.DRY_RUN === '1';
const tally = new Map();
let changedFiles = 0;

for (const file of files) {
  const source = fs.readFileSync(file, 'utf8');
  let hits = 0;
  const next = source.replace(/#[0-9a-fA-F]{6}\b/g, (match) => {
    const mapped = align(match);
    if (!mapped) return match;
    hits += 1;
    const key = `${match.toLowerCase()} -> ${mapped}`;
    tally.set(key, (tally.get(key) || 0) + 1);
    return mapped;
  });
  if (hits) {
    changedFiles += 1;
    if (!dryRun) fs.writeFileSync(file, next);
  }
}

const rows = [...tally.entries()].sort((a, b) => b[1] - a[1]);
console.log(`${dryRun ? '[dry run] ' : ''}files changed: ${changedFiles}/${files.length}`);
console.log(`distinct colours remapped: ${rows.length}`);
console.log(`total replacements: ${rows.reduce((sum, [, count]) => sum + count, 0)}`);
console.log(rows.slice(0, 25).map(([key, count]) => `  ${count.toString().padStart(3)}  ${key}`).join('\n'));
