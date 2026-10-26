#!/usr/bin/env node
/*
  Construit les fichiers 3D vendored du kit d'animation (studio/workspace/anim/lib/) :

    node scripts/build_three_bundle.mjs

  - three.bundle.min.js : three.js + les addons du kit en un seul script classique (IIFE) qui pose
    `window.THREE`. Les pages d'animation sont ouvertes en file:// sans réseau (studio/sandbox_exec.py) :
    les modules ES y sont bloqués (origine null), d'où le bundle.
  - fonts/poppins3d.typeface.js : Poppins ExtraBold au format typeface de three (TextGeometry), réduite aux
    caractères ASCII imprimables + lettres accentuées et symboles courants (unités des nombres extrudés) ; les
    titres restent en SVG (studio.js), plus nets.

  Les dépendances sont installées dans un dossier temporaire : rien n'est ajouté au repo hormis les sorties.
  Relancer après un changement de version (THREE_VERSION) ou de la liste des addons.
*/
import { execFileSync } from "node:child_process";
import { mkdtempSync, readFileSync, writeFileSync, copyFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { createRequire } from "node:module";

const THREE_VERSION = "0.170.0";
const ESBUILD_VERSION = "0.24.0";
const OPENTYPE_VERSION = "1.3.4";
const GLYPHS = Array.from({length: 95}, (_, i) => String.fromCharCode(32 + i)).join("") + "€×°éèêëàâçùûîïôœÉÈÀÇ";

const repo = join(dirname(fileURLToPath(import.meta.url)), "..");
const lib = join(repo, "studio", "workspace", "anim", "lib");
const work = mkdtempSync(join(tmpdir(), "three-bundle-"));

try {
  writeFileSync(join(work, "package.json"), JSON.stringify({ private: true, type: "module" }));
  execFileSync("npm", ["install", "--silent", "--no-audit", "--no-fund",
    `three@${THREE_VERSION}`, `esbuild@${ESBUILD_VERSION}`, `opentype.js@${OPENTYPE_VERSION}`],
  { cwd: work, stdio: "inherit" });

  writeFileSync(join(work, "entry.js"), `
import * as T from "three";
import { EffectComposer } from "three/addons/postprocessing/EffectComposer.js";
import { RenderPass } from "three/addons/postprocessing/RenderPass.js";
import { UnrealBloomPass } from "three/addons/postprocessing/UnrealBloomPass.js";
import { BokehPass } from "three/addons/postprocessing/BokehPass.js";
import { OutputPass } from "three/addons/postprocessing/OutputPass.js";
import { ShaderPass } from "three/addons/postprocessing/ShaderPass.js";
import { Reflector } from "three/addons/objects/Reflector.js";
import { RoomEnvironment } from "three/addons/environments/RoomEnvironment.js";
import { RoundedBoxGeometry } from "three/addons/geometries/RoundedBoxGeometry.js";
import { TextGeometry } from "three/addons/geometries/TextGeometry.js";
import { FontLoader } from "three/addons/loaders/FontLoader.js";
window.THREE = { ...T, EffectComposer, RenderPass, UnrealBloomPass, BokehPass, OutputPass, ShaderPass, Reflector,
  RoomEnvironment, RoundedBoxGeometry, TextGeometry, FontLoader };
`);
  execFileSync(join(work, "node_modules", ".bin", "esbuild"), [
    "entry.js", "--bundle", "--minify", "--format=iife", "--target=es2020", "--legal-comments=none",
    `--banner:js=/* three.js r${THREE_VERSION.split(".")[1]} + addons (MIT, https://threejs.org) — généré par scripts/build_three_bundle.mjs */`,
    `--outfile=${join(lib, "three.bundle.min.js")}`,
  ], { cwd: work, stdio: "inherit" });
  copyFileSync(join(work, "node_modules", "three", "LICENSE"), join(lib, "three.LICENSE"));

  // Typeface three : coordonnées en unités de la police (resolution = unitsPerEm), commandes
  // « q »/« b » avec le point d'arrivée AVANT les points de contrôle (format lu par three/addons Font).
  const opentype = createRequire(join(work, "package.json"))("opentype.js");
  const font = opentype.parse(readFileSync(join(lib, "fonts", "Poppins-ExtraBold.ttf")).buffer);
  const r = (v) => Math.round(v);
  const glyphs = {};
  for (const ch of new Set(GLYPHS)) {
    const glyph = font.charToGlyph(ch);
    const o = glyph.path.commands.map((c) => {
      switch (c.type) {
        case "M": return `m ${r(c.x)} ${r(c.y)}`;
        case "L": return `l ${r(c.x)} ${r(c.y)}`;
        case "Q": return `q ${r(c.x)} ${r(c.y)} ${r(c.x1)} ${r(c.y1)}`;
        case "C": return `b ${r(c.x)} ${r(c.y)} ${r(c.x1)} ${r(c.y1)} ${r(c.x2)} ${r(c.y2)}`;
        default: return "";
      }
    }).filter(Boolean).join(" ");
    const box = glyph.getBoundingBox();
    glyphs[ch] = { ha: r(glyph.advanceWidth), x_min: r(box.x1), x_max: r(box.x2), o };
  }
  const head = font.tables.head;
  const typeface = {
    familyName: "Poppins ExtraBold", resolution: font.unitsPerEm, glyphs,
    ascender: font.ascender, descender: font.descender,
    boundingBox: { xMin: head.xMin, yMin: head.yMin, xMax: head.xMax, yMax: head.yMax },
    underlinePosition: font.tables.post.underlinePosition,
    underlineThickness: font.tables.post.underlineThickness,
  };
  writeFileSync(join(lib, "fonts", "poppins3d.typeface.js"),
    `/* Poppins ExtraBold (OFL, voir OFL.txt), ASCII + accents — scripts/build_three_bundle.mjs */\n`
    + `window.POPPINS_3D = ${JSON.stringify(typeface)};\n`);
  console.log("ok :", join(lib, "three.bundle.min.js"));
} finally {
  rmSync(work, { recursive: true, force: true });
}
