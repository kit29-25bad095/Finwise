"use client";

import React, { useState } from "react";
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
} from "lucide-react";
import { Topbar } from "@/components/shell/Topbar";
import { MetricCard } from "@/components/ui/MetricCard";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR, formatDate } from "@/lib/utils";
import { AuditDrawer, TransactionAuditItem } from "@/components/drawer/AuditDrawer";

export default function OverviewDashboardPage() {
  const [selectedAuditItem, setSelectedAuditItem] = useState<TransactionAuditItem | null>(null);

  // Authoritative metrics derived from reconciliation ledger
  const summaryMetrics = [
    { label: "Total Orders", value: "4,821", isMonetary: false, subtext: "Shopify capture ledger" },
    { label: "Successful Captures", value: formatINR(14280500.0), isMonetary: true, subtext: "Gross gateway captured" },
    { label: "Total Settled", value: formatINR(13994890.0), isMonetary: true, subtext: "Net settlement batches" },
    { label: "Bank Credits Matched", value: formatINR(13958890.0), isMonetary: true, subtext: "Pass 1 & Pass 2 matched" },
    { label: "Total Discrepancies", value: "36", isMonetary: false, status: "pending" as const, subtext: "Under active investigation" },
    { label: "Potentially Recoverable", value: formatINR(48500.0), isMonetary: true, status: "pending" as const, subtext: "Pending provider audit" },
    { label: "Verified Recoverable", value: formatINR(36000.0), isMonetary: true, status: "leakage" as const, subtext: "Evidence validated" },
    { label: "Actually Recovered", value: formatINR(12500.0), isMonetary: true, status: "matched" as const, subtext: "Nodal credits received" },
  ];

  // Recent exceptions under review
  const recentExceptions: TransactionAuditItem[] = [
    {
      id: "EXC-2026-081",
      orderId: "ORD-98421",
      paymentId: "pay_Oz91M203Nba",
      gatewayRef: "settle_batch_90412",
      settlementRef: "SETL-20261110-09",
      bankUtr: "HDFCR5202611110098",
      orderDate: "2026-11-10",
      shopifyGross: 12500.0,
      gatewayCapture: 12500.0,
      mdrFee: 231.25,
      applicableGst: 41.63,
      refundsAdjustments: 0.0,
      settlementNet: 12227.12,
      bankCredit: 12227.12,
      variance: 0.0,
      matchStatus: "MATCHED_PASS_1",
      matchingMethod: "Pass 1: Exact Gateway Payment ID & Order Ref",
      ruleVersion: "RULE-2026-V1.2",
      runId: "RUN-2026-11-12-01",
      sourceFile: "shopify_orders_nov2026.csv",
      sourceRow: 142,
    },
    {
      id: "EXC-2026-082",
      orderId: "ORD-98422",
      paymentId: "pay_Oz91M204Kpq",
      gatewayRef: "settle_batch_90412",
      settlementRef: "SETL-20261110-09",
      bankUtr: "HDFCR5202611110098",
      orderDate: "2026-11-10",
      shopifyGross: 8400.0,
      gatewayCapture: 8400.0,
      mdrFee: 180.6,
      applicableGst: 32.51,
      refundsAdjustments: 0.0,
      settlementNet: 8186.89,
      bankCredit: 8150.89,
      variance: -36.0,
      matchStatus: "LEAKAGE_OVERCHARGE",
      matchingMethod: "Pass 3: Contractual Tariff Overcharge Detector",
      ruleVersion: "RULE-2026-V1.2",
      runId: "RUN-2026-11-12-01",
      sourceFile: "razorpay_settlement_nov2026.csv",
      sourceRow: 89,
      investigation: {
        hypotheses: ["Applied 2.15% fee card instead of contractual 1.85% D2C rate for Corporate Credit Card."],
        supportingEvidence: ["Contract Agreement Tariff: Schedule B (1.85% + 18% GST)", "Reported Fee: ₹180.60 (Expected ₹155.40)"],
        contradictingEvidence: ["No international interchange surcharge cited in gateway metadata."],
        missingInformation: ["Interchange network classification code from gateway nodal file."],
        recommendedSteps: ["File formal claim with gateway relationship manager citing Schedule B tariff."],
      },
      disputeDraft: "DISPUTE CLAIM: OVERCHARGE RECOVERY\nOrder ID: ORD-98422\nDiscrepancy: ₹36.00 excess MDR tariff applied.",
    },
    {
      id: "EXC-2026-083",
      orderId: "ORD-98423",
      paymentId: "pay_Oz91M205Zaa",
      gatewayRef: "settle_batch_pending",
      settlementRef: "UNSETTLED",
      bankUtr: "PENDING_CREDIT",
      orderDate: "2026-11-08",
      shopifyGross: 14200.0,
      gatewayCapture: 14200.0,
      mdrFee: 262.7,
      applicableGst: 47.29,
      refundsAdjustments: 0.0,
      settlementNet: 13890.01,
      bankCredit: 0.0,
      variance: -13890.01,
      matchStatus: "LEAKAGE_MISSING_SETTLEMENT",
      matchingMethod: "Detector 1: Missing Gateway Settlement (T+2 Due Date Exceeded)",
      ruleVersion: "RULE-2026-V1.2",
      runId: "RUN-2026-11-12-01",
      sourceFile: "shopify_orders_nov2026.csv",
      sourceRow: 215,
      investigation: {
        hypotheses: ["Capture settlement batch delayed beyond contractual T+2 business days window."],
        supportingEvidence: ["Payment captured on 08 Nov 2026", "RBI banking calendar confirms clearing day was 10 Nov 2026."],
        contradictingEvidence: ["No gateway risk freeze or chargeback hold attached to merchant ID."],
        missingInformation: ["Gateway settlement batch release timestamp."],
        recommendedSteps: ["Transmit missing settlement ticket via gateway merchant console."],
      },
      disputeDraft: "DISPUTE CLAIM: DELAYED SETTLEMENT BATCH\nOrder ID: ORD-98423\nAmount: ₹13,890.01 capture unsettled past contractual T+2 cutoff.",
    },
  ];

  // Latest reconciliation runs
  const latestRuns = [
    {
      id: "RUN-2026-11-12-01",
      date: "2026-11-12 02:30 IST",
      totalProcessed: "4,821 tx",
      pass1Matched: "94.2%",
      pass4Knapsack: "4.8%",
      unresolved: "1.0%",
      status: "COMPLETED",
    },
    {
      id: "RUN-2026-11-11-01",
      date: "2026-11-11 23:15 IST",
      totalProcessed: "4,790 tx",
      pass1Matched: "94.0%",
      pass4Knapsack: "5.1%",
      unresolved: "0.9%",
      status: "COMPLETED",
    },
  ];

  return (
    <>
      <Topbar title="Financial Overview" breadcrumb="Finora" />

      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        {/* Editorial Page Header */}
        <div className="border-b border-border pb-4">
          <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
            Financial Overview
          </h1>
          <p className="text-xs text-ink-secondary mt-1">
            Monitor payment flows, settlements and revenue discrepancies across orders, gateways and bank ledgers.
          </p>
        </div>

        {/* Top 8 Summary Metrics (Strictly separating Potential from Verified Recovery) */}
        <div>
          <div className="text-[11px] font-mono uppercase text-ink-muted font-semibold mb-2">
            RECONCILIATION SUMMARY & LEAKAGE LEDGER
          </div>
          <div className="grid grid-cols-2 md:grid-cols-4 gap-3">
            {summaryMetrics.map((metric, i) => (
              <MetricCard
                key={i}
                label={metric.label}
                value={metric.value}
                isMonetary={metric.isMonetary}
                status={metric.status}
                subtext={metric.subtext}
              />
            ))}
          </div>
        </div>

        {/* Section A & B: Reconciliation Health and Settlement Status */}
        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {/* A. Reconciliation Health */}
          <div className="bg-surface border border-border p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <span className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                  SECTION A
                </span>
                <h2 className="text-sm font-semibold text-ink-primary">
                  Reconciliation Health
                </h2>
              </div>
              <Badge variant="matched">99.0% MATCHED</Badge>
            </div>

            <div className="space-y-3 text-xs">
              <div className="flex justify-between items-center py-1 border-b border-border/60">
                <span className="text-ink-secondary">Exact Reference Matches (Pass 1 & 2):</span>
                <span className="font-mono text-ink-primary font-medium">94.2% (4,541 tx)</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/60">
                <span className="text-ink-secondary">Bounded Multi-Match Allocation (Pass 5):</span>
                <span className="font-mono text-ink-primary font-medium">4.8% (231 tx)</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/60">
                <span className="text-ink-secondary">Candidate Ambiguity / Human Queue:</span>
                <span className="font-mono text-[#D97706] font-medium">1.0% (49 tx)</span>
              </div>
              <div className="flex justify-between items-center py-1">
                <span className="text-ink-secondary">Mathematical Conservation Check:</span>
                <span className="font-mono text-ink-primary flex items-center gap-1">
                  <CheckCircle2 className="h-3.5 w-3.5 text-zinc-700" />
                  Passed (Zero Float)
                </span>
              </div>
            </div>

            <div className="p-2.5 bg-canvas border border-border text-[11px] text-ink-secondary flex items-center justify-between">
              <span>Tolerance Bound: <strong className="font-mono text-ink-primary">±₹0.05</strong></span>
              <span>Algorithm Version: <strong className="font-mono text-ink-primary">v1.2-Deterministic</strong></span>
            </div>
          </div>

          {/* B. Settlement Status */}
          <div className="bg-surface border border-border p-5 space-y-4">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <span className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                  SECTION B
                </span>
                <h2 className="text-sm font-semibold text-ink-primary">
                  Settlement & Banking Window
                </h2>
              </div>
              <Badge variant="neutral">T+2 RBI SCHEDULE</Badge>
            </div>

            <div className="space-y-3 text-xs">
              <div className="flex justify-between items-center py-1 border-b border-border/60">
                <span className="text-ink-secondary">Nodal Bank Account:</span>
                <span className="font-mono text-ink-primary font-medium">HDFC Bank (•••• 4912)</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/60">
                <span className="text-ink-secondary">Gateway Cutoff Timestamp:</span>
                <span className="font-mono text-ink-primary font-medium">23:00:00 IST</span>
              </div>
              <div className="flex justify-between items-center py-1 border-b border-border/60">
                <span className="text-ink-secondary">Expected In-Transit Settlements:</span>
                <span className="font-mono text-[#D97706] font-medium">{formatINR(36000.0)}</span>
              </div>
              <div className="flex justify-between items-center py-1">
                <span className="text-ink-secondary">Statement Import Coverage:</span>
                <span className="font-mono text-ink-primary font-medium">01 Nov 2026 – 12 Nov 2026</span>
              </div>
            </div>

            <div className="p-2.5 bg-canvas border border-border text-[11px] text-ink-secondary flex items-center justify-between">
              <span>Next Clearing Window: <strong className="font-mono text-ink-primary">12 Nov, 18:00 IST</strong></span>
              <Link href="/dashboard/settlements" className="text-ink-primary hover:underline font-medium">
                View Settlements →
              </Link>
            </div>
          </div>
        </div>

        {/* Section C: Four Core Leakage Detectors Breakdown */}
        <div className="bg-surface border border-border p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div>
              <span className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                SECTION C
              </span>
              <h2 className="text-sm font-semibold text-ink-primary">
                Four Core Leakage Detectors
              </h2>
            </div>
            <Link
              href="/dashboard/leakage-detection"
              className="text-xs text-ink-secondary hover:text-ink-primary flex items-center gap-1"
            >
              <span>Detector Rules</span>
              <ArrowUpRight className="h-3 w-3" />
            </Link>
          </div>

          <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-3 text-xs">
            {/* Detector 1 */}
            <div className="border border-border p-3.5 bg-canvas/30 space-y-2">
              <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                DETECTOR 1
              </div>
              <div className="font-medium text-ink-primary">
                Missing Gateway Settlement
              </div>
              <div className="text-lg font-mono font-semibold text-[#DC2626] tabular-nums">
                {formatINR(13890.01)}
              </div>
              <div className="text-[11px] text-ink-muted">
                1 transaction exceeded contractual T+2 cutoff.
              </div>
            </div>

            {/* Detector 2 */}
            <div className="border border-border p-3.5 bg-canvas/30 space-y-2">
              <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                DETECTOR 2
              </div>
              <div className="font-medium text-ink-primary">
                Settlement Not Credited to Bank
              </div>
              <div className="text-lg font-mono font-semibold text-ink-primary tabular-nums">
                {formatINR(0.0)}
              </div>
              <div className="text-[11px] text-ink-muted">
                Zero nodal bank statement gaps detected.
              </div>
            </div>

            {/* Detector 3 */}
            <div className="border border-border p-3.5 bg-canvas/30 space-y-2">
              <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                DETECTOR 3
              </div>
              <div className="font-medium text-ink-primary">
                Contractual Fee Overcharge
              </div>
              <div className="text-lg font-mono font-semibold text-[#DC2626] tabular-nums">
                {formatINR(22109.99)}
              </div>
              <div className="text-[11px] text-ink-muted">
                32 transactions deviated from tariff schedule.
              </div>
            </div>

            {/* Detector 4 */}
            <div className="border border-border p-3.5 bg-canvas/30 space-y-2">
              <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                DETECTOR 4
              </div>
              <div className="font-medium text-ink-primary">
                Duplicate / Unauthorized Refund
              </div>
              <div className="text-lg font-mono font-semibold text-ink-primary tabular-nums">
                {formatINR(0.0)}
              </div>
              <div className="text-[11px] text-ink-muted">
                All refunds verified against Shopify returns.
              </div>
            </div>
          </div>
        </div>

        {/* Section D: Recent Exceptions Table */}
        <div className="bg-surface border border-border p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div>
              <span className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                SECTION D
              </span>
              <h2 className="text-sm font-semibold text-ink-primary">
                Recent Exceptions Requiring Review
              </h2>
            </div>
            <Link
              href="/dashboard/reconciliation"
              className="text-xs text-ink-secondary hover:text-ink-primary font-medium"
            >
              Open Full Reconciliation Workspace →
            </Link>
          </div>

          <div className="border border-border overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse">
              <thead>
                <tr className="border-b border-border bg-canvas/80 text-[11px] font-mono text-ink-muted uppercase">
                  <th className="py-2.5 px-3 font-semibold">Order ID</th>
                  <th className="py-2.5 px-3 font-semibold">Order Date</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Shopify Gross</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Gateway Capture</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Bank Credit</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Variance</th>
                  <th className="py-2.5 px-3 font-semibold">Status</th>
                  <th className="py-2.5 px-3 font-semibold text-right">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {recentExceptions.map((item) => (
                  <tr
                    key={item.id}
                    onClick={() => setSelectedAuditItem(item)}
                    className="hover:bg-hover/60 cursor-pointer transition-colors h-11"
                  >
                    <td className="py-2 px-3 font-mono font-medium text-ink-primary">
                      {item.orderId}
                    </td>
                    <td className="py-2 px-3 text-ink-secondary">
                      {item.orderDate}
                    </td>
                    <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary">
                      {formatINR(item.shopifyGross)}
                    </td>
                    <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary">
                      {formatINR(item.gatewayCapture)}
                    </td>
                    <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary">
                      {formatINR(item.bankCredit)}
                    </td>
                    <td
                      className={`py-2 px-3 font-mono font-semibold text-right tabular-nums ${
                        item.variance !== 0 ? "text-[#DC2626]" : "text-ink-primary"
                      }`}
                    >
                      {formatINR(item.variance)}
                    </td>
                    <td className="py-2 px-3">
                      <Badge
                        variant={
                          item.matchStatus.startsWith("LEAKAGE")
                            ? "leakage"
                            : item.matchStatus === "UNRESOLVED"
                            ? "pending"
                            : "matched"
                        }
                      >
                        {item.matchStatus}
                      </Badge>
                    </td>
                    <td className="py-2 px-3 text-right">
                      <span className="text-[11px] text-ink-secondary hover:text-ink-primary font-mono underline">
                        Inspect
                      </span>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>

        {/* Section E: Latest Reconciliation Runs */}
        <div className="bg-surface border border-border p-5 space-y-4">
          <div className="flex items-center justify-between border-b border-border pb-3">
            <div>
              <span className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                SECTION E
              </span>
              <h2 className="text-sm font-semibold text-ink-primary">
                Deterministic Reconciliation Execution Log
              </h2>
            </div>
            <span className="text-xs font-mono text-ink-muted">
              PostgreSQL ACID Record
            </span>
          </div>

          <div className="space-y-2">
            {latestRuns.map((run) => (
              <div
                key={run.id}
                className="p-3 border border-border bg-canvas/30 flex flex-col sm:flex-row sm:items-center justify-between gap-3 text-xs"
              >
                <div className="flex items-center gap-3">
                  <span className="font-mono font-medium text-ink-primary">{run.id}</span>
                  <span className="text-ink-muted font-mono text-[11px]">{run.date}</span>
                </div>
                <div className="flex items-center gap-4 text-ink-secondary font-mono text-[11px]">
                  <span>Processed: <strong className="text-ink-primary">{run.totalProcessed}</strong></span>
                  <span>Pass 1 Exact: <strong className="text-ink-primary">{run.pass1Matched}</strong></span>
                  <span>Pass 5 Allocation: <strong className="text-ink-primary">{run.pass4Knapsack}</strong></span>
                  <span>Review Queue: <strong className="text-[#D97706]">{run.unresolved}</strong></span>
                  <Badge variant="matched">{run.status}</Badge>
                </div>
              </div>
            ))}
          </div>
        </div>
      </main>

      {/* Transaction Audit Drawer */}
      <AuditDrawer
        item={selectedAuditItem}
        isOpen={!!selectedAuditItem}
        onClose={() => setSelectedAuditItem(null)}
      />
    </>
  );
}
