/**
 * Read-only audit list for a task's past occurrences.
 *
 * One block per cycle, showing **both** the originally-scheduled due
 * date and the actual completion (or skip) timestamp. The owner snapshot
 * (``owner_at_completion``) is rendered alongside the completer so the
 * audit trail survives owner rotation.
 *
 * Recurring controls accumulate many cycles over the years. We render
 * the latest 5 by default and offer "Show {N} older" to expand the
 * full history — keeps the inline experience tidy and shifts the bulk
 * read to the per-task Excel export button on the parent panel.
 */
import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import Box from "@mui/material/Box";
import Button from "@mui/material/Button";
import Stack from "@mui/material/Stack";
import Typography from "@mui/material/Typography";
import MaterialSymbol from "@/components/MaterialSymbol";
import type { MitigationTask, MitigationTaskOccurrence } from "@/types";
import { activationDate } from "./leadTime";

interface Props {
  occurrences: MitigationTaskOccurrence[];
  /** Lead-time on the parent task. Optional for backwards compat with
   *  callers that don't render scheduled rows (e.g. test fixtures); when
   *  omitted, scheduled cycles still render but without the "Activates
   *  on" sub-line. */
  leadTimeDays?: MitigationTask["lead_time_days"];
}

const COLLAPSED_LIMIT = 5;

function formatDateTime(iso: string | null): string {
  if (!iso) return "—";
  try {
    return new Date(iso).toLocaleString();
  } catch {
    return iso;
  }
}

export default function OccurrenceHistoryList({ occurrences, leadTimeDays }: Props) {
  const { t } = useTranslation("delivery");
  const [expanded, setExpanded] = useState(false);

  const sorted = useMemo(
    () => [...occurrences].sort((a, b) => b.sequence - a.sequence),
    [occurrences],
  );

  if (sorted.length === 0) {
    return (
      <Typography variant="body2" color="text.secondary">
        {t("risks.tasks.history.empty")}
      </Typography>
    );
  }

  const visible = expanded ? sorted : sorted.slice(0, COLLAPSED_LIMIT);
  const hiddenCount = sorted.length - visible.length;

  return (
    <Stack spacing={1.5}>
      {visible.map((occ) => {
        const isOpen = occ.status === "open";
        const isScheduled = occ.status === "scheduled";
        const icon =
          occ.status === "done"
            ? "check_circle"
            : occ.status === "skipped"
              ? "skip_next"
              : occ.status === "scheduled"
                ? "event_upcoming"
                : "schedule";
        const color =
          occ.status === "done"
            ? "success.main"
            : occ.status === "skipped"
              ? "warning.main"
              : "text.secondary";
        const closeLabelKey =
          occ.status === "skipped"
            ? "risks.tasks.history.skippedLabel"
            : "risks.tasks.history.completedLabel";
        const activatesOn = isScheduled
          ? activationDate(occ.due_date, leadTimeDays ?? 0)
          : null;
        return (
          <Box
            key={occ.id}
            id={`occurrence-${occ.id}`}
            sx={{
              display: "flex",
              gap: 1.5,
              alignItems: "flex-start",
              p: 1,
              borderRadius: 1,
              border: 1,
              borderColor: "divider",
            }}
          >
            <Box sx={{ color, pt: 0.25 }}>
              <MaterialSymbol icon={icon} size={20} />
            </Box>
            <Stack spacing={0.25} sx={{ flex: 1, minWidth: 0 }}>
              <Stack direction="row" spacing={1} alignItems="baseline" flexWrap="wrap">
                <Typography variant="body2" fontWeight={600}>
                  {t("risks.tasks.history.cycleLabel", { sequence: occ.sequence })}
                </Typography>
                <Typography variant="caption" color="text.secondary">
                  {t(`risks.tasks.status.${occ.status}`)}
                </Typography>
              </Stack>
              {/* Target date — always render for cycles that have one
                  so auditors can compare scheduled vs. actual. */}
              <Typography variant="caption" color="text.secondary">
                {t("risks.tasks.history.targetLabel")}: {occ.due_date ?? "—"}
              </Typography>
              {isScheduled ? (
                <>
                  {activatesOn && (
                    <Typography variant="caption" color="text.secondary">
                      {t("risks.tasks.history.activatesOn", { date: activatesOn })}
                    </Typography>
                  )}
                  <Typography variant="caption" color="text.secondary">
                    {occ.assigned_owner_name
                      ? t("risks.tasks.history.assignedTo", {
                          name: occ.assigned_owner_name,
                        })
                      : t("risks.tasks.history.unassigned")}
                  </Typography>
                </>
              ) : isOpen ? (
                <>
                  {occ.activated_at && (
                    <Typography variant="caption" color="text.secondary">
                      {t("risks.tasks.history.activatedOn", {
                        timestamp: formatDateTime(occ.activated_at),
                      })}
                    </Typography>
                  )}
                  <Typography variant="caption" color="text.secondary">
                    {occ.assigned_owner_name
                      ? t("risks.tasks.history.assignedTo", {
                          name: occ.assigned_owner_name,
                        })
                      : t("risks.tasks.history.unassigned")}
                  </Typography>
                </>
              ) : (
                <>
                  <Typography variant="caption" color="text.secondary">
                    {t(closeLabelKey)}: {formatDateTime(occ.completed_at)}
                  </Typography>
                  <Typography variant="caption" color="text.secondary">
                    {t("risks.tasks.history.completedBy", {
                      name: occ.completed_by_name ?? "—",
                      owner: occ.owner_at_completion_name ?? "—",
                    })}
                  </Typography>
                </>
              )}
              {occ.completion_notes && (
                <Typography
                  variant="body2"
                  sx={{ mt: 0.5, whiteSpace: "pre-wrap", color: "text.primary" }}
                >
                  {occ.completion_notes}
                </Typography>
              )}
            </Stack>
          </Box>
        );
      })}
      {hiddenCount > 0 && (
        <Box>
          <Button
            size="small"
            startIcon={<MaterialSymbol icon="expand_more" size={16} />}
            onClick={() => setExpanded(true)}
          >
            {t("risks.tasks.history.showOlder", { count: hiddenCount })}
          </Button>
        </Box>
      )}
      {expanded && sorted.length > COLLAPSED_LIMIT && (
        <Box>
          <Button
            size="small"
            startIcon={<MaterialSymbol icon="expand_less" size={16} />}
            onClick={() => setExpanded(false)}
          >
            {t("risks.tasks.history.collapse")}
          </Button>
        </Box>
      )}
    </Stack>
  );
}
