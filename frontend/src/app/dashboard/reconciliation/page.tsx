"use client";

import React, { useState, useEffect } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR, formatDateTime } from "@/lib/utils";
import { ApiClient, ReconciliationRun } from "@/lib/api";
import {
  GitCompare,
  RefreshCw,
  Search,
  CheckCircle2,
  Clock,
  Layers,
  ChevronRight,
  SlidersHorizontal,
  X,
  ShieldCheck,
  AlertOctagon,
  ArrowRight,
  TrendingDown,
} from "lucide-react";

export default function ReconciliationWorkspacePage() {
  const [runs, setRuns] = useState<ReconciliationRun[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [selectedRun, setSelectedRun] = useState<ReconciliationRun | null>(null);
  const [triggering, setTriggering] = useState(false);
  const [searchQuery, setSearchQuery] = useState("");

  const fetchRuns = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ApiClient.listReconciliationRuns();
      setRuns(res);
      if (res.length > 0 && !selectedRun) {
        setSelectedRun(res[0]);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load reconciliation run history.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchRuns();
  }, []);

  const handleTriggerRun = async () => {
    try {
      setTriggering(true);
      const newRun = await ApiClient.triggerReconciliationRun();
      await fetchRuns();
      setSelectedRun(newRun);
    } catch (err: any) {
      alert("Failed to execute reconciliation run: " + err.message);
    } finally {
      setTriggering(false);
    }
  };

  const filteredRuns = runs.filter((r) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      r.run_number.toString().includes(q) ||
      r.id.toLowerCase().includes(q) ||
      r.status.toLowerCase().includes(q)
    );
  });

  return (
    <div className="flex flex-col min-h-screen bg-canvas">
      <Topbar
        title="Reconciliation Run Management"
        breadcrumb="Workspace"
        onRunSync={handleTriggerRun}
      />

      <main className="p-6 md:p-8 space-y-8 max-w-7xl mx-auto w-full">
        {/* Header & Run Trigger */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Immutable Ledger Run History
            </h1>
            <p className="text-xs text-ink-secondary mt-0.5">
              Deterministic correlation passes 1 through 6 with superseding allocation versioning
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Button
              onClick={fetchRuns}
              variant="outline"
              size="sm"
              disabled={loading}
              className="text-xs font-mono"
            >
              <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
            <Button
              onClick={handleTriggerRun}
              size="sm"
              disabled={triggering}
              className="text-xs font-mono"
            >
              <GitCompare className={`h-3.5 w-3.5 mr-1.5 ${triggering ? "animate-spin" : ""}`} />
              {triggering ? "Running Multi-Pass Engine..." : "Trigger Run N+1"}
            </Button>
          </div>
        </div>

        {/* Selected Run Deep-Dive Banner */}
        {selectedRun && (
          <div className="border border-border bg-surface p-6 space-y-6">
            <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
              <div className="flex items-center gap-3">
                <div className="p-2 border border-border bg-canvas">
                  <GitCompare className="h-5 w-5 text-ink-primary" />
                </div>
                <div>
                  <div className="flex items-center gap-2">
                    <h2 className="text-sm font-semibold text-ink-primary">
                      Run #{selectedRun.run_number}
                    </h2>
                    <span className="text-[10px] font-mono text-ink-muted">
                      ({selectedRun.id})
                    </span>
                    <Badge
                      variant={
                        selectedRun.status === "COMPLETED"
                          ? "matched"
                          : selectedRun.status === "COMPLETED_WITH_EXCEPTIONS"
                          ? "pending"
                          : "leakage"
                      }
                    >
                      {selectedRun.status.replace(/_/g, " ")}
                    </Badge>
                  </div>
                  <p className="text-xs text-ink-secondary mt-0.5">
                    Executed {formatDateTime(selectedRun.created_at)} • Duration:{" "}
                    {selectedRun.duration_ms ? `${selectedRun.duration_ms}ms` : "—"}
                  </p>
                </div>
              </div>

              <div className="flex items-center gap-6 text-xs font-mono">
                <div>
                  <span className="text-ink-muted block text-[10px] uppercase">Matched Bank</span>
                  <span className="font-semibold text-ink-primary text-sm">
                    {formatINR(selectedRun.total_matched_bank_amount)}
                  </span>
                </div>
                <div className="h-8 w-px bg-border" />
                <div>
                  <span className="text-ink-muted block text-[10px] uppercase">Discrepancy</span>
                  <span className="font-semibold text-status-leakage-text text-sm">
                    {formatINR(selectedRun.total_discrepancy_amount)}
                  </span>
                </div>
              </div>
            </div>

            {/* Run Quantitative Metrics Breakdown */}
            <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
              <div className="p-3 border border-border bg-canvas space-y-1">
                <span className="text-[10px] uppercase text-ink-muted block">Orders Matched</span>
                <div className="text-sm font-semibold text-ink-primary">
                  {selectedRun.matched_orders_count} / {selectedRun.total_orders_evaluated}
                </div>
                <span className="text-[11px] text-ink-secondary">
                  Total: {formatINR(selectedRun.total_order_amount)}
                </span>
              </div>

              <div className="p-3 border border-border bg-canvas space-y-1">
                <span className="text-[10px] uppercase text-ink-muted block">Payments Matched</span>
                <div className="text-sm font-semibold text-ink-primary">
                  {selectedRun.matched_payments_count} / {selectedRun.total_payments_evaluated}
                </div>
                <span className="text-[11px] text-ink-secondary">
                  Captured: {formatINR(selectedRun.total_captured_amount)}
                </span>
              </div>

              <div className="p-3 border border-border bg-canvas space-y-1">
                <span className="text-[10px] uppercase text-ink-muted block">Settlements Matched</span>
                <div className="text-sm font-semibold text-ink-primary">
                  {selectedRun.matched_settlements_count} / {selectedRun.total_settlements_evaluated}
                </div>
                <span className="text-[11px] text-ink-secondary">
                  Settled: {formatINR(selectedRun.total_settled_amount)}
                </span>
              </div>

              <div className="p-3 border border-border bg-canvas space-y-1">
                <span className="text-[10px] uppercase text-ink-muted block">Bank Credits Cleared</span>
                <div className="text-sm font-semibold text-ink-primary">
                  {selectedRun.matched_bank_txs_count} / {selectedRun.total_bank_transactions_evaluated}
                </div>
                <span className="text-[11px] text-ink-secondary">
                  Fee Drift: {formatINR(selectedRun.total_fee_drift_amount)}
                </span>
              </div>
            </div>
          </div>
        )}

        {/* Run History Table */}
        <div className="border border-border bg-surface p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-mono uppercase tracking-wider text-ink-muted">
              Historical Execution Runs ({runs.length})
            </h2>

            <div className="relative max-w-xs">
              <Search className="h-3.5 w-3.5 absolute left-3 top-2 text-ink-muted" />
              <input
                type="text"
                placeholder="Search runs..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="pl-8 pr-3 py-1 text-xs bg-canvas border border-border focus:outline-none focus:border-ink-primary font-mono"
              />
            </div>
          </div>

          <div className="border border-border overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-border bg-canvas text-ink-muted font-mono uppercase text-[10px]">
                  <th className="py-2.5 px-3">Run #</th>
                  <th className="py-2.5 px-3">Status</th>
                  <th className="py-2.5 px-3">Timestamp</th>
                  <th className="py-2.5 px-3 text-right">Orders</th>
                  <th className="py-2.5 px-3 text-right">Payments</th>
                  <th className="py-2.5 px-3 text-right">Settled Amount</th>
                  <th className="py-2.5 px-3 text-right">Matched Bank</th>
                  <th className="py-2.5 px-3 text-right">Discrepancy</th>
                  <th className="py-2.5 px-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border font-mono">
                {loading ? (
                  <tr>
                    <td colSpan={9} className="py-8 text-center text-ink-muted">
                      Loading run history...
                    </td>
                  </tr>
                ) : filteredRuns.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-8 text-center text-ink-muted">
                      No reconciliation runs executed yet. Click &quot;Trigger Run N+1&quot; to begin.
                    </td>
                  </tr>
                ) : (
                  filteredRuns.map((r) => {
                    const isSelected = selectedRun?.id === r.id;
                    return (
                      <tr
                        key={r.id}
                        className={`hover:bg-hover transition-colors ${
                          isSelected ? "bg-canvas font-semibold" : ""
                        }`}
                      >
                        <td className="py-2.5 px-3">
                          <span className="text-ink-primary font-semibold">#{r.run_number}</span>
                        </td>
                        <td className="py-2.5 px-3">
                          <Badge
                            variant={
                              r.status === "COMPLETED"
                                ? "matched"
                                : r.status === "COMPLETED_WITH_EXCEPTIONS"
                                ? "pending"
                                : "leakage"
                            }
                          >
                            {r.status}
                          </Badge>
                        </td>
                        <td className="py-2.5 px-3 text-ink-secondary text-[11px]">
                          {formatDateTime(r.created_at)}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-primary">
                          {r.matched_orders_count}/{r.total_orders_evaluated}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-primary">
                          {r.matched_payments_count}/{r.total_payments_evaluated}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-primary">
                          {formatINR(r.total_settled_amount)}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-primary font-medium">
                          {formatINR(r.total_matched_bank_amount)}
                        </td>
                        <td className="py-2.5 px-3 text-right text-status-leakage-text font-semibold">
                          {formatINR(r.total_discrepancy_amount)}
                        </td>
                        <td className="py-2.5 px-3 text-center">
                          <Button
                            onClick={() => setSelectedRun(r)}
                            variant="ghost"
                            size="sm"
                            className="text-[11px] font-mono h-6 px-2"
                          >
                            Inspect
                          </Button>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}
