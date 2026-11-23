"use client";

import React, { useState, useEffect } from "react";
import Link from "next/link";
import {
  ShieldCheck,
  AlertTriangle,
  ArrowRight,
  TrendingDown,
  CheckCircle2,
  Clock,
  Layers,
  FileSpreadsheet,
  AlertOctagon,
  Radar,
  ArrowUpRight,
  RefreshCw,
  TrendingUp,
  FileText,
  Sliders,
  DollarSign,
  Activity,
  Sparkles,
} from "lucide-react";
import { Topbar } from "@/components/shell/Topbar";
import { MetricCard } from "@/components/ui/MetricCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR, formatDateTime } from "@/lib/utils";
import { ApiClient, DashboardOverview } from "@/lib/api";

export default function OverviewDashboardPage() {
  const [data, setData] = useState<DashboardOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [syncing, setSyncing] = useState(false);

  const fetchOverview = async () => {
    try {
      setLoading(true);
      setError(null);
      const overview = await ApiClient.getDashboardOverview();
      setData(overview);
    } catch (err: any) {
      console.error("Failed to load dashboard overview:", err);
      setError(err.message || "Failed to load financial overview from backend.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchOverview();
  }, []);

  const handleRunSync = async () => {
    try {
      setSyncing(true);
      await ApiClient.triggerReconciliationRun();
      await fetchOverview();
    } catch (err: any) {
      alert("Failed to run reconciliation: " + err.message);
    } finally {
      setSyncing(false);
    }
  };

  if (loading && !data) {
    return (
      <div className="flex flex-col min-h-screen">
        <Topbar title="Executive Overview" breadcrumb="Workspace" />
        <div className="p-8 space-y-6 animate-pulse">
          <div className="h-20 bg-muted/20 rounded border border-border" />
          <div className="grid grid-cols-1 md:grid-cols-4 gap-4">
            {[1, 2, 3, 4, 5, 6, 7, 8].map((i) => (
              <div key={i} className="h-28 bg-muted/10 rounded border border-border" />
            ))}
          </div>
          <div className="h-64 bg-muted/10 rounded border border-border" />
        </div>
      </div>
    );
  }

  if (error && !data) {
    return (
      <div className="flex flex-col min-h-screen">
        <Topbar title="Executive Overview" breadcrumb="Workspace" />
        <div className="p-8">
          <div className="p-6 border border-status-leakage-text/30 bg-status-leakage-bg rounded max-w-2xl">
            <div className="flex items-center gap-3 text-status-leakage-text font-medium mb-2">
              <AlertOctagon className="h-5 w-5" />
              <span>Backend Connection Error</span>
            </div>
            <p className="text-sm text-ink-secondary mb-4">{error}</p>
            <Button onClick={fetchOverview} variant="outline" size="sm">
              <RefreshCw className="h-3.5 w-3.5 mr-2" /> Retry Connection
            </Button>
          </div>
        </div>
      </div>
    );
  }

  const overview = data!;
  const flow = overview.flow;

  return (
    <div className="flex flex-col min-h-screen bg-canvas">
      <Topbar
        title="Executive Overview"
        breadcrumb="Workspace"
        onRunSync={handleRunSync}
      />

      <div className="p-6 md:p-8 space-y-8 max-w-7xl">
        {/* Banner: Latest Run Status & Enterprise Tenant Scope */}
        <div className="border border-border bg-surface p-4 flex flex-col md:flex-row md:items-center justify-between gap-4">
          <div className="flex items-center gap-3">
            <div className="p-2 border border-border bg-canvas">
              <ShieldCheck className="h-5 w-5 text-ink-primary" strokeWidth={1.5} />
            </div>
            <div>
              <div className="flex items-center gap-2">
                <h2 className="text-sm font-semibold tracking-tight text-ink-primary">
                  {overview.tenant_name}
                </h2>
                <span className="text-[10px] font-mono px-1.5 py-0.5 border border-border bg-canvas text-ink-secondary">
                  {overview.currency}
                </span>
                {overview.latest_run_number ? (
                  <Badge variant="matched">Run #{overview.latest_run_number}</Badge>
                ) : (
                  <Badge variant="pending">No Prior Run</Badge>
                )}
              </div>
              <p className="text-xs text-ink-secondary mt-0.5">
                Deterministic Three-Way Financial Ledger Audit • Zero Float Floating-Point Arithmetic
              </p>
            </div>
          </div>

          <div className="flex items-center gap-4 text-xs">
            <div className="text-right">
              <span className="text-ink-muted block text-[10px] uppercase font-mono">
                Reconciliation Accuracy
              </span>
              <span className="font-mono font-semibold text-ink-primary text-sm">
                {overview.reconciliation_accuracy_percentage}%
              </span>
            </div>
            <div className="h-8 w-px bg-border hidden md:block" />
            <Button
              onClick={handleRunSync}
              disabled={syncing}
              size="sm"
              variant="outline"
              className="text-xs font-mono"
            >
              <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${syncing ? "animate-spin" : ""}`} />
              {syncing ? "Executing 3-Way Pass..." : "Trigger Reconciliation Run"}
            </Button>
          </div>
        </div>

        {/* 1. Executive Overview Metric Grid (Module A) */}
        <div className="space-y-3">
          <div className="flex items-center justify-between">
            <h3 className="text-xs font-mono uppercase tracking-wider text-ink-muted">
              Authoritative Financial Ledger Totals
            </h3>
            <span className="text-[11px] text-ink-muted">
              Source: PostgreSQL NUMERIC(18,4)
            </span>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3">
            <MetricCard
              label="Shopify Orders Evaluated"
              value={overview.total_orders_count.toLocaleString("en-IN")}
              subtext={`Gross: ${formatINR(overview.total_orders_amount)}`}
              isMonetary={false}
            />
            <MetricCard
              label="Gateway Gross Captures"
              value={formatINR(overview.total_captured_amount)}
              subtext={`${overview.total_captured_count} captured transactions`}
              isMonetary={true}
            />
            <MetricCard
              label="Gateway Settlements"
              value={formatINR(overview.total_settled_amount)}
              subtext={`${overview.total_settlements_count} batch settlements`}
              isMonetary={true}
            />
            <MetricCard
              label="HDFC Bank Credits"
              value={formatINR(overview.total_bank_credited_amount)}
              subtext={`${overview.total_bank_credits_count} bank credits cleared`}
              isMonetary={true}
            />
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 pt-2">
            <MetricCard
              label="Successfully Reconciled"
              value={formatINR(overview.reconciled_amount)}
              subtext="Matched across 3 independent ledgers"
              isMonetary={true}
              status="matched"
            />
            <MetricCard
              label="Unmatched Variance"
              value={formatINR(overview.unmatched_amount)}
              subtext="Pending allocation or investigation"
              isMonetary={true}
              status={Number(overview.unmatched_amount) > 0 ? "pending" : "default"}
            />
            <MetricCard
              label="Detected Revenue Leakage"
              value={formatINR(overview.total_detected_leakage)}
              subtext={`${overview.leakage_findings_count} findings across 4 detectors`}
              isMonetary={true}
              status={Number(overview.total_detected_leakage) > 0 ? "leakage" : "matched"}
            />
            <MetricCard
              label="Review Queue Items"
              value={overview.pending_review_count.toString()}
              subtext="Ambiguous matches requiring review"
              isMonetary={false}
              status={overview.pending_review_count > 0 ? "pending" : "matched"}
            />
          </div>
        </div>

        {/* 2. Visual Three-Way Reconciliation Flow (Module B) */}
        <div className="border border-border bg-surface p-6 space-y-6">
          <div className="flex items-center justify-between border-b border-border pb-4">
            <div>
              <h3 className="text-sm font-semibold text-ink-primary tracking-tight">
                Three-Way Financial Reconciliation Flow
              </h3>
              <p className="text-xs text-ink-secondary mt-0.5">
                Shopify Orders → Razorpay Payments → Gateway Settlements → HDFC Bank Credits
              </p>
            </div>
            <Link
              href="/dashboard/reconciliation"
              className="text-xs font-mono text-ink-primary hover:underline flex items-center gap-1"
            >
              <span>Inspect Pass Engine</span>
              <ArrowRight className="h-3 w-3" />
            </Link>
          </div>

          <div className="grid grid-cols-1 md:grid-cols-4 gap-4 relative">
            {/* Step 1: Shopify */}
            <div className="p-4 border border-border bg-canvas space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono uppercase tracking-wider text-ink-muted">
                  STAGE 1 • OMS
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 border border-border text-ink-secondary">
                  Shopify
                </span>
              </div>
              <div>
                <div className="text-lg font-mono font-semibold text-ink-primary">
                  {formatINR(flow.shopify_orders.total_amount)}
                </div>
                <div className="text-xs text-ink-secondary mt-0.5">
                  {flow.shopify_orders.total_count} Orders Processed
                </div>
              </div>
              <div className="pt-2 border-t border-border flex justify-between text-[11px] font-mono">
                <span className="text-ink-secondary">Matched: {formatINR(flow.shopify_orders.matched_amount)}</span>
                <span className="text-status-pending-text">Unmatched: {formatINR(flow.shopify_orders.unmatched_amount)}</span>
              </div>
            </div>

            {/* Step 2: Razorpay Captures */}
            <div className="p-4 border border-border bg-canvas space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono uppercase tracking-wider text-ink-muted">
                  STAGE 2 • GATEWAY
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 border border-border text-ink-secondary">
                  Razorpay
                </span>
              </div>
              <div>
                <div className="text-lg font-mono font-semibold text-ink-primary">
                  {formatINR(flow.razorpay_payments.total_amount)}
                </div>
                <div className="text-xs text-ink-secondary mt-0.5">
                  {flow.razorpay_payments.total_count} Captures Processed
                </div>
              </div>
              <div className="pt-2 border-t border-border flex justify-between text-[11px] font-mono">
                <span className="text-ink-secondary">Matched: {formatINR(flow.razorpay_payments.matched_amount)}</span>
                <span className="text-status-pending-text">Unmatched: {formatINR(flow.razorpay_payments.unmatched_amount)}</span>
              </div>
            </div>

            {/* Step 3: Settlements */}
            <div className="p-4 border border-border bg-canvas space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono uppercase tracking-wider text-ink-muted">
                  STAGE 3 • NODAL BATCH
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 border border-border text-ink-secondary">
                  Settlements
                </span>
              </div>
              <div>
                <div className="text-lg font-mono font-semibold text-ink-primary">
                  {formatINR(flow.gateway_settlements.total_amount)}
                </div>
                <div className="text-xs text-ink-secondary mt-0.5">
                  {flow.gateway_settlements.total_count} Batches Created
                </div>
              </div>
              <div className="pt-2 border-t border-border flex justify-between text-[11px] font-mono">
                <span className="text-ink-secondary">Matched: {formatINR(flow.gateway_settlements.matched_amount)}</span>
                <span className="text-status-pending-text">Unmatched: {formatINR(flow.gateway_settlements.unmatched_amount)}</span>
              </div>
            </div>

            {/* Step 4: Bank Credits */}
            <div className="p-4 border border-border bg-canvas space-y-3">
              <div className="flex items-center justify-between">
                <span className="text-[10px] font-mono uppercase tracking-wider text-ink-muted">
                  STAGE 4 • CURRENT A/C
                </span>
                <span className="text-[10px] font-mono px-1.5 py-0.5 border border-border text-ink-secondary">
                  HDFC Bank
                </span>
              </div>
              <div>
                <div className="text-lg font-mono font-semibold text-ink-primary">
                  {formatINR(flow.hdfc_bank_credits.total_amount)}
                </div>
                <div className="text-xs text-ink-secondary mt-0.5">
                  {flow.hdfc_bank_credits.total_count} Credits Verified
                </div>
              </div>
              <div className="pt-2 border-t border-border flex justify-between text-[11px] font-mono">
                <span className="text-ink-secondary">Matched: {formatINR(flow.hdfc_bank_credits.matched_amount)}</span>
                <span className="text-status-pending-text">Unmatched: {formatINR(flow.hdfc_bank_credits.unmatched_amount)}</span>
              </div>
            </div>
          </div>
        </div>

        {/* 3. Revenue Leakage Monitoring Breakdown (Module C) */}
        <div className="grid grid-cols-1 lg:grid-cols-3 gap-6">
          {/* Leakage by Category */}
          <div className="lg:col-span-2 border border-border bg-surface p-6 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div className="flex items-center gap-2">
                <Radar className="h-4 w-4 text-status-leakage-text" strokeWidth={1.5} />
                <h3 className="text-sm font-semibold text-ink-primary">
                  Revenue Leakage by Core Detector
                </h3>
              </div>
              <Link
                href="/dashboard/leakage-detection"
                className="text-xs font-mono text-ink-secondary hover:text-ink-primary flex items-center gap-1"
              >
                <span>View Findings ({overview.leakage_findings_count})</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>

            <div className="space-y-3">
              {overview.leakage_by_category.map((cat) => (
                <div
                  key={cat.category}
                  className="p-3 border border-border bg-canvas flex items-center justify-between"
                >
                  <div className="space-y-1">
                    <div className="text-xs font-medium text-ink-primary">
                      {cat.display_name}
                    </div>
                    <div className="text-[11px] text-ink-muted font-mono">
                      {cat.count} Exceptions Identified
                    </div>
                  </div>
                  <div className="text-right">
                    <div className="text-sm font-mono font-semibold text-status-leakage-text">
                      {formatINR(cat.total_amount)}
                    </div>
                    <span className="text-[10px] text-ink-muted">Verified Delta</span>
                  </div>
                </div>
              ))}
            </div>
          </div>

          {/* Severity & AI Status */}
          <div className="space-y-6">
            <div className="border border-border bg-surface p-6 space-y-4">
              <div className="flex items-center justify-between border-b border-border pb-3">
                <h3 className="text-sm font-semibold text-ink-primary">
                  Leakage Severity Triage
                </h3>
                <span className="text-[10px] font-mono text-ink-muted">PRIORITY</span>
              </div>

              <div className="space-y-3">
                {overview.leakage_by_severity.map((sev) => {
                  const isHigh = sev.severity === "HIGH";
                  const isMed = sev.severity === "MEDIUM";
                  return (
                    <div
                      key={sev.severity}
                      className="p-3 border border-border bg-canvas flex items-center justify-between"
                    >
                      <div className="flex items-center gap-2">
                        <span
                          className={`h-2 w-2 rounded-full ${
                            isHigh
                              ? "bg-status-leakage-text"
                              : isMed
                              ? "bg-status-pending-text"
                              : "bg-ink-secondary"
                          }`}
                        />
                        <span className="text-xs font-mono text-ink-primary">
                          {sev.severity} SEVERITY
                        </span>
                      </div>
                      <div className="text-right">
                        <span className="text-xs font-mono font-semibold text-ink-primary block">
                          {formatINR(sev.total_amount)}
                        </span>
                        <span className="text-[10px] text-ink-muted">
                          {sev.count} Cases
                        </span>
                      </div>
                    </div>
                  );
                })}
              </div>
            </div>

            {/* AI Forensic Readiness Card (Module H) */}
            <div className="border border-border bg-surface p-5 space-y-3">
              <div className="flex items-center justify-between">
                <div className="flex items-center gap-2">
                  <Sparkles className="h-4 w-4 text-ink-primary" strokeWidth={1.5} />
                  <span className="text-xs font-semibold text-ink-primary">
                    AI Forensic Investigator
                  </span>
                </div>
                <span className="text-[10px] font-mono px-1.5 py-0.5 border border-border text-ink-secondary bg-canvas">
                  Gemini 2.0
                </span>
              </div>
              <p className="text-xs text-ink-secondary leading-relaxed">
                Platform interface integrated. External LLM key provisioning is pending;
                forensic calculation runs 100% deterministically in the local core engine.
              </p>
              <Link
                href="/dashboard/investigations"
                className="text-xs font-mono text-ink-primary hover:underline flex items-center gap-1 pt-1"
              >
                <span>View AI Module Status</span>
                <ArrowRight className="h-3 w-3" />
              </Link>
            </div>
          </div>
        </div>

        {/* 4. Quick Navigation Bar */}
        <div className="grid grid-cols-2 md:grid-cols-4 gap-3 pt-2">
          <Link
            href="/dashboard/reconciliation"
            className="p-3 border border-border bg-surface hover:bg-hover transition-colors flex items-center justify-between text-xs"
          >
            <span className="font-medium text-ink-primary">Reconciliation Engine</span>
            <ArrowRight className="h-3.5 w-3.5 text-ink-secondary" />
          </Link>
          <Link
            href="/dashboard/exceptions"
            className="p-3 border border-border bg-surface hover:bg-hover transition-colors flex items-center justify-between text-xs"
          >
            <span className="font-medium text-ink-primary">Human Review Queue</span>
            <ArrowRight className="h-3.5 w-3.5 text-ink-secondary" />
          </Link>
          <Link
            href="/dashboard/contracts"
            className="p-3 border border-border bg-surface hover:bg-hover transition-colors flex items-center justify-between text-xs"
          >
            <span className="font-medium text-ink-primary">Fee & Tariff Schedules</span>
            <ArrowRight className="h-3.5 w-3.5 text-ink-secondary" />
          </Link>
          <Link
            href="/dashboard/audit"
            className="p-3 border border-border bg-surface hover:bg-hover transition-colors flex items-center justify-between text-xs"
          >
            <span className="font-medium text-ink-primary">Audit Log Ledger</span>
            <ArrowRight className="h-3.5 w-3.5 text-ink-secondary" />
          </Link>
        </div>
      </div>
    </div>
  );
}
