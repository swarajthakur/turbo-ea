/** Helpers that derive ``CreateRiskDialog`` seed values from TurboLens findings. */
import type {
  Risk,
  RiskCategory,
  RiskImpact,
  RiskProbability,
  TurboLensComplianceFinding,
} from "@/types";

const COMPLIANCE_SEVERITY_TO_IMPACT: Record<string, RiskImpact> = {
  critical: "critical",
  high: "high",
  medium: "medium",
  low: "low",
  info: "low",
};

function safeImpact(v: string | null | undefined): RiskImpact {
  if (v === "critical" || v === "high" || v === "medium" || v === "low") return v;
  return "medium";
}

export interface RiskDialogSeed {
  mode: "manual" | "compliance";
  title: string;
  description: string;
  category: RiskCategory;
  initial_probability: RiskProbability;
  initial_impact: RiskImpact;
  cardIds: string[];
  /** If set, CreateRiskDialog calls the promote endpoint with this finding id. */
  findingId?: string;
}

export function seedFromCompliance(finding: TurboLensComplianceFinding): RiskDialogSeed {
  const where = finding.card_name ?? "landscape";
  const base = finding.regulation_article
    ? `${finding.regulation_article}: ${where}`
    : `${finding.regulation.toUpperCase()}: ${where}`;
  const descriptionParts = [finding.requirement, finding.gap_description].filter(
    (p) => p && p.trim(),
  );
  return {
    mode: "compliance",
    findingId: finding.id,
    title: base,
    description: descriptionParts.join("\n\n"),
    category: "compliance",
    initial_probability: finding.status === "non_compliant" ? "high" : "medium",
    initial_impact: safeImpact(COMPLIANCE_SEVERITY_TO_IMPACT[finding.severity]),
    cardIds: finding.card_id ? [finding.card_id] : [],
  };
}

export function emptySeed(cardIds: string[] = []): RiskDialogSeed {
  return {
    mode: "manual",
    title: "",
    description: "",
    category: "operational",
    initial_probability: "medium",
    initial_impact: "medium",
    cardIds,
  };
}

/** Pick a UI chip colour based on a risk level. Used by both list + detail. */
export function riskLevelChipColor(
  level: Risk["initial_level"] | null | undefined,
): "error" | "warning" | "info" | "success" | "default" {
  switch (level) {
    case "critical":
      return "error";
    case "high":
      return "warning";
    case "medium":
      return "info";
    case "low":
      return "success";
    default:
      return "default";
  }
}
