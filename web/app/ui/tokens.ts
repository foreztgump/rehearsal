// Single source of truth for the dark-theme design system (Phase 13 UI overhaul).
// Pure constants / typed objects — no React import, no side effects — so it
// tree-shakes cleanly and never pulls weight into the voice-only bundle (mirrors
// the avatarConfig.ts discipline). Every config panel imports its shared styles
// from here instead of redefining the copy-pasted blocks.
//
// The palette IS the locked design system (13-UI-SPEC.md §Color, 13-CONTEXT.md):
// hex values are unchanged from the pre-refactor panels. Spacing/typography are
// normalized onto the UI-SPEC px scale (4/8/16/24/32/48/64, 4 sizes / 2 weights,
// no text below 14px).

// Locked dark GitHub-style palette (60/30/10). NEVER change these values.
export const palette = {
  bg: "#0b0f14", // app background, talking-screen canvas (dominant 60%)
  panel: "#0d1117", // cards / panels / setup surface (secondary 30%)
  inputBg: "#161b22", // nested input fields
  border: "#30363d", // borders
  accent: "#58a6ff", // active segment, agent transcript, focus ring (accent 10%)
  action: "#3fb950", // primary CTA + success only
  warning: "#d29922", // transient applying/parsing/distilling/thinking states
  destructive: "#f85149", // errors + leave-session confirmation only
  text: "#e6edf3", // primary text
  textBody: "#c9d1d9", // secondary / body-in-panel text
  textMuted: "#8b949e", // muted / helper text
} as const;

// Spacing scale — multiples of 4 (13-UI-SPEC.md §Spacing Scale).
export const space = {
  xs: "4px",
  sm: "8px",
  md: "16px",
  lg: "24px",
  xl: "32px",
  xxl: "48px",
  xxxl: "64px",
} as const;

// Border radii. Pill/segmented controls use the full-round 999px; controls 8px;
// cards 12px (13-UI-SPEC.md §Spacing Scale exceptions).
export const radius = {
  control: "8px",
  card: "12px",
  pill: "999px",
} as const;

// Typography — exactly 4 sizes, 2 weights, line-heights 1.5 body / 1.2 heading
// (13-UI-SPEC.md §Typography). No size below 14px.
export const font = {
  size: {
    body: "16px",
    label: "14px",
    heading: "20px",
    display: "28px",
  },
  weight: {
    regular: 400,
    semibold: 600,
  },
  lineHeight: {
    body: 1.5,
    heading: 1.2,
  },
} as const;

// Shared panel container style. Rebuilt from the tokens above (replacing the
// pre-refactor rem ad-hoc values); the 0.9rem panel font bumps to the 14px Label
// token so no text sits below 14px. Palette values unchanged.
export const panelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: space.sm,
  width: "20rem",
  padding: space.md,
  border: `1px solid ${palette.border}`,
  borderRadius: radius.card,
  background: palette.panel,
  color: palette.textBody,
  fontSize: font.size.label,
};

// Shared label style (a labeled <label> wrapping its control).
export const labelStyle: React.CSSProperties = {
  display: "flex",
  flexDirection: "column",
  gap: space.xs,
  fontWeight: font.weight.semibold,
};

// Shared input / select / textarea style.
export const inputStyle: React.CSSProperties = {
  padding: `${space.sm} ${space.sm}`,
  borderRadius: radius.control,
  border: `1px solid ${palette.border}`,
  background: palette.inputBg,
  color: palette.textBody,
  fontWeight: font.weight.regular,
};
