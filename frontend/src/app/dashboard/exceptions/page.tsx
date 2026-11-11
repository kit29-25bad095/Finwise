"use client";

import React, { useState, useMemo } from "react";
import {
  AlertOctagon,
  Search,
  Filter,
  CheckCircle2,
  XCircle,
  FileText,
  Clock,
  ShieldCheck,
  ChevronRight,
  Download,
} from "lucide-react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR, formatDate } from "@/lib/utils";
import { ConfirmationDialog } from "@/components/ui/ConfirmationDialog";
import { AuditDrawer, TransactionAuditItem } from "@/components/drawer/AuditDrawer";

interface ExceptionItem {
  id: string;
  detectorCategory:
    | "Missing Gateway Settlement"
    | "Settlement Not Credited to Bank"
    | "Contractual Fee Overcharge"
    | "Duplicate or Unauthorized Refund";
  sourceRef: string;
  orderId: string;
  paymentId: string;
  discrepancyAmount: number;
  evidenceStatus: "COMPLETE" | "PENDING_LOGS" | "INSUFFICIENT";
  investigationStatus:
    | "Detected"
    | "Investigating"
    | "Evidence Pending"
    | "Potentially Recoverable"
    | "Verified Recoverable"
    | "Human Approved"
    | "Claimed"
    | "Recovered"
    | "Dismissed";
  recoveryClassification: "RECOVERABLE" | "NON_RECOVERABLE" | "UNRESOLVED";
  lastUpdated: string;
  auditItem: TransactionAuditItem;
}

export default function ExceptionsPage() {
  const [selectedAuditItem, setSelectedAuditItem] = useState<TransactionAuditItem | null>(null);
  const [activeCategory, setActiveCategory] = useState<string>("ALL");
  const [activeStatusFilter, setActiveStatusFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [reviewModalItem, setReviewModalItem] = useState<ExceptionItem | null>(null);

  // Authoritative exception inventory
  const [exceptions, setExceptions] = useState<ExceptionItem[]>([
    {
      id: "EXC-2026-001",
      detectorCategory: "Contractual Fee Overcharge",
      sourceRef: "ORD-98422",
      orderId: "ORD-98422",
      paymentId: "pay_Oz91M204Kpq",
      discrepancyAmount: 36.0,
      evidenceStatus: "COMPLETE",
      investigationStatus: "Verified Recoverable",
      recoveryClassification: "RECOVERABLE",
      lastUpdated: "2026-11-12 01:45 IST",
      auditItem: {
        id: "tx-003",
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
          hypotheses: ["Applied 2.15% fee card instead of contractual 1.85% rate."],
          supportingEvidence: ["Contract Agreement Tariff: Schedule B (1.85% + 18% GST)", "Reported Fee: ₹180.60 (Expected ₹155.40)"],
          contradictingEvidence: ["No international interchange surcharge cited."],
          missingInformation: ["Interchange network classification code from gateway nodal file."],
          recommendedSteps: ["File formal claim with gateway relationship manager citing Schedule B tariff."],
        },
        disputeDraft: "DISPUTE CLAIM: OVERCHARGE RECOVERY\nOrder ID: ORD-98422\nDiscrepancy: ₹36.00 excess MDR tariff applied.",
      },
    },
    {
      id: "EXC-2026-002",
      detectorCategory: "Missing Gateway Settlement",
      sourceRef: "ORD-98423",
      orderId: "ORD-98423",
      paymentId: "pay_Oz91M205Zaa",
      discrepancyAmount: 13890.01,
      evidenceStatus: "COMPLETE",
      investigationStatus: "Potentially Recoverable",
      recoveryClassification: "RECOVERABLE",
      lastUpdated: "2026-11-12 02:10 IST",
      auditItem: {
        id: "tx-004",
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
          hypotheses: ["Settlement batch release delayed beyond contractual T+2 cutoff."],
          supportingEvidence: ["Captured on 08 Nov 2026", "RBI clearing completed on 10 Nov 2026"],
          contradictingEvidence: ["No merchant freeze cited."],
          missingInformation: ["Gateway batch release log."],
          recommendedSteps: ["File ticket with payment operations team."],
        },
        disputeDraft: "DISPUTE CLAIM: DELAYED SETTLEMENT BATCH\nOrder ID: ORD-98423\nAmount: ₹13,890.01 capture unsettled past contractual T+2 cutoff.",
      },
    },
    {
      id: "EXC-2026-003",
      detectorCategory: "Contractual Fee Overcharge",
      sourceRef: "ORD-98430",
      orderId: "ORD-98430",
      paymentId: "pay_Oz91M212Ptt",
      discrepancyAmount: 54.2,
      evidenceStatus: "PENDING_LOGS",
      investigationStatus: "Investigating",
      recoveryClassification: "UNRESOLVED",
      lastUpdated: "2026-11-12 02:22 IST",
      auditItem: {
        id: "tx-010",
        orderId: "ORD-98430",
        paymentId: "pay_Oz91M212Ptt",
        gatewayRef: "settle_batch_90415",
        settlementRef: "SETL-20261111-04",
        bankUtr: "HDFCR5202611120091",
        orderDate: "2026-11-10",
        shopifyGross: 18000.0,
        gatewayCapture: 18000.0,
        mdrFee: 387.0,
        applicableGst: 69.66,
        refundsAdjustments: 0.0,
        settlementNet: 17543.34,
        bankCredit: 17489.14,
        variance: -54.2,
        matchStatus: "LEAKAGE_OVERCHARGE",
        matchingMethod: "Pass 3: Contractual Tariff Overcharge Detector",
        ruleVersion: "RULE-2026-V1.2",
        runId: "RUN-2026-11-12-01",
        sourceFile: "razorpay_settlement_nov2026.csv",
        sourceRow: 114,
      },
    },
  ]);

  const categories = [
    "ALL",
    "Missing Gateway Settlement",
    "Settlement Not Credited to Bank",
    "Contractual Fee Overcharge",
    "Duplicate or Unauthorized Refund",
  ];

  const statusFilters = [
    "ALL",
    "Detected",
    "Investigating",
    "Evidence Pending",
    "Potentially Recoverable",
    "Verified Recoverable",
    "Human Approved",
    "Claimed",
    "Recovered",
    "Dismissed",
  ];

  const filteredExceptions = useMemo(() => {
    return exceptions.filter((item) => {
      if (activeCategory !== "ALL" && item.detectorCategory !== activeCategory) return false;
      if (activeStatusFilter !== "ALL" && item.investigationStatus !== activeStatusFilter) return false;
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        return (
          item.id.toLowerCase().includes(q) ||
          item.sourceRef.toLowerCase().includes(q) ||
          item.paymentId.toLowerCase().includes(q)
        );
      }
      return true;
    });
  }, [exceptions, activeCategory, activeStatusFilter, searchQuery]);

  const handleApproveException = (reason: string) => {
    if (!reviewModalItem) return;
    setExceptions((prev) =>
      prev.map((item) =>
        item.id === reviewModalItem.id
          ? { ...item, investigationStatus: "Human Approved", lastUpdated: "Just now by Human Reviewer" }
          : item
      )
    );
  };

  return (
    <>
      <Topbar title="Exception Management" breadcrumb="Investigation" />

      <main className="p-6 space-y-4 max-w-7xl mx-auto w-full">
        {/* Editorial Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Exception Management
            </h1>
            <p className="text-xs text-ink-secondary mt-1">
              Deterministic revenue leakage exceptions surfaced across the four core financial detectors.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <span className="text-[11px] font-mono text-ink-muted">
              Mandate: Never treat a suspected discrepancy as confirmed loss without evidence.
            </span>
          </div>
        </div>

        {/* Detector Category Filter Tabs */}
        <div className="flex flex-wrap gap-1 border-b border-border pb-2 text-xs">
          {categories.map((cat) => (
            <button
              key={cat}
              onClick={() => setActiveCategory(cat)}
              className={`px-3 py-1.5 font-mono text-[11px] uppercase transition-colors border ${
                activeCategory === cat
                  ? "bg-brand-black text-white border-brand-black font-semibold"
                  : "bg-surface text-ink-secondary border-border hover:bg-hover hover:text-ink-primary"
              }`}
            >
              {cat}
            </button>
          ))}
        </div>

        {/* Filter Toolbar */}
        <div className="bg-surface border border-border p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
          <div className="relative flex-1 min-w-[240px] max-w-md">
            <Search className="h-3.5 w-3.5 text-ink-muted absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search Exception ID, Order, or Payment ID..."
              className="w-full pl-8 pr-3 py-1.5 border border-border bg-canvas text-ink-primary text-xs focus:outline-none focus:ring-1 focus:ring-ink-primary placeholder:text-ink-muted font-mono"
            />
          </div>

          <div className="flex items-center gap-2">
            <span className="text-[11px] font-mono text-ink-muted uppercase">Lifecycle:</span>
            <select
              value={activeStatusFilter}
              onChange={(e) => setActiveStatusFilter(e.target.value)}
              className="px-2.5 py-1.5 border border-border bg-surface text-ink-primary text-xs focus:outline-none focus:ring-1 focus:ring-ink-primary font-mono cursor-pointer"
            >
              {statusFilters.map((st) => (
                <option key={st} value={st}>
                  {st.toUpperCase()}
                </option>
              ))}
            </select>
          </div>
        </div>

        {/* Exceptions Ledger Table */}
        <div className="bg-surface border border-border overflow-x-auto shadow-sm">
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-border bg-canvas/80 text-[11px] font-mono text-ink-muted uppercase select-none">
                <th className="py-2.5 px-3 font-semibold">Exception ID</th>
                <th className="py-2.5 px-3 font-semibold">Detector Category</th>
                <th className="py-2.5 px-3 font-semibold">Source Ref</th>
                <th className="py-2.5 px-3 font-semibold text-right">Discrepancy</th>
                <th className="py-2.5 px-3 font-semibold text-center">Evidence</th>
                <th className="py-2.5 px-3 font-semibold text-center">Status</th>
                <th className="py-2.5 px-3 font-semibold text-center">Classification</th>
                <th className="py-2.5 px-3 font-semibold text-right">Last Updated</th>
                <th className="py-2.5 px-3 font-semibold text-center">Actions</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {filteredExceptions.map((item) => (
                <tr
                  key={item.id}
                  className="hover:bg-hover/60 transition-colors h-[44px]"
                >
                  <td
                    onClick={() => setSelectedAuditItem(item.auditItem)}
                    className="py-2 px-3 font-mono font-medium text-ink-primary cursor-pointer hover:underline"
                  >
                    {item.id}
                  </td>
                  <td className="py-2 px-3 text-ink-secondary">
                    {item.detectorCategory}
                  </td>
                  <td className="py-2 px-3 font-mono text-ink-primary">
                    {item.sourceRef}
                  </td>
                  <td className="py-2 px-3 font-mono font-semibold text-right tabular-nums text-[#DC2626]">
                    {formatINR(item.discrepancyAmount)}
                  </td>
                  <td className="py-2 px-3 text-center">
                    <Badge variant={item.evidenceStatus === "COMPLETE" ? "matched" : "pending"}>
                      {item.evidenceStatus}
                    </Badge>
                  </td>
                  <td className="py-2 px-3 text-center">
                    <Badge
                      variant={
                        item.investigationStatus === "Verified Recoverable"
                          ? "leakage"
                          : item.investigationStatus === "Human Approved"
                          ? "matched"
                          : "pending"
                      }
                    >
                      {item.investigationStatus}
                    </Badge>
                  </td>
                  <td className="py-2 px-3 text-center font-mono text-[11px] text-ink-secondary">
                    {item.recoveryClassification}
                  </td>
                  <td className="py-2 px-3 font-mono text-[11px] text-ink-muted text-right">
                    {item.lastUpdated}
                  </td>
                  <td className="py-2 px-3 text-center">
                    <div className="flex items-center justify-center gap-1.5">
                      <Button
                        variant="secondary"
                        size="sm"
                        onClick={() => setSelectedAuditItem(item.auditItem)}
                      >
                        Dossier
                      </Button>
                      <Button
                        variant="primary"
                        size="sm"
                        onClick={() => setReviewModalItem(item)}
                        disabled={item.investigationStatus === "Human Approved"}
                      >
                        {item.investigationStatus === "Human Approved" ? "Approved" : "Approve"}
                      </Button>
                    </div>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>

      {/* Audit Drawer */}
      <AuditDrawer
        item={selectedAuditItem}
        isOpen={!!selectedAuditItem}
        onClose={() => setSelectedAuditItem(null)}
      />

      {/* Human Review Confirmation Dialog */}
      <ConfirmationDialog
        isOpen={!!reviewModalItem}
        onClose={() => setReviewModalItem(null)}
        onConfirm={handleApproveException}
        title={`Approve Recovery Claim: ${reviewModalItem?.id}`}
        description={`You are formally approving ${formatINR(reviewModalItem?.discrepancyAmount || 0)} as a verified recoverable revenue loss under ${reviewModalItem?.detectorCategory}. This action produces an immutable audit log entry.`}
        confirmLabel="Authorize Recovery Claim"
        severity="critical"
      />
    </>
  );
}
