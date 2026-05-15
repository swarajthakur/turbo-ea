/**
 * Format a recurrence rule for display.
 *
 * Returns a translation-aware human label like "One-shot",
 * "Every week", or "Every 6 months". The caller passes a translation
 * function `t` already bound to the right namespace ("delivery"), so
 * this helper is pure (no react-i18next dependency) and unit-testable.
 */
import type { RecurrenceUnit } from "@/types";

type TFn = (key: string, options?: Record<string, unknown>) => string;

export function formatRecurrence(
  unit: RecurrenceUnit,
  interval: number,
  t: TFn,
): string {
  if (unit === "none") {
    return t("risks.tasks.recurrence.oneShot");
  }
  const count = Math.max(1, interval);
  if (count === 1) {
    return t(`risks.tasks.recurrence.${unit}_one`);
  }
  return t(`risks.tasks.recurrence.${unit}_other`, { count });
}

export const RECURRENCE_UNIT_OPTIONS: RecurrenceUnit[] = [
  "days",
  "weeks",
  "months",
  "years",
];
