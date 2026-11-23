"use client";

import React, { useState, useEffect } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR, formatDateTime } from "@/lib/utils";
import { ApiClient, LeakageFinding, LeakageFindingsResponse } from "@/lib/api";
import {
  Radar,
  Sliders,
  ShieldCheck,
  AlertTriangle,
  RefreshCw,
  Search,
  Filter,
  CheckCircle2,
  FileText,
  ChevronRight,
  X,
  ExternalLink,
} from "lucide-react";

export default function LeakageDetectionPage() {
  const [data, setData] = useState<LeakageFindingsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [categoryFilter, setCategoryFilter] = useState<string>("ALL");
  const [severityFilter, setSeverityFilter] = useState<string>("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedFinding, setSelectedFinding] = useState<LeakageFinding | null>(null);

  const fetchFindings = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ApiClient.getLeakageFindings();
      setData(res);
    } catch (err: any) {
      setError(err.message || "Failed to load leakage findings from backend.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFindings();
  }, []);

  const detectors = [
    {
      id: "DETECTOR-1",
      code: "MISSING_SETTLEMENT",
      name: "Missing Gateway Settlement",
      description: "Identifies captured payments with positive unallocated balance where settlement batch has not arrived after contractual due date.",
      formula: "DueDate = AddBusinessDays(CaptureDate, T_contract, Calendar_RBI)",
      tolerance: "Zero Tolerance (0.00)",
    },
    {
      id: "DETECTOR-2",
      code: "UNCREDITED_SETTLEMENT",
      name: "Settlement Not Credited to Bank",
      description: "Detects settlement batches marked 'settled' with valid UTR references that never appeared in the verified bank statement.",
      formula: "Delta_Bank = NetSettlementAmount - Sum(AllocatedBankCredit)",
      tolerance: "Zero Tolerance (0.00)",
    },
    {
      id: "DETECTOR-3",
      code: "FEE_OVERCHARGE",
      name: "Contractual Fee Overcharge",
      description: "Compares applied gateway MDR and GST against the merchant's signed fee schedule across payment instruments.",
      formula: "Delta_Fee = (ReportedFee + ReportedTax) - (ContractBaseFee + ContractGST)",
      tolerance: "₹0.05 (Sub-paisa buffer)",
    },
    {
      id: "DETECTOR-4",
      code: "DUPLICATE_OR_EXCESS_REFUND",
      name: "Duplicate or Unauthorized Refund",
      description: "Flags refunds exceeding original gross capture, duplicate gateway refund IDs, or orphan refund debits.",
      formula: "Delta_Excess = max(0, Sum(RefundAmount) - CapturedAmount)",
      tolerance: "Zero Tolerance (0.00)",
    },
  ];

  const filteredFindings = (data?.findings || []).filter((f) => {
    if (categoryFilter !== "ALL" && f.category !== categoryFilter) return false;
    if (severityFilter !== "ALL" && f.severity !== severityFilter) return false;
    if (searchQuery) {
      const q = searchQuery.toLowerCase();
      const matchTitle = f.title.toLowerCase().includes(q);
      const matchId = f.finding_id.toLowerCase().includes(q);
      const matchCat = f.category.toLowerCase().includes(q);
      if (!matchTitle && !matchId && !matchCat) return false;
    }
    return true;
  });

  return (
    <div className="flex flex-col min-h-screen bg-canvas">
      <Topbar title="Revenue Leakage Monitoring" breadcrumb="Investigation" />

      <main className="p-6 md:p-8 space-y-8 max-w-7xl mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Phase 4 Revenue Leakage Detectors
            </h1>
            <p className="text-xs text-ink-secondary mt-0.5">
              Deterministic mathematical functions identifying recoverable revenue discrepancies
            </p>
          </div>
          <Button
            onClick={fetchFindings}
            variant="outline"
            size="sm"
            disabled={loading}
            className="text-xs font-mono"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
            Refresh Detectors
          </Button>
        </div>

        {/* Executive Summary Cards */}
        <div className="grid grid-cols-1 sm:grid-cols-2 lg:grid-cols-4 gap-4">
          <div className="p-4 border border-border bg-surface">
            <span className="text-[10px] font-mono uppercase tracking-wider text-ink-muted block">
              Total Identified Leakage
            </span>
            <div className="text-xl font-mono font-semibold text-status-leakage-text mt-1">
              {formatINR(data?.total_leakage_amount || 0)}
            </div>
            <span className="text-xs text-ink-secondary mt-0.5 block">
              {data?.total_findings || 0} Total Findings
            </span>
          </div>

          <div className="p-4 border border-border bg-surface">
            <span className="text-[10px] font-mono uppercase tracking-wider text-ink-muted block">
              High Severity Leakage
            </span>
            <div className="text-xl font-mono font-semibold text-status-leakage-text mt-1">
              {data?.high_severity_count || 0}
            </div>
            <span className="text-xs text-ink-secondary mt-0.5 block">
              Missing & Uncredited Settlements
            </span>
          </div>

          <div className="p-4 border border-border bg-surface">
            <span className="text-[10px] font-mono uppercase tracking-wider text-ink-muted block">
              Medium Severity
            </span>
            <div className="text-xl font-mono font-semibold text-status-pending-text mt-1">
              {data?.medium_severity_count || 0}
            </div>
            <span className="text-xs text-ink-secondary mt-0.5 block">
              Contractual Fee Drift & Overcharges
            </span>
          </div>

          <div className="p-4 border border-border bg-surface">
            <span className="text-[10px] font-mono uppercase tracking-wider text-ink-muted block">
              Low Severity
            </span>
            <div className="text-xl font-mono font-semibold text-ink-primary mt-1">
              {data?.low_severity_count || 0}
            </div>
            <span className="text-xs text-ink-secondary mt-0.5 block">
              Refund Anomalies & Minor Drift
            </span>
          </div>
        </div>

        {/* 4 Core Detector Status Cards */}
        <div className="space-y-3">
          <h2 className="text-xs font-mono uppercase tracking-wider text-ink-muted">
            Detector Modules (Deterministic Specifications)
          </h2>
          <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
            {detectors.map((d) => {
              const findingsForDetector = (data?.findings || []).filter(
                (f) => f.category === d.code
              );
              const totalAmt = findingsForDetector.reduce(
                (sum, f) => sum + Number(f.difference),
                0
              );
              return (
                <div key={d.id} className="p-4 border border-border bg-surface space-y-2">
                  <div className="flex items-center justify-between">
                    <span className="text-[10px] font-mono text-ink-muted uppercase">
                      {d.id}
                    </span>
                    <Badge variant="matched">ACTIVE</Badge>
                  </div>
                  <h3 className="text-sm font-semibold text-ink-primary">{d.name}</h3>
                  <p className="text-xs text-ink-secondary leading-relaxed">{d.description}</p>
                  <div className="pt-2 border-t border-border flex items-center justify-between text-xs font-mono">
                    <span className="text-ink-secondary">{findingsForDetector.length} Findings</span>
                    <span className="text-status-leakage-text font-semibold">
                      {formatINR(totalAmt)}
                    </span>
                  </div>
                </div>
              );
            })}
          </div>
        </div>

        {/* Filter & Search Bar */}
        <div className="border border-border bg-surface p-4 space-y-4">
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="h-4 w-4 absolute left-3 top-2.5 text-ink-muted" />
              <input
                type="text"
                placeholder="Search by finding ID or reference..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-canvas border border-border focus:outline-none focus:border-ink-primary font-mono text-ink-primary"
              />
            </div>

            <div className="flex items-center gap-2">
              <select
                value={categoryFilter}
                onChange={(e) => setCategoryFilter(e.target.value)}
                className="text-xs bg-canvas border border-border px-3 py-1.5 text-ink-primary font-mono"
              >
                <option value="ALL">All Categories</option>
                <option value="MISSING_SETTLEMENT">Missing Settlements</option>
                <option value="UNCREDITED_SETTLEMENT">Uncredited Settlements</option>
                <option value="FEE_OVERCHARGE">Fee Overcharges</option>
                <option value="DUPLICATE_OR_EXCESS_REFUND">Refund Anomalies</option>
              </select>

              <select
                value={severityFilter}
                onChange={(e) => setSeverityFilter(e.target.value)}
                className="text-xs bg-canvas border border-border px-3 py-1.5 text-ink-primary font-mono"
              >
                <option value="ALL">All Severities</option>
                <option value="HIGH">High Severity</option>
                <option value="MEDIUM">Medium Severity</option>
                <option value="LOW">Low Severity</option>
              </select>
            </div>
          </div>

          {/* Findings Table */}
          <div className="border border-border overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-border bg-canvas text-ink-muted font-mono uppercase text-[10px]">
                  <th className="py-2.5 px-3">Finding ID</th>
                  <th className="py-2.5 px-3">Category</th>
                  <th className="py-2.5 px-3">Title / Description</th>
                  <th className="py-2.5 px-3 text-right">Expected</th>
                  <th className="py-2.5 px-3 text-right">Actual</th>
                  <th className="py-2.5 px-3 text-right">Discrepancy</th>
                  <th className="py-2.5 px-3 text-center">Severity</th>
                  <th className="py-2.5 px-3">Detection Date</th>
                  <th className="py-2.5 px-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {loading ? (
                  <tr>
                    <td colSpan={9} className="py-8 text-center text-ink-muted font-mono">
                      Querying leakage detectors...
                    </td>
                  </tr>
                ) : filteredFindings.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-8 text-center text-ink-muted">
                      No leakage findings matching current filters. All checked ledgers conform to tolerances.
                    </td>
                  </tr>
                ) : (
                  filteredFindings.map((f) => (
                    <tr key={f.id} className="hover:bg-hover transition-colors">
                      <td className="py-2.5 px-3 font-mono font-medium text-ink-primary">
                        {f.finding_id}
                      </td>
                      <td className="py-2.5 px-3 font-mono text-[11px] text-ink-secondary">
                        {f.category.replace(/_/g, " ")}
                      </td>
                      <td className="py-2.5 px-3 text-ink-primary max-w-xs truncate">
                        {f.title}
                      </td>
                      <td className="py-2.5 px-3 font-mono text-right text-ink-secondary">
                        {formatINR(f.expected_amount)}
                      </td>
                      <td className="py-2.5 px-3 font-mono text-right text-ink-secondary">
                        {formatINR(f.actual_amount)}
                      </td>
                      <td className="py-2.5 px-3 font-mono text-right font-semibold text-status-leakage-text">
                        {formatINR(f.difference)}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <Badge
                          variant={
                            f.severity === "HIGH"
                              ? "leakage"
                              : f.severity === "MEDIUM"
                              ? "pending"
                              : "matched"
                          }
                        >
                          {f.severity}
                        </Badge>
                      </td>
                      <td className="py-2.5 px-3 font-mono text-[11px] text-ink-muted">
                        {formatDateTime(f.detection_date)}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <button
                          onClick={() => setSelectedFinding(f)}
                          className="text-[11px] font-mono text-ink-primary hover:underline"
                        >
                          Evidence
                        </button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      {/* Evidence Drawer Modal */}
      {selectedFinding && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex justify-end">
          <div className="w-full max-w-md bg-surface border-l border-border h-full p-6 overflow-y-auto space-y-6">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <span className="text-[10px] font-mono uppercase text-ink-muted">
                  EVIDENCE PROVENANCE
                </span>
                <h3 className="text-base font-semibold text-ink-primary">
                  {selectedFinding.finding_id}
                </h3>
              </div>
              <button
                onClick={() => setSelectedFinding(null)}
                className="p-1 hover:bg-hover border border-border"
              >
                <X className="h-4 w-4 text-ink-secondary" />
              </button>
            </div>

            <div className="space-y-4 text-xs font-mono">
              <div className="p-3 border border-border bg-canvas space-y-1">
                <span className="text-[10px] text-ink-muted uppercase block">Description</span>
                <div className="text-ink-primary">{selectedFinding.title}</div>
              </div>

              <div className="grid grid-cols-2 gap-3">
                <div className="p-3 border border-border bg-canvas">
                  <span className="text-[10px] text-ink-muted uppercase block">Expected</span>
                  <div className="text-sm font-semibold text-ink-primary mt-1">
                    {formatINR(selectedFinding.expected_amount)}
                  </div>
                </div>
                <div className="p-3 border border-border bg-canvas">
                  <span className="text-[10px] text-ink-muted uppercase block">Discrepancy</span>
                  <div className="text-sm font-semibold text-status-leakage-text mt-1">
                    {formatINR(selectedFinding.difference)}
                  </div>
                </div>
              </div>

              <div className="space-y-2">
                <span className="text-[10px] text-ink-muted uppercase tracking-wider block">
                  Substantiating References
                </span>
                <div className="p-3 border border-border bg-canvas space-y-2 text-[11px]">
                  {Object.entries(selectedFinding.evidence_references).map(([key, value]) => (
                    <div key={key} className="flex justify-between border-b border-border pb-1">
                      <span className="text-ink-muted">{key}:</span>
                      <span className="text-ink-primary font-medium text-right max-w-xs break-all">
                        {typeof value === "object" ? JSON.stringify(value) : String(value)}
                      </span>
                    </div>
                  ))}
                </div>
              </div>

              <div className="pt-4 border-t border-border flex justify-end">
                <Button
                  onClick={() => setSelectedFinding(null)}
                  variant="outline"
                  size="sm"
                  className="w-full text-xs font-mono"
                >
                  Close Provenance View
                </Button>
              </div>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
