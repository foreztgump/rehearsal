import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import test from "node:test";

// RED guard (T1): fails against today's SettingsDrawer.tsx + globals.css and goes
// green once T2 reskins them onto the shared-theme classes (.drawer-scrim, .surface,
// .btn-ghost, .btn-apply danger). No hardcoded colors leak into the component.
const read = (path) => readFileSync(new URL(path, import.meta.url), "utf8");
const drawerSrc = read("./SettingsDrawer.tsx");
const cssSrc = read("./globals.css");
const drawerScrimRule = cssSrc.match(/\.drawer-scrim\s*\{[^}]*\}/s)?.[0] ?? "";

test("scrim is a themed .drawer-scrim, not a hardcoded rgba fill", () => {
  assert.doesNotMatch(drawerSrc, /rgba\(0\s*,\s*0\s*,\s*0\s*,\s*0\.55\)/);
  assert.match(drawerSrc, /className="drawer-scrim"/);
});

test(".drawer-scrim rule blurs with backdrop-filter over a themed var() background", () => {
  assert.match(drawerScrimRule, /backdrop-filter/);
  assert.match(drawerScrimRule, /var\(--/);
  assert.doesNotMatch(drawerScrimRule, /rgba\(0\s*,\s*0\s*,\s*0/);
});

test("drawer panel uses the shared .surface class instead of palette.panel", () => {
  assert.match(drawerSrc, /className="[^"]*\bsurface\b[^"]*"/);
  assert.doesNotMatch(drawerSrc, /background:\s*palette\.panel/);
});

test("close button is a .btn-ghost carrying aria-label", () => {
  assert.match(drawerSrc, /aria-label="Close settings"[^>]*>/);
  assert.match(
    drawerSrc,
    /\bbtn-ghost\b[\s\S]*?aria-label="Close settings"|aria-label="Close settings"[\s\S]*?\bbtn-ghost\b/,
  );
});

test("End armed outline uses .btn-ghost danger", () => {
  assert.match(drawerSrc, /className="btn-ghost danger"/);
});

test("End confirm destructive fill uses .btn-apply danger, not inline palette", () => {
  assert.match(drawerSrc, /className="btn-apply danger"/);
  assert.doesNotMatch(drawerSrc, /color:\s*palette\.bg/);
  assert.match(cssSrc, /\.btn-apply\.danger\s*\{[^}]*background:\s*var\(--destructive\)/);
});

test("confirm-step Cancel uses .btn-ghost", () => {
  const cancelButtons = drawerSrc.match(/className="btn-ghost"[\s\S]*?Cancel/g) ?? [];
  assert.ok(cancelButtons.length >= 1, "confirm Cancel must carry className=btn-ghost");
});

test("END_CONFIRM stays exported for single-sourcing (back-compat)", () => {
  assert.match(drawerSrc, /export const END_CONFIRM/);
});

test("no raw hex colors leak into SettingsDrawer.tsx", () => {
  assert.doesNotMatch(drawerSrc, /#(?:[0-9a-fA-F]{3}|[0-9a-fA-F]{6})\b/);
});
