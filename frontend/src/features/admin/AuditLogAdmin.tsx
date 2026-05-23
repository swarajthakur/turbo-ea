import { Fragment, useCallback, useEffect, useState } from "react";
import { useTranslation } from "react-i18next";
import Box from "@mui/material/Box";
import Typography from "@mui/material/Typography";
import Paper from "@mui/material/Paper";
import Table from "@mui/material/Table";
import TableBody from "@mui/material/TableBody";
import TableCell from "@mui/material/TableCell";
import TableContainer from "@mui/material/TableContainer";
import TableHead from "@mui/material/TableHead";
import TableRow from "@mui/material/TableRow";
import Chip from "@mui/material/Chip";
import Button from "@mui/material/Button";
import IconButton from "@mui/material/IconButton";
import Tooltip from "@mui/material/Tooltip";
import TextField from "@mui/material/TextField";
import MenuItem from "@mui/material/MenuItem";
import CircularProgress from "@mui/material/CircularProgress";
import Alert from "@mui/material/Alert";
import Dialog from "@mui/material/Dialog";
import DialogTitle from "@mui/material/DialogTitle";
import DialogContent from "@mui/material/DialogContent";
import DialogActions from "@mui/material/DialogActions";
import Accordion from "@mui/material/Accordion";
import AccordionSummary from "@mui/material/AccordionSummary";
import AccordionDetails from "@mui/material/AccordionDetails";
import Collapse from "@mui/material/Collapse";
import FormControlLabel from "@mui/material/FormControlLabel";
import Switch from "@mui/material/Switch";
import MaterialSymbol from "@/components/MaterialSymbol";
import { api, ApiError } from "@/api/client";

interface Batch {
  id: string;
  tool_name: string;
  actor_user_id: string | null;
  actor_display_name: string | null;
  origin: string;
  dry_run: boolean;
  confirm_token: string | null;
  summary: Record<string, unknown> | null;
  created_at: string;
  committed_at: string | null;
}

interface BatchEvent {
  id: string;
  event_type: string;
  data: Record<string, unknown> | null;
  card_id: string | null;
  user_id: string | null;
  user_display_name: string | null;
  created_at: string;
}

interface BatchHistory {
  batch: Batch;
  events: BatchEvent[];
}

interface RollbackOp {
  event_id: string;
  op: string;
  card_id?: string;
  relation_id?: string;
  fields?: Record<string, unknown>;
  event_type?: string;
  reason?: string;
  status?: string;
}

interface RollbackPlan {
  dry_run?: boolean;
  batch: Batch;
  operations: RollbackOp[];
  unsupported_events: RollbackOp[];
  event_count: number;
}

interface ConflictingBatch {
  batch_id: string;
  tool_name: string;
  created_at: string;
  touched_entities: string[];
}

function originColor(origin: string): "default" | "primary" | "secondary" | "warning" {
  if (origin === "mcp") return "warning";
  if (origin === "web") return "primary";
  return "default";
}

function StatusChip({ batch }: { batch: Batch }) {
  if (batch.dry_run && !batch.committed_at) {
    return <Chip size="small" label="Dry-run only" color="default" variant="outlined" />;
  }
  if (batch.committed_at) {
    return <Chip size="small" label="Committed" color="success" variant="outlined" />;
  }
  return <Chip size="small" label="Open" color="warning" variant="outlined" />;
}

// ── Rollback dialog ────────────────────────────────────────────────────────

function RollbackDialog({
  batch,
  open,
  onClose,
  onCompleted,
}: {
  batch: Batch | null;
  open: boolean;
  onClose: () => void;
  onCompleted: () => void;
}) {
  const [loadingPlan, setLoadingPlan] = useState(false);
  const [plan, setPlan] = useState<RollbackPlan | null>(null);
  const [conflicts, setConflicts] = useState<ConflictingBatch[]>([]);
  const [force, setForce] = useState(false);
  const [committing, setCommitting] = useState(false);
  const [error, setError] = useState("");
  const [committedResult, setCommittedResult] = useState<unknown>(null);

  useEffect(() => {
    if (!open || !batch) return;
    setPlan(null);
    setConflicts([]);
    setError("");
    setCommittedResult(null);
    setForce(false);
    setLoadingPlan(true);
    (async () => {
      try {
        const p = await api.post<RollbackPlan>(
          `/mutation-batches/${batch.id}/rollback`,
          { dry_run: true, force: false },
        );
        setPlan(p);
      } catch (err) {
        if (err instanceof ApiError) {
          const detail = err.detail as
            | { error?: string; conflicting_batches?: ConflictingBatch[]; message?: string }
            | undefined;
          if (detail?.error === "rollback_conflict") {
            setConflicts(detail.conflicting_batches ?? []);
            setError(detail.message ?? "Conflicts detected.");
          } else {
            setError(err.message);
          }
        } else {
          setError(String(err));
        }
      } finally {
        setLoadingPlan(false);
      }
    })();
  }, [open, batch]);

  const commit = useCallback(async () => {
    if (!batch) return;
    setCommitting(true);
    setError("");
    try {
      const result = await api.post(
        `/mutation-batches/${batch.id}/rollback`,
        { dry_run: false, force },
      );
      setCommittedResult(result);
      onCompleted();
    } catch (err) {
      if (err instanceof ApiError) {
        const detail = err.detail as
          | { error?: string; conflicting_batches?: ConflictingBatch[]; message?: string }
          | undefined;
        if (detail?.error === "rollback_conflict") {
          setConflicts(detail.conflicting_batches ?? []);
          setError(detail.message ?? "Conflicts detected.");
        } else {
          setError(err.message);
        }
      } else {
        setError(String(err));
      }
    } finally {
      setCommitting(false);
    }
  }, [batch, force, onCompleted]);

  return (
    <Dialog open={open} onClose={onClose} maxWidth="md" fullWidth>
      <DialogTitle>
        Roll back batch {batch?.id?.slice(0, 8)}…{" "}
        <Typography component="span" variant="body2" color="text.secondary">
          ({batch?.tool_name})
        </Typography>
      </DialogTitle>
      <DialogContent dividers>
        {loadingPlan && (
          <Box sx={{ display: "flex", justifyContent: "center", py: 4 }}>
            <CircularProgress />
          </Box>
        )}

        {committedResult ? (
          <Alert severity="success">
            Rollback committed. {plan?.operations?.length ?? 0} operation
            {(plan?.operations?.length ?? 0) === 1 ? "" : "s"} applied.
          </Alert>
        ) : (
          <>
            {error && (
              <Alert severity={conflicts.length ? "warning" : "error"} sx={{ mb: 2 }}>
                {error}
              </Alert>
            )}

            {conflicts.length > 0 && (
              <Box sx={{ mb: 2 }}>
                <Typography variant="subtitle2" gutterBottom>
                  Later batches modified the same entities:
                </Typography>
                <TableContainer component={Paper} variant="outlined">
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Batch</TableCell>
                        <TableCell>Tool</TableCell>
                        <TableCell>When</TableCell>
                        <TableCell>Touched</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {conflicts.map((c) => (
                        <TableRow key={c.batch_id}>
                          <TableCell>
                            <code>{c.batch_id.slice(0, 8)}…</code>
                          </TableCell>
                          <TableCell>{c.tool_name}</TableCell>
                          <TableCell>
                            {new Date(c.created_at).toLocaleString()}
                          </TableCell>
                          <TableCell>{c.touched_entities.length}</TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>
                <FormControlLabel
                  sx={{ mt: 1 }}
                  control={
                    <Switch
                      checked={force}
                      onChange={(e) => setForce(e.target.checked)}
                    />
                  }
                  label="Force rollback (overwrites the later batches' changes)"
                />
              </Box>
            )}

            {plan && (
              <>
                <Typography variant="subtitle2" gutterBottom>
                  Inverse-op plan ({plan.operations.length} operation
                  {plan.operations.length === 1 ? "" : "s"})
                </Typography>
                <TableContainer component={Paper} variant="outlined" sx={{ mb: 2 }}>
                  <Table size="small">
                    <TableHead>
                      <TableRow>
                        <TableCell>Op</TableCell>
                        <TableCell>Target</TableCell>
                        <TableCell>Detail</TableCell>
                      </TableRow>
                    </TableHead>
                    <TableBody>
                      {plan.operations.map((op) => (
                        <TableRow key={op.event_id}>
                          <TableCell>
                            <code>{op.op}</code>
                          </TableCell>
                          <TableCell>
                            <code>
                              {(op.card_id || op.relation_id || "—").slice(0, 8)}…
                            </code>
                          </TableCell>
                          <TableCell>
                            {op.fields ? (
                              <code style={{ fontSize: 11 }}>
                                {Object.keys(op.fields).join(", ")}
                              </code>
                            ) : (
                              "—"
                            )}
                          </TableCell>
                        </TableRow>
                      ))}
                    </TableBody>
                  </Table>
                </TableContainer>

                {plan.unsupported_events.length > 0 && (
                  <Alert severity="info" sx={{ mb: 2 }}>
                    {plan.unsupported_events.length} event(s) cannot be reversed
                    automatically (no structured snapshot recorded). These will be
                    left in place:{" "}
                    {Array.from(
                      new Set(plan.unsupported_events.map((e) => e.event_type ?? "?")),
                    ).join(", ")}
                  </Alert>
                )}
              </>
            )}
          </>
        )}
      </DialogContent>
      <DialogActions>
        <Button onClick={onClose}>
          {committedResult ? "Close" : "Cancel"}
        </Button>
        {!committedResult && plan && (
          <Button
            onClick={commit}
            variant="contained"
            color="error"
            disabled={committing || (conflicts.length > 0 && !force)}
            startIcon={
              committing ? (
                <CircularProgress size={16} color="inherit" />
              ) : (
                <MaterialSymbol icon="undo" />
              )
            }
          >
            {committing ? "Rolling back…" : force ? "Force rollback" : "Roll back"}
          </Button>
        )}
      </DialogActions>
    </Dialog>
  );
}

// ── Batch detail (events) ──────────────────────────────────────────────────

function BatchEvents({ batchId }: { batchId: string }) {
  const [history, setHistory] = useState<BatchHistory | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    setLoading(true);
    api
      .get<BatchHistory>(`/mutation-batches/${batchId}/events`)
      .then(setHistory)
      .catch((err) => setError(err instanceof Error ? err.message : String(err)))
      .finally(() => setLoading(false));
  }, [batchId]);

  if (loading) {
    return (
      <Box sx={{ py: 2, display: "flex", justifyContent: "center" }}>
        <CircularProgress size={20} />
      </Box>
    );
  }
  if (error) return <Alert severity="error">{error}</Alert>;
  if (!history) return null;

  return (
    <Box>
      <Typography variant="caption" color="text.secondary">
        {history.events.length} event{history.events.length === 1 ? "" : "s"}
      </Typography>
      <TableContainer component={Paper} variant="outlined" sx={{ mt: 1 }}>
        <Table size="small">
          <TableHead>
            <TableRow>
              <TableCell>When</TableCell>
              <TableCell>Event</TableCell>
              <TableCell>Card</TableCell>
              <TableCell>Data</TableCell>
            </TableRow>
          </TableHead>
          <TableBody>
            {history.events.map((e) => (
              <TableRow key={e.id}>
                <TableCell sx={{ whiteSpace: "nowrap" }}>
                  {new Date(e.created_at).toLocaleTimeString()}
                </TableCell>
                <TableCell>
                  <code>{e.event_type}</code>
                </TableCell>
                <TableCell>
                  {e.card_id ? <code>{e.card_id.slice(0, 8)}…</code> : "—"}
                </TableCell>
                <TableCell sx={{ fontSize: 11, maxWidth: 360, overflow: "hidden" }}>
                  <code>{JSON.stringify(e.data)}</code>
                </TableCell>
              </TableRow>
            ))}
          </TableBody>
        </Table>
      </TableContainer>
    </Box>
  );
}

// ── Main page ──────────────────────────────────────────────────────────────

export default function AuditLogAdmin() {
  const { t } = useTranslation(["admin", "common"]);
  const [batches, setBatches] = useState<Batch[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [originFilter, setOriginFilter] = useState<string>("");
  const [toolFilter, setToolFilter] = useState<string>("");
  const [expanded, setExpanded] = useState<string | null>(null);
  const [rollbackTarget, setRollbackTarget] = useState<Batch | null>(null);

  const load = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const params = new URLSearchParams({ limit: "100" });
      if (originFilter) params.set("origin", originFilter);
      if (toolFilter) params.set("tool_name", toolFilter);
      const data = await api.get<Batch[]>(`/mutation-batches?${params.toString()}`);
      setBatches(data);
    } catch (err) {
      setError(err instanceof Error ? err.message : String(err));
    } finally {
      setLoading(false);
    }
  }, [originFilter, toolFilter]);

  useEffect(() => {
    load();
  }, [load]);

  return (
    <Box>
      <Box sx={{ display: "flex", alignItems: "center", gap: 1, mb: 2 }}>
        <MaterialSymbol icon="history" size={24} />
        <Typography variant="h6">{t("settings.tabs.auditLog", "Audit log")}</Typography>
        <Box sx={{ flex: 1 }} />
        <Tooltip title={t("common.refresh", "Refresh")}>
          <IconButton size="small" onClick={load} disabled={loading}>
            <MaterialSymbol icon="refresh" />
          </IconButton>
        </Tooltip>
      </Box>

      <Typography variant="body2" color="text.secondary" sx={{ mb: 2 }}>
        Every mutating MCP / API / web write opens a <em>mutation batch</em>. Use
        this view to inspect what changed, by whom, when, and from where — and to
        roll back an AI-driven batch that landed wrong.
      </Typography>

      <Paper variant="outlined" sx={{ p: 2, mb: 2, display: "flex", gap: 2, flexWrap: "wrap" }}>
        <TextField
          select
          label="Origin"
          value={originFilter}
          onChange={(e) => setOriginFilter(e.target.value)}
          size="small"
          sx={{ minWidth: 140 }}
        >
          <MenuItem value="">All</MenuItem>
          <MenuItem value="mcp">MCP (AI agent)</MenuItem>
          <MenuItem value="web">Web UI</MenuItem>
          <MenuItem value="api">API</MenuItem>
        </TextField>
        <TextField
          label="Tool name"
          value={toolFilter}
          onChange={(e) => setToolFilter(e.target.value)}
          size="small"
          placeholder="e.g. create_cards_bulk"
          sx={{ minWidth: 240 }}
        />
      </Paper>

      {error && (
        <Alert severity="error" sx={{ mb: 2 }}>
          {error}
        </Alert>
      )}

      {loading ? (
        <Box sx={{ py: 4, display: "flex", justifyContent: "center" }}>
          <CircularProgress />
        </Box>
      ) : batches.length === 0 ? (
        <Alert severity="info">No mutation batches match these filters.</Alert>
      ) : (
        <TableContainer component={Paper} variant="outlined">
          <Table size="small">
            <TableHead>
              <TableRow>
                <TableCell />
                <TableCell>When</TableCell>
                <TableCell>Tool</TableCell>
                <TableCell>Origin</TableCell>
                <TableCell>Actor</TableCell>
                <TableCell>Status</TableCell>
                <TableCell align="right">Actions</TableCell>
              </TableRow>
            </TableHead>
            <TableBody>
              {batches.map((b) => {
                const isOpen = expanded === b.id;
                const canRollback = !!b.committed_at;
                return (
                  <Fragment key={b.id}>
                    <TableRow hover>
                      <TableCell sx={{ width: 40 }}>
                        <IconButton
                          size="small"
                          onClick={() => setExpanded(isOpen ? null : b.id)}
                        >
                          <MaterialSymbol
                            icon={isOpen ? "keyboard_arrow_down" : "keyboard_arrow_right"}
                          />
                        </IconButton>
                      </TableCell>
                      <TableCell sx={{ whiteSpace: "nowrap" }}>
                        {new Date(b.created_at).toLocaleString()}
                      </TableCell>
                      <TableCell>
                        <code>{b.tool_name}</code>
                      </TableCell>
                      <TableCell>
                        <Chip
                          size="small"
                          label={b.origin}
                          color={originColor(b.origin)}
                          variant={b.origin === "mcp" ? "filled" : "outlined"}
                        />
                      </TableCell>
                      <TableCell>{b.actor_display_name ?? "—"}</TableCell>
                      <TableCell>
                        <StatusChip batch={b} />
                      </TableCell>
                      <TableCell align="right">
                        <Tooltip
                          title={
                            canRollback
                              ? "Reverse every write in this batch"
                              : "Dry-run / uncommitted batches have nothing to roll back"
                          }
                        >
                          <span>
                            <Button
                              size="small"
                              color="error"
                              disabled={!canRollback}
                              onClick={() => setRollbackTarget(b)}
                              startIcon={<MaterialSymbol icon="undo" />}
                            >
                              Roll back
                            </Button>
                          </span>
                        </Tooltip>
                      </TableCell>
                    </TableRow>
                    <TableRow>
                      <TableCell colSpan={7} sx={{ p: 0, border: 0 }}>
                        <Collapse in={isOpen} unmountOnExit>
                          <Box sx={{ p: 2, bgcolor: "action.hover" }}>
                            {isOpen && <BatchEvents batchId={b.id} />}
                          </Box>
                        </Collapse>
                      </TableCell>
                    </TableRow>
                  </Fragment>
                );
              })}
            </TableBody>
          </Table>
        </TableContainer>
      )}

      <RollbackDialog
        batch={rollbackTarget}
        open={rollbackTarget !== null}
        onClose={() => setRollbackTarget(null)}
        onCompleted={() => {
          // Refresh the list so the new rollback batch shows up and the
          // original's row reflects whatever new state the conflict
          // scan picked up.
          load();
        }}
      />
    </Box>
  );
}
