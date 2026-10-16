/**
 * Minimal i18n scaffold: a typed dictionary per locale + a `t()` helper.
 * English is the default; add a locale by copying `en` (missing keys fall back to English).
 */
const en = {
  appName: "PhishGuard",
  tagline: "Security-awareness training — simulations are in-app previews only",
  nav: {
    dashboard: "Dashboard",
    campaigns: "Campaigns",
    templates: "Templates",
    people: "Learners",
    training: "Training",
    inbox: "Simulation inbox",
    reports: "Report phish",
    triage: "Triage queue",
    ai: "AI Studio",
    risk: "Risk & reports",
    admin: "Admin",
    profile: "Profile",
  },
  demo: "DEMO MODE",
  demoHint: "No AI provider key is set. Outputs are deterministic demo results, not real model output.",
  synthetic: "All learners and outcomes are synthetic.",
  loading: "Loading…",
  empty: "Nothing here yet.",
  retry: "Try again",
  signOut: "Sign out",
};

export type Dict = typeof en;

const hi: Partial<Dict> = {
  // Example partial translation to show the mechanism.
  loading: "लोड हो रहा है…",
  retry: "फिर से कोशिश करें",
};

const dictionaries: Record<string, Partial<Dict>> = { en, hi };

export function getDict(locale = "en"): Dict {
  return { ...en, ...(dictionaries[locale] ?? {}) } as Dict;
}

export const t = getDict("en");
