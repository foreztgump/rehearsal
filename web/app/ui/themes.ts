// Theme catalog for the landing/setup + talking screens (design-mockups/v4).
// Six runtime-selectable themes. Each theme is two things:
//   1. A CSS-variable palette block (lives in globals.css, keyed by [data-theme]).
//   2. JS-side metadata used by the canvas visualizer + the theme picker swatches.
//
// Pure data — no React import, no side effects (same bundle-isolation discipline
// as tokens.ts / avatarConfig.ts). The CSS palette and these `swatch` colors are
// hand-kept in sync with the matching globals.css [data-theme="…"] block.

// RGB triplet used by the canvas visualizer (avoids re-parsing hex each frame).
export type RGB = [number, number, number];

// Which canvas renderer a theme drives. One per v4 mockup visualizer.
export type VizMode =
  | "halo" // 1 Eclipse Aurora — rotating comet arcs + glossy orb
  | "bloom" // 2 Nebula Bloom — petals + particle ring
  | "sonar" // 3 Sonar Pulse — emitted rings + circular frequency bars
  | "blob" // 4 Liquid Ember — morphing wobble blob
  | "prism" // 5 Prism Wave — mirrored radial waveform ribbons
  | "aurora"; // 6 Aurora Veil — flowing northern-lights bands

export type ThemeId =
  | "eclipse-aurora"
  | "nebula-bloom"
  | "sonar-pulse"
  | "liquid-ember"
  | "prism-wave"
  | "aurora-veil";

export type Theme = {
  id: ThemeId;
  name: string;
  blurb: string;
  vizMode: VizMode;
  // Visualizer colors. p1 = primary accent, p2/p3 = secondary halo hues.
  viz: {
    p1: RGB;
    p2: RGB;
    p3: RGB;
    // Prism Wave / Aurora Veil drive their ribbons from an HSL hue instead of RGB.
    hueBase?: number;
  };
  // Swatch shown in the picker (mirrors the CSS --accent / --bg of each block).
  swatch: { accent: string; bg: string };
};

export const THEMES: Theme[] = [
  {
    id: "eclipse-aurora",
    name: "Eclipse Aurora",
    blurb: "Cool boreal ink with a muted jade halo",
    vizMode: "halo",
    viz: { p1: [108, 195, 166], p2: [142, 160, 214], p3: [103, 179, 201] },
    swatch: { accent: "#6cc3a6", bg: "#0a0d11" },
  },
  {
    id: "nebula-bloom",
    name: "Nebula Bloom",
    blurb: "Deep magenta night, blooming petal core",
    vizMode: "bloom",
    viz: { p1: [194, 107, 194], p2: [191, 105, 171], p3: [177, 115, 196] },
    swatch: { accent: "#c26bc2", bg: "#130b13" },
  },
  {
    id: "sonar-pulse",
    name: "Sonar Pulse",
    blurb: "Teal depths with emitted sonar rings",
    vizMode: "sonar",
    viz: { p1: [107, 177, 194], p2: [105, 154, 191], p3: [115, 196, 194] },
    swatch: { accent: "#6bb1c2", bg: "#0b1213" },
  },
  {
    id: "liquid-ember",
    name: "Liquid Ember",
    blurb: "Warm amber glow, molten morphing orb",
    vizMode: "blob",
    viz: { p1: [194, 156, 107], p2: [191, 174, 105], p3: [196, 142, 115] },
    swatch: { accent: "#c29c6b", bg: "#13100b" },
  },
  {
    id: "prism-wave",
    name: "Prism Wave",
    blurb: "Violet dusk with prism-split waveforms",
    vizMode: "prism",
    viz: { p1: [135, 117, 204], p2: [150, 113, 198], p3: [115, 117, 196], hueBase: 250 },
    swatch: { accent: "#8775cc", bg: "#0d0b13" },
  },
  {
    id: "aurora-veil",
    name: "Aurora Veil",
    blurb: "Rose-ink veil of flowing aurora bands",
    vizMode: "aurora",
    viz: { p1: [194, 107, 133], p2: [191, 105, 111], p3: [196, 115, 158], hueBase: 342 },
    swatch: { accent: "#c26b85", bg: "#130b0e" },
  },
];

export const DEFAULT_THEME_ID: ThemeId = "eclipse-aurora";

export const THEME_STORAGE_KEY = "adept.theme";

const THEME_BY_ID = new Map<ThemeId, Theme>(THEMES.map((t) => [t.id, t]));

export function getTheme(id: string | null | undefined): Theme {
  return (id && THEME_BY_ID.get(id as ThemeId)) || THEME_BY_ID.get(DEFAULT_THEME_ID)!;
}

export function isThemeId(value: string | null | undefined): value is ThemeId {
  return !!value && THEME_BY_ID.has(value as ThemeId);
}
