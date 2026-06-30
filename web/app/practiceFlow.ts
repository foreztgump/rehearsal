// These mode and role keys must mirror agent/interview.py. There is no frontend
// schema handshake for mode.update, so drift stays silent until the agent rejects
// the RPC payload at runtime.
export const MODE_LEARN = "learn";
export const MODE_DRILL = "drill";
export const MODE_ROLEPLAY = "roleplay";
export const MODE_INTERVIEW = "interview";

export const ROLES = [
  "general_professional",
  "software_engineer",
  "ai_ml_practitioner",
  "data_analyst",
  "cloud_devops",
  "cybersecurity",
  "product_manager",
  "sales_customer_success",
  "leadership",
  "grc_policy",
] as const;

export type PracticeMode =
  | typeof MODE_LEARN
  | typeof MODE_DRILL
  | typeof MODE_ROLEPLAY
  | typeof MODE_INTERVIEW;
export type InterviewRoleKey = (typeof ROLES)[number];

export type InterviewMode = {
  mode: string;
  role_key: string;
};

export const DEFAULT_ROLE: InterviewRoleKey = "general_professional";

export const DEFAULT_INTERVIEW: InterviewMode = {
  mode: MODE_LEARN,
  role_key: DEFAULT_ROLE,
};

export const PRACTICE_SCENARIOS: { label: string; value: PracticeMode }[] = [
  { label: "General Chat", value: MODE_LEARN },
  { label: "Drill", value: MODE_DRILL },
  { label: "Roleplay", value: MODE_ROLEPLAY },
  { label: "Mock Interview", value: MODE_INTERVIEW },
];

export const ROLE_LABEL: Record<InterviewRoleKey, string> = {
  general_professional: "General Professional",
  software_engineer: "Software Engineer",
  ai_ml_practitioner: "AI / ML Practitioner",
  data_analyst: "Data Analyst",
  cloud_devops: "Cloud / DevOps",
  cybersecurity: "Cybersecurity",
  product_manager: "Product Manager",
  sales_customer_success: "Sales / Customer Success",
  leadership: "Leadership",
  grc_policy: "GRC / Policy",
};

const PERSONA_TARGET_BY_DISPLAY_NAME: Record<string, InterviewRoleKey> = {
  "Software Engineering Mentor": "software_engineer",
  "AI/ML Coach": "ai_ml_practitioner",
  "Cybersecurity Trainer": "cybersecurity",
  "Product Manager Coach": "product_manager",
  "GRC / Policy Advisor": "grc_policy",
};

export function isInterviewMode(value: InterviewMode): boolean {
  return value.mode === MODE_INTERVIEW;
}

export function interviewTargetForPersona(displayName: string): InterviewRoleKey {
  return PERSONA_TARGET_BY_DISPLAY_NAME[displayName] ?? DEFAULT_ROLE;
}

export function withPracticeMode(
  current: InterviewMode,
  mode: string,
  personaDisplayName: string,
  hasSeenInterviewTarget = false,
): InterviewMode {
  if (mode !== MODE_INTERVIEW) return { ...current, mode };
  if (
    current.mode === MODE_INTERVIEW ||
    hasSeenInterviewTarget ||
    current.role_key !== DEFAULT_ROLE
  ) {
    return { ...current, mode };
  }
  return {
    mode,
    role_key: interviewTargetForPersona(personaDisplayName),
  };
}

export function selfCheck(): void {
  const roleSet = new Set<string>(ROLES);
  for (const scenario of PRACTICE_SCENARIOS) {
    if (!scenario.label || !scenario.value) throw new Error("invalid practice scenario");
  }
  for (const role of Object.values(PERSONA_TARGET_BY_DISPLAY_NAME)) {
    if (!roleSet.has(role)) throw new Error(`unknown mapped role: ${role}`);
  }
  if (interviewTargetForPersona("Unknown") !== DEFAULT_ROLE) {
    throw new Error("unknown persona fallback drifted");
  }
}
