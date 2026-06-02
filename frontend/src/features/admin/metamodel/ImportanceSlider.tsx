import Box from "@mui/material/Box";
import Slider from "@mui/material/Slider";
import Typography from "@mui/material/Typography";
import { useTheme } from "@mui/material/styles";
import { useTranslation } from "react-i18next";

/**
 * Discrete data-quality importance control. Four tiers, shown as a slider with
 * numeric marks plus the tier name + number, so admins see both the friendly
 * label and the exact weight:
 *   Ignore = 0, Normal = 1, Important = 2, Critical = 3.
 *
 * The underlying value is the numeric field/contributor `weight` (0 excludes).
 * Legacy/out-of-range weights snap to the nearest tier for display without
 * being silently rewritten until the admin moves the slider.
 */

export const TIER_KEYS = ["ignore", "normal", "important", "critical"] as const;
export type Tier = 0 | 1 | 2 | 3;

export function weightToTier(weight: number | undefined): Tier {
  const w = weight ?? 1;
  if (w <= 0) return 0;
  if (w < 2) return 1;
  if (w < 3) return 2;
  return 3;
}

/** Intensity ramp (grey → primary.dark) so stronger weight reads as "counts more". */
export function useTierColor(): (tier: Tier) => string {
  const theme = useTheme();
  return (tier: Tier) =>
    [
      theme.palette.action.disabled,
      theme.palette.primary.light,
      theme.palette.primary.main,
      theme.palette.primary.dark,
    ][tier];
}

interface ImportanceSliderProps {
  value: number | undefined;
  onChange: (weight: number) => void;
  width?: number;
}

export default function ImportanceSlider({
  value,
  onChange,
  width = 150,
}: ImportanceSliderProps) {
  const { t } = useTranslation("admin");
  const tierColor = useTierColor();
  const tier = weightToTier(value);
  const color = tierColor(tier);
  const tierLabel = t(`metamodel.importance.${TIER_KEYS[tier]}`);

  return (
    <Box sx={{ display: "flex", alignItems: "center", gap: 2 }}>
      <Slider
        value={tier}
        onChange={(_, v) => onChange(Number(v))}
        min={0}
        max={3}
        step={1}
        marks={[{ value: 0 }, { value: 1 }, { value: 2 }, { value: 3 }]}
        size="small"
        valueLabelDisplay="off"
        aria-label={t("metamodel.importance.label")}
        sx={{ width, color, "& .MuiSlider-markActive": { bgcolor: "currentColor" } }}
      />
      <Typography
        variant="caption"
        sx={{ color, fontWeight: 700, minWidth: 96, whiteSpace: "nowrap" }}
      >
        {tierLabel} ({tier})
      </Typography>
    </Box>
  );
}
