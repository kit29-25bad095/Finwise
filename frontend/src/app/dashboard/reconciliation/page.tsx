"use client";

import React, { useState, useMemo } from "react";
import {
  Search,
  Filter,
  Download,
  Calendar,
  Layers,
  ChevronLeft,
  ChevronRight,
  SlidersHorizontal,
  X,
  FileSpreadsheet,
} from "lucide-react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR, formatDate } from "@/lib/utils";
import { AuditDrawer, TransactionAuditItem } from "@/components/drawer/AuditDrawer";

export default function ReconciliationWorkspacePage() {
  const [selectedItem, setSelectedItem] = useState<TransactionAuditItem | null>(null);
  const [searchQuery, setSearchQuery] = useState("");
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [runSelector, setRunSelector] = useState("ALL_RUNS");
  const [dateFilter, setDateFilter] = useState("ALL_TIME");
  const [page, setPage] = useState(1);
  const pageSize = 10;

  // Realistic authoritative ledger dataset
  const rawLedger: TransactionAuditItem[] = [
    {
      id: "tx-001",
      orderId: "ORD-98420",
      paymentId: "pay_Oz91M202Kaa",
      gatewayRef: "settle_batch_90412",
      settlementRef: "SETL-20261110-09",
      bankUtr: "HDFCR5202611110098",
      orderDate: "2026-11-10",
      shopifyGross: 15400.0,
      gatewayCapture: 15400.0,
      mdrFee: 284.9,
      applicableGst: 51.28,
      refundsAdjustments: 0.0,
      settlementNet: 15063.82,
      bankCredit: 15063.82,
      variance: 0.0,
      matchStatus: "MATCHED_PASS_1",
      matchingMethod: "Pass 1: Exact Gateway Payment ID & Order Ref",
      ruleVersion: "RULE-2026-V1.2",
      runId: "RUN-2026-11-12-01",
      sourceFile: "shopify_orders_nov2026.csv",
      sourceRow: 141,
    },
    {
      id: "tx-002",
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
        hypotheses: ["Applied 2.15% fee card instead of contractual 1.85% D2C rate."],
        supportingEvidence: ["Contract Agreement Tariff: Schedule B (1.85% + 18% GST)", "Reported Fee: ₹180.60 (Expected ₹155.40)"],
        contradictingEvidence: ["No international card metadata cited."],
        missingInformation: ["Interchange network classification code from gateway nodal file."],
        recommendedSteps: ["File formal claim with gateway relationship manager citing Schedule B tariff."],
      },
      disputeDraft: "DISPUTE CLAIM: OVERCHARGE RECOVERY\nOrder ID: ORD-98422\nDiscrepancy: ₹36.00 excess MDR tariff applied.",
    },
    {
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
    {
      id: "tx-005",
      orderId: "ORD-98424",
      paymentId: "pay_Oz91M206Cdd",
      gatewayRef: "settle_batch_90413",
      settlementRef: "SETL-20261111-01",
      bankUtr: "HDFCR5202611110099",
      orderDate: "2026-11-09",
      shopifyGross: 6200.0,
      gatewayCapture: 6200.0,
      mdrFee: 114.7,
      applicableGst: 20.65,
      refundsAdjustments: 0.0,
      settlementNet: 6064.65,
      bankCredit: 6064.65,
      variance: 0.0,
      matchStatus: "MATCHED_PASS_2",
      matchingMethod: "Pass 2: Exact Settlement ID & Bank UTR Match",
      ruleVersion: "RULE-2026-V1.2",
      runId: "RUN-2026-11-12-01",
      sourceFile: "hdfc_bank_nov2026.csv",
      sourceRow: 301,
    },
    {
      id: "tx-006",
      orderId: "ORD-98425",
      paymentId: "pay_Oz91M207Rtt",
      gatewayRef: "settle_batch_90413",
      settlementRef: "SETL-20261111-01",
      bankUtr: "HDFCR5202611110099",
      orderDate: "2026-11-09",
      shopifyGross: 29500.0,
      gatewayCapture: 29500.0,
      mdrFee: 545.75,
      applicableGst: 98.24,
      refundsAdjustments: 0.0,
      settlementNet: 28856.01,
      bankCredit: 28856.01,
      variance: 0.0,
      matchStatus: "MATCHED_PASS_1",
      matchingMethod: "Pass 1: Exact Gateway Payment ID & Order Ref",
      ruleVersion: "RULE-2026-V1.2",
      runId: "RUN-2026-11-12-01",
      sourceFile: "shopify_orders_nov2026.csv",
      sourceRow: 145,
    },
    {
      id: "tx-007",
      orderId: "ORD-98426",
      paymentId: "pay_Oz91M208Faa",
      gatewayRef: "settle_batch_90414",
      settlementRef: "SETL-20261111-02",
      bankUtr: "HDFCR5202611120014",
      orderDate: "2026-11-10",
      shopifyGross: 4500.0,
      gatewayCapture: 4500.0,
      mdrFee: 83.25,
      applicableGst: 14.99,
      refundsAdjustments: 0.0,
      settlementNet: 4401.76,
      bankCredit: 4401.76,
      variance: 0.0,
      matchStatus: "MATCHED_PASS_4",
      matchingMethod: "Pass 4: Multi-Factor Candidate Scoring Engine (Score: 0.94)",
      ruleVersion: "RULE-2026-V1.2",
      runId: "RUN-2026-11-12-01",
      sourceFile: "hdfc_bank_nov2026.csv",
      sourceRow: 412,
    },
    {
      id: "tx-008",
      orderId: "ORD-98427",
      paymentId: "pay_Oz91M209Vbb",
      gatewayRef: "settle_batch_pending",
      settlementRef: "SETL-UNRESOLVED",
      bankUtr: "AMBIGUOUS_MATCH",
      orderDate: "2026-11-11",
      shopifyGross: 9800.0,
      gatewayCapture: 9800.0,
      mdrFee: 181.3,
      applicableGst: 32.63,
      refundsAdjustments: 0.0,
      settlementNet: 9586.07,
      bankCredit: 9586.07,
      variance: 0.0,
      matchStatus: "UNRESOLVED",
      matchingMethod: "Pass 6: Human Review Queue (Collision score delta < 0.15)",
      ruleVersion: "RULE-2026-V1.2",
      runId: "RUN-2026-11-12-01",
      sourceFile: "shopify_orders_nov2026.csv",
      sourceRow: 198,
      investigation: {
        hypotheses: ["Two identical net amount transactions within the same banking window."],
        supportingEvidence: ["Credit of ₹9,586.07 received", "Candidate #1: ORD-98427 (Score: 0.88)", "Candidate #2: ORD-98429 (Score: 0.86)"],
        contradictingEvidence: ["Narration lacks explicit order number token."],
        missingInformation: ["Original customer card last 4 digits from gateway."],
        recommendedSteps: ["Require human reviewer manual candidate approval."],
      },
    },
  ];

  // Filtering logic
  const filteredLedger = useMemo(() => {
    return rawLedger.filter((item) => {
      // Search
      if (searchQuery.trim()) {
        const q = searchQuery.toLowerCase();
        const matches =
          item.orderId.toLowerCase().includes(q) ||
          item.paymentId.toLowerCase().includes(q) ||
          item.bankUtr.toLowerCase().includes(q) ||
          item.settlementRef.toLowerCase().includes(q);
        if (!matches) return false;
      }

      // Status filter
      if (statusFilter === "LEAKAGE" && !item.matchStatus.startsWith("LEAKAGE")) return false;
      if (statusFilter === "MATCHED" && !item.matchStatus.startsWith("MATCHED")) return false;
      if (statusFilter === "UNRESOLVED" && item.matchStatus !== "UNRESOLVED") return false;

      return true;
    });
  }, [searchQuery, statusFilter]);

  const paginatedItems = useMemo(() => {
    const start = (page - 1) * pageSize;
    return filteredLedger.slice(start, start + pageSize);
  }, [filteredLedger, page]);

  const totalPages = Math.ceil(filteredLedger.length / pageSize) || 1;

  const handleExportCSV = () => {
    const headers = [
      "Order ID",
      "Order Date",
      "Payment ID",
      "Shopify Gross",
      "Gateway Capture",
      "MDR Fee",
      "Applicable GST",
      "Settlement Net",
      "Bank Credit",
      "Variance",
      "Match Status",
      "Bank UTR",
    ];
    const rows = filteredLedger.map((item) => [
      item.orderId,
      item.orderDate,
      item.paymentId,
      item.shopifyGross.toFixed(2),
      item.gatewayCapture.toFixed(2),
      item.mdrFee.toFixed(2),
      item.applicableGst.toFixed(2),
      item.settlementNet.toFixed(2),
      item.bankCredit.toFixed(2),
      item.variance.toFixed(2),
      item.matchStatus,
      item.bankUtr,
    ]);

    const csvContent =
      "data:text/csv;charset=utf-8," +
      [headers.join(","), ...rows.map((e) => e.join(","))].join("\n");
    const encodedUri = encodeURI(csvContent);
    const link = document.createElement("a");
    link.setAttribute("href", encodedUri);
    link.setAttribute("download", `Finora_Reconciliation_Ledger_${new Date().toISOString().substring(0, 10)}.csv`);
    document.body.appendChild(link);
    link.click();
    document.body.removeChild(link);
  };

  return (
    <>
      <Topbar title="Reconciliation Workspace" breadcrumb="Workspace" />

      <main className="p-6 space-y-4 max-w-7xl mx-auto w-full">
        {/* Workspace Editorial Header */}
        <div className="flex flex-col sm:flex-row sm:items-center justify-between gap-3 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Reconciliation
            </h1>
            <p className="text-xs text-ink-secondary mt-1">
              Trace every rupee across orders, payment gateways, settlements and bank credits.
            </p>
          </div>
          <div className="flex items-center gap-2">
            <Button
              variant="secondary"
              size="sm"
              onClick={handleExportCSV}
              className="flex items-center gap-1.5"
            >
              <Download className="h-3.5 w-3.5 text-ink-secondary" strokeWidth={1.5} />
              <span>Export Ledger CSV</span>
            </Button>
          </div>
        </div>

        {/* Filter Toolbar */}
        <div className="bg-surface border border-border p-3 flex flex-wrap items-center justify-between gap-3 text-xs">
          {/* Search Box */}
          <div className="relative flex-1 min-w-[240px] max-w-md">
            <Search className="h-3.5 w-3.5 text-ink-muted absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={searchQuery}
              onChange={(e) => setSearchQuery(e.target.value)}
              placeholder="Search Order ID, Payment ID, UTR, or Batch..."
              className="w-full pl-8 pr-3 py-1.5 border border-border bg-canvas text-ink-primary text-xs focus:outline-none focus:ring-1 focus:ring-ink-primary placeholder:text-ink-muted font-mono"
            />
            {searchQuery && (
              <button
                onClick={() => setSearchQuery("")}
                className="absolute right-2.5 top-1/2 -translate-y-1/2 text-ink-muted hover:text-ink-primary"
              >
                <X className="h-3 w-3" />
              </button>
            )}
          </div>

          {/* Filter Dropdowns */}
          <div className="flex flex-wrap items-center gap-2">
            {/* Status Selector */}
            <select
              value={statusFilter}
              onChange={(e) => setStatusFilter(e.target.value)}
              className="px-2.5 py-1.5 border border-border bg-surface text-ink-primary text-xs focus:outline-none focus:ring-1 focus:ring-ink-primary font-mono cursor-pointer"
            >
              <option value="ALL">ALL MATCH STATUSES</option>
              <option value="MATCHED">MATCHED ONLY</option>
              <option value="LEAKAGE">CONFIRMED LEAKAGES</option>
              <option value="UNRESOLVED">HUMAN REVIEW QUEUE</option>
            </select>

            {/* Run Selector */}
            <select
              value={runSelector}
              onChange={(e) => setRunSelector(e.target.value)}
              className="px-2.5 py-1.5 border border-border bg-surface text-ink-primary text-xs focus:outline-none focus:ring-1 focus:ring-ink-primary font-mono cursor-pointer"
            >
              <option value="ALL_RUNS">RUN: ALL RUNS</option>
              <option value="RUN-2026-11-12-01">RUN-2026-11-12-01 (Latest)</option>
              <option value="RUN-2026-11-11-01">RUN-2026-11-11-01</option>
            </select>

            {/* Date Range Selector */}
            <select
              value={dateFilter}
              onChange={(e) => setDateFilter(e.target.value)}
              className="px-2.5 py-1.5 border border-border bg-surface text-ink-primary text-xs focus:outline-none focus:ring-1 focus:ring-ink-primary font-mono cursor-pointer"
            >
              <option value="ALL_TIME">RANGE: CURRENT MONTH</option>
              <option value="TODAY">TODAY</option>
              <option value="LAST_7_DAYS">LAST 7 DAYS</option>
            </select>
          </div>
        </div>

        {/* Ledger Summary Stats Bar */}
        <div className="bg-canvas border border-border px-4 py-2.5 flex items-center justify-between text-xs font-mono text-ink-secondary">
          <div className="flex items-center gap-4">
            <span>TOTAL ROWS: <strong className="text-ink-primary">{filteredLedger.length}</strong></span>
            <span>LEAKAGE COUNT: <strong className="text-[#DC2626]">{filteredLedger.filter(i => i.matchStatus.startsWith("LEAKAGE")).length}</strong></span>
            <span>HUMAN REVIEW: <strong className="text-[#D97706]">{filteredLedger.filter(i => i.matchStatus === "UNRESOLVED").length}</strong></span>
          </div>
          <div className="text-[11px] text-ink-muted">
            Click any row to open full right-side Audit Dossier
          </div>
        </div>

        {/* High-Density Financial Ledger Table (Compact 44px rows) */}
        <div className="bg-surface border border-border overflow-x-auto shadow-sm">
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-border bg-canvas/80 text-[11px] font-mono text-ink-muted uppercase select-none">
                <th className="py-2.5 px-3 font-semibold">1. Order ID</th>
                <th className="py-2.5 px-3 font-semibold">2. Order Date</th>
                <th className="py-2.5 px-3 font-semibold text-right">3. Shopify Gross</th>
                <th className="py-2.5 px-3 font-semibold text-right">4. Gateway Capture</th>
                <th className="py-2.5 px-3 font-semibold text-right">5. Gateway Fees</th>
                <th className="py-2.5 px-3 font-semibold text-right">6. Settlement Net</th>
                <th className="py-2.5 px-3 font-semibold text-right">7. Bank Credit</th>
                <th className="py-2.5 px-3 font-semibold text-right">8. Variance</th>
                <th className="py-2.5 px-3 font-semibold text-center">9. Match Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {paginatedItems.length > 0 ? (
                paginatedItems.map((item) => {
                  const isLeakage = item.matchStatus.startsWith("LEAKAGE");
                  const isPending = item.matchStatus === "UNRESOLVED";
                  const totalGatewayFee = item.mdrFee + item.applicableGst;

                  return (
                    <tr
                      key={item.id}
                      onClick={() => setSelectedItem(item)}
                      className="hover:bg-hover cursor-pointer transition-colors h-[44px]"
                    >
                      <td className="py-2 px-3 font-mono font-medium text-ink-primary whitespace-nowrap">
                        {item.orderId}
                      </td>
                      <td className="py-2 px-3 text-ink-secondary whitespace-nowrap">
                        {item.orderDate}
                      </td>
                      <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary whitespace-nowrap">
                        {formatINR(item.shopifyGross)}
                      </td>
                      <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary whitespace-nowrap">
                        {formatINR(item.gatewayCapture)}
                      </td>
                      <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-secondary whitespace-nowrap">
                        {formatINR(totalGatewayFee)}
                      </td>
                      <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary whitespace-nowrap">
                        {formatINR(item.settlementNet)}
                      </td>
                      <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary whitespace-nowrap">
                        {formatINR(item.bankCredit)}
                      </td>
                      <td
                        className={`py-2 px-3 font-mono font-semibold text-right tabular-nums whitespace-nowrap ${
                          item.variance !== 0 ? "text-[#DC2626]" : "text-ink-primary"
                        }`}
                      >
                        {formatINR(item.variance)}
                      </td>
                      <td className="py-2 px-3 text-center whitespace-nowrap">
                        <Badge
                          variant={isLeakage ? "leakage" : isPending ? "pending" : "matched"}
                        >
                          {item.matchStatus}
                        </Badge>
                      </td>
                    </tr>
                  );
                })
              ) : (
                <tr>
                  <td colSpan={9} className="py-12 text-center text-ink-muted">
                    <div className="flex flex-col items-center justify-center space-y-2">
                      <FileSpreadsheet className="h-8 w-8 text-ink-muted" strokeWidth={1.5} />
                      <p className="text-sm font-medium text-ink-secondary">No financial records match your criteria.</p>
                      <p className="text-xs text-ink-muted">Try clearing the search query or adjusting the filters.</p>
                    </div>
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>

        {/* Pagination Bar */}
        <div className="flex items-center justify-between pt-2 text-xs text-ink-secondary font-mono">
          <div>
            Showing Page <strong className="text-ink-primary">{page}</strong> of <strong className="text-ink-primary">{totalPages}</strong> ({filteredLedger.length} items)
          </div>
          <div className="flex items-center gap-1.5">
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPage((p) => Math.max(p - 1, 1))}
              disabled={page === 1}
            >
              <ChevronLeft className="h-3.5 w-3.5" />
            </Button>
            <Button
              variant="secondary"
              size="sm"
              onClick={() => setPage((p) => Math.min(p + 1, totalPages))}
              disabled={page === totalPages}
            >
              <ChevronRight className="h-3.5 w-3.5" />
            </Button>
          </div>
        </div>
      </main>

      {/* Right-Side Transaction Audit Drawer (Section 6) */}
      <AuditDrawer
        item={selectedItem}
        isOpen={!!selectedItem}
        onClose={() => setSelectedItem(null)}
      />
    </>
  );
}
