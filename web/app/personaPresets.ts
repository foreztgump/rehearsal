// Persona presets (AVTR-13). A preset is a ready-made Persona snapshot + an avatar
// mood; selecting one pre-fills the still-editable persona fields and voice. All
// presets reuse the default GLB (mood varies per preset — see avatarConfig). Pure
// data, no React — same bundle discipline as avatarConfig.ts.
import { DEFAULT_PERSONA, type Persona } from "./PersonaPanel";

export type PersonaPreset = {
  id: string;
  label: string;
  blurb: string;
  persona: Persona;
  mood: "neutral" | "happy" | "angry" | "sad" | "fear" | "disgust" | "love" | "sleep";
};

export const DEFAULT_PRESET_ID = "cyber-trainer";

export const PERSONA_PRESETS: PersonaPreset[] = [
  {
    id: DEFAULT_PRESET_ID,
    label: "Cybersecurity Trainer",
    blurb: "General cyber coach — the default.",
    persona: DEFAULT_PERSONA, // role_text "" → agent ROLE_PREAMBLE; voice af_bella
    mood: "neutral",
  },
  {
    id: "soc-analyst-coach",
    label: "SOC Analyst Coach",
    blurb: "Alert triage, SIEM, MITRE ATT&CK, incident escalation.",
    persona: {
      role_text:
        "You are a SOC analyst mentor. Coach the learner on alert triage, SIEM and " +
        "log analysis, the MITRE ATT&CK framework, phishing and malware " +
        "investigation, and incident escalation — practitioner-level, spoken aloud.",
      display_name: "SOC Analyst Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "moderate",
      voice_id: "am_michael",
    },
    mood: "neutral",
  },
  {
    id: "security-engineer-coach",
    label: "Security Engineer Coach",
    blurb: "Secure architecture, IAM, vuln mgmt, cloud hardening, automation.",
    persona: {
      role_text:
        "You are a security engineering mentor. Coach the learner on secure " +
        "architecture and network segmentation, identity and access management, " +
        "vulnerability management, cloud and infrastructure hardening, and security " +
        "automation — practitioner-level, spoken aloud.",
      display_name: "Security Engineer Coach",
      difficulty: "intermediate",
      verbosity: "balanced",
      correction: "moderate",
      voice_id: "bm_george",
    },
    mood: "neutral",
  },
  {
    id: "grc-advisor",
    label: "GRC Advisor",
    blurb: "Risk, NIST/ISO 27001, audit evidence, policy, vendor risk.",
    persona: {
      role_text:
        "You are a governance, risk, and compliance advisor. Coach the learner on " +
        "risk assessment and treatment, control frameworks such as NIST and " +
        "ISO 27001, audit and compliance evidence, policy development, and " +
        "third-party risk — practitioner-level, spoken aloud.",
      display_name: "GRC Advisor",
      difficulty: "intermediate",
      verbosity: "detailed",
      correction: "gentle",
      voice_id: "bf_emma",
    },
    mood: "neutral",
  },
  {
    id: "domain-expert",
    label: "Domain Expert",
    blurb: "General expert sounding board for any topic you set.",
    persona: {
      role_text:
        "You are a knowledgeable domain expert and Socratic sounding board. Help the " +
        "learner practice explaining and reasoning about whatever domain they raise, " +
        "spoken aloud, with precise terminology.",
      display_name: "Domain Expert",
      difficulty: "expert",
      verbosity: "balanced",
      correction: "gentle",
      voice_id: "af_nicole",
    },
    mood: "happy",
  },
];
