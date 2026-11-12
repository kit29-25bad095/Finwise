"use client";

import React, { useState, useEffect } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR, formatDateTime } from "@/lib/utils";
import { ApiClient, ReviewQueueItem, ReviewQueueResponse } from "@/lib/api";
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
  RefreshCw,
  X,
  Layers,
  ArrowRight,
  Sliders,
  DollarSign,
  AlertTriangle,
} from "lucide-react";

export default function ReviewQueuePage() {
  const [data, setData] = useState<ReviewQueueResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [statusFilter, setStatusFilter] = useState("ALL");
  const [searchQuery, setSearchQuery] = useState("");
  const [selectedItem, setSelectedItem] = useState<ReviewQueueItem | null>(null);

  // Review Decision State
  const [reviewAction, setReviewAction] = useState<"APPROVE" | "REJECT" | "MANUAL_ALLOCATE">("APPROVE");
  const [reviewNotes, setReviewNotes] = useState("");
  const [manualAmount, setManualAmount] = useState("");
  const [selectedCandidateId, setSelectedCandidateId] = useState<string>("");
  const [submitting, setSubmitting] = useState(false);

  // User RBAC
  const [userRole, setUserRole] = useState<string>("FINANCE_MANAGER");

  useEffect(() => {
    if (typeof window !== "undefined") {
      const role = localStorage.getItem("finora_active_role") || "FINANCE_MANAGER";
      setUserRole(role);
    }
  }, []);

  const isAuditor = userRole === "AUDITOR";

  const fetchQueue = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ApiClient.getReviewQueue(statusFilter === "ALL" ? undefined : statusFilter);
      setData(res);
    } catch (err: any) {
      setError(err.message || "Failed to load review queue.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchQueue();
  }, [statusFilter]);

  const handleOpenReview = (item: ReviewQueueItem) => {
    setSelectedItem(item);
    setReviewAction("APPROVE");
    setReviewNotes("");
    setManualAmount(item.discrepancy_amount ? String(item.discrepancy_amount) : "");
    if (item.candidates && item.candidates.length > 0) {
      setSelectedCandidateId(item.candidates[0].id);
    }
  };

  const handleResolve = async () => {
    if (!selectedItem) return;
    if (!reviewNotes.trim()) {
      alert("A mandatory review rationale must be provided for audit traceability.");
      return;
    }

    try {
      setSubmitting(true);
      await ApiClient.resolveMatch(
        selectedItem.match_id,
        reviewAction,
        reviewNotes,
        selectedCandidateId || undefined,
        reviewAction === "MANUAL_ALLOCATE" ? manualAmount : undefined
      );
      setSelectedItem(null);
      await fetchQueue();
    } catch (err: any) {
      alert("Failed to submit review decision: " + err.message);
    } finally {
      setSubmitting(false);
    }
  };

  const filteredItems = (data?.items || []).filter((item) => {
    if (!searchQuery) return true;
    const q = searchQuery.toLowerCase();
    return (
      item.match_id.toLowerCase().includes(q) ||
      item.classification.toLowerCase().includes(q) ||
      item.explanation.toLowerCase().includes(q)
    );
  });

  return (
    <div className="flex flex-col min-h-screen bg-canvas">
      <Topbar title="Financial Review Queue" breadcrumb="Investigation" />

      <main className="p-6 md:p-8 space-y-8 max-w-7xl mx-auto w-full">
        {/* RBAC Banner if Auditor */}
        {isAuditor && (
          <div className="p-3 border border-border bg-canvas flex items-center justify-between text-xs">
            <div className="flex items-center gap-2 text-ink-secondary">
              <ShieldCheck className="h-4 w-4" />
              <span>
                <strong>Auditor Role Detected:</strong> You have read-only inspection access.
                Decisions must be submitted by Finance Managers or Admins.
              </span>
            </div>
            <span className="font-mono text-[10px] uppercase text-ink-muted">READ ONLY</span>
          </div>
        )}

        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Human-in-the-Loop Review Workspace
            </h1>
            <p className="text-xs text-ink-secondary mt-0.5">
              Review ambiguous correlations, aggregation collisions, unresolved knapsack bounds, and tariff variances
            </p>
          </div>

          <Button
            onClick={fetchQueue}
            variant="outline"
            size="sm"
            disabled={loading}
            className="text-xs font-mono"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
            Refresh Queue
          </Button>
        </div>

        {/* Filter Bar */}
        <div className="border border-border bg-surface p-4 space-y-4">
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="relative flex-1 max-w-sm">
              <Search className="h-4 w-4 absolute left-3 top-2.5 text-ink-muted" />
              <input
                type="text"
                placeholder="Search by match ID, classification, or notes..."
                value={searchQuery}
                onChange={(e) => setSearchQuery(e.target.value)}
                className="w-full pl-9 pr-3 py-1.5 text-xs bg-canvas border border-border focus:outline-none focus:border-ink-primary font-mono text-ink-primary"
              />
            </div>

            <div className="flex items-center gap-2">
              <select
                value={statusFilter}
                onChange={(e) => setStatusFilter(e.target.value)}
                className="text-xs bg-canvas border border-border px-3 py-1.5 text-ink-primary font-mono"
              >
                <option value="ALL">All Items</option>
                <option value="PENDING_REVIEW">Pending Review</option>
                <option value="APPROVED">Approved</option>
                <option value="REJECTED">Rejected</option>
                <option value="RESOLVED">Resolved</option>
              </select>
            </div>
          </div>

          {/* Review Queue Table */}
          <div className="border border-border overflow-x-auto">
            <table className="w-full text-left border-collapse text-xs">
              <thead>
                <tr className="border-b border-border bg-canvas text-ink-muted font-mono uppercase text-[10px]">
                  <th className="py-2.5 px-3">Run</th>
                  <th className="py-2.5 px-3">Pass</th>
                  <th className="py-2.5 px-3">Classification</th>
                  <th className="py-2.5 px-3">Reason / Explanation</th>
                  <th className="py-2.5 px-3 text-right">Source</th>
                  <th className="py-2.5 px-3 text-right">Target</th>
                  <th className="py-2.5 px-3 text-right">Discrepancy</th>
                  <th className="py-2.5 px-3 text-center">Status</th>
                  <th className="py-2.5 px-3 text-center">Action</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border font-mono">
                {loading ? (
                  <tr>
                    <td colSpan={9} className="py-8 text-center text-ink-muted">
                      Querying pending review items...
                    </td>
                  </tr>
                ) : filteredItems.length === 0 ? (
                  <tr>
                    <td colSpan={9} className="py-8 text-center text-ink-muted">
                      No review queue items pending. All matches resolved or approved.
                    </td>
                  </tr>
                ) : (
                  filteredItems.map((item) => (
                    <tr key={item.match_id} className="hover:bg-hover transition-colors">
                      <td className="py-2.5 px-3 text-ink-primary font-semibold">
                        #{item.run_number}
                      </td>
                      <td className="py-2.5 px-3 text-ink-secondary">Pass {item.pass_number}</td>
                      <td className="py-2.5 px-3 font-semibold text-ink-primary">
                        {item.classification.replace(/_/g, " ")}
                      </td>
                      <td className="py-2.5 px-3 text-ink-secondary max-w-xs truncate font-sans">
                        {item.explanation}
                      </td>
                      <td className="py-2.5 px-3 text-right text-ink-primary">
                        {formatINR(item.source_amount)}
                      </td>
                      <td className="py-2.5 px-3 text-right text-ink-primary">
                        {formatINR(item.target_amount)}
                      </td>
                      <td className="py-2.5 px-3 text-right font-semibold text-status-leakage-text">
                        {formatINR(item.discrepancy_amount)}
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <Badge
                          variant={
                            item.review_status === "APPROVED" || item.review_status === "RESOLVED"
                              ? "matched"
                              : item.review_status === "REJECTED"
                              ? "leakage"
                              : "pending"
                          }
                        >
                          {item.review_status.replace(/_/g, " ")}
                        </Badge>
                      </td>
                      <td className="py-2.5 px-3 text-center">
                        <Button
                          onClick={() => handleOpenReview(item)}
                          variant="outline"
                          size="sm"
                          className="text-[11px] font-mono h-6 px-2.5"
                        >
                          Review
                        </Button>
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>

      {/* Decision Review Modal */}
      {selectedItem && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex items-center justify-center p-4">
          <div className="w-full max-w-2xl bg-surface border border-border p-6 shadow-xl space-y-6 max-h-[90vh] overflow-y-auto">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <span className="text-[10px] font-mono uppercase text-ink-muted">
                  FINANCIAL REVIEW DECISION
                </span>
                <h3 className="text-base font-semibold text-ink-primary">
                  {selectedItem.classification.replace(/_/g, " ")} (Pass {selectedItem.pass_number})
                </h3>
              </div>
              <button
                onClick={() => setSelectedItem(null)}
                className="p-1 hover:bg-hover border border-border"
              >
                <X className="h-4 w-4 text-ink-secondary" />
              </button>
            </div>

            {/* Evidence & Explanation Box */}
            <div className="p-4 border border-border bg-canvas space-y-3 text-xs font-mono">
              <div className="flex justify-between">
                <span className="text-ink-muted">Explanation:</span>
                <span className="text-ink-primary font-medium text-right max-w-md font-sans">
                  {selectedItem.explanation}
                </span>
              </div>
              <div className="grid grid-cols-3 gap-3 pt-2 border-t border-border">
                <div>
                  <span className="text-[10px] text-ink-muted block">SOURCE AMOUNT</span>
                  <span className="text-sm font-semibold text-ink-primary">
                    {formatINR(selectedItem.source_amount)}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-ink-muted block">TARGET AMOUNT</span>
                  <span className="text-sm font-semibold text-ink-primary">
                    {formatINR(selectedItem.target_amount)}
                  </span>
                </div>
                <div>
                  <span className="text-[10px] text-ink-muted block">DISCREPANCY</span>
                  <span className="text-sm font-semibold text-status-leakage-text">
                    {formatINR(selectedItem.discrepancy_amount)}
                  </span>
                </div>
              </div>
            </div>

            {/* If Candidates exist (Knapsack or Ambiguous Collision) */}
            {selectedItem.candidates && selectedItem.candidates.length > 0 && (
              <div className="space-y-2 text-xs font-mono">
                <span className="text-[10px] font-mono uppercase text-ink-muted block">
                  Competing Candidates ({selectedItem.candidates.length})
                </span>
                <div className="border border-border divide-y divide-border bg-canvas">
                  {selectedItem.candidates.map((c) => (
                    <label
                      key={c.id}
                      className="p-3 flex items-center justify-between cursor-pointer hover:bg-hover"
                    >
                      <div className="flex items-center gap-3">
                        <input
                          type="radio"
                          name="candidateSelection"
                          value={c.id}
                          checked={selectedCandidateId === c.id}
                          onChange={() => setSelectedCandidateId(c.id)}
                          disabled={isAuditor}
                        />
                        <div>
                          <div className="font-semibold text-ink-primary">{c.reference}</div>
                          {c.date && <div className="text-[10px] text-ink-muted">{c.date}</div>}
                        </div>
                      </div>
                      <div className="text-right">
                        <div className="font-semibold text-ink-primary">{formatINR(c.amount)}</div>
                        {c.score && (
                          <div className="text-[10px] text-ink-secondary">Score: {c.score}</div>
                        )}
                      </div>
                    </label>
                  ))}
                </div>
              </div>
            )}

            {/* Decision Input Controls */}
            {!isAuditor ? (
              <div className="space-y-4 pt-2 border-t border-border">
                <div className="space-y-2">
                  <label className="text-xs font-mono text-ink-primary block uppercase">
                    Select Decision Action
                  </label>
                  <div className="grid grid-cols-3 gap-3">
                    <button
                      type="button"
                      onClick={() => setReviewAction("APPROVE")}
                      className={`p-2.5 text-xs font-mono border text-center transition-colors ${
                        reviewAction === "APPROVE"
                          ? "border-ink-primary bg-ink-primary text-white"
                          : "border-border bg-surface text-ink-primary hover:bg-hover"
                      }`}
                    >
                      Approve Match
                    </button>
                    <button
                      type="button"
                      onClick={() => setReviewAction("REJECT")}
                      className={`p-2.5 text-xs font-mono border text-center transition-colors ${
                        reviewAction === "REJECT"
                          ? "border-status-leakage-text bg-status-leakage-bg text-status-leakage-text font-semibold"
                          : "border-border bg-surface text-ink-primary hover:bg-hover"
                      }`}
                    >
                      Reject Match
                    </button>
                    <button
                      type="button"
                      onClick={() => setReviewAction("MANUAL_ALLOCATE")}
                      className={`p-2.5 text-xs font-mono border text-center transition-colors ${
                        reviewAction === "MANUAL_ALLOCATE"
                          ? "border-status-pending-text bg-status-pending-bg text-status-pending-text font-semibold"
                          : "border-border bg-surface text-ink-primary hover:bg-hover"
                      }`}
                    >
                      Manual Allocate
                    </button>
                  </div>
                </div>

                {reviewAction === "MANUAL_ALLOCATE" && (
                  <div className="space-y-1">
                    <label className="text-[10px] font-mono text-ink-muted uppercase block">
                      Manual Allocation Amount (₹)
                    </label>
                    <input
                      type="text"
                      value={manualAmount}
                      onChange={(e) => setManualAmount(e.target.value)}
                      placeholder="e.g. 5000.0000"
                      className="w-full px-3 py-1.5 text-xs bg-canvas border border-border font-mono text-ink-primary"
                    />
                  </div>
                )}

                <div className="space-y-1">
                  <label className="text-[10px] font-mono text-ink-muted uppercase block">
                    Mandatory Review Rationale (Auditable Evidence Note) *
                  </label>
                  <textarea
                    rows={3}
                    value={reviewNotes}
                    onChange={(e) => setReviewNotes(e.target.value)}
                    placeholder="State justification, ledger ticket reference, or reason for decision..."
                    className="w-full p-2.5 text-xs bg-canvas border border-border font-sans text-ink-primary focus:outline-none focus:border-ink-primary"
                  />
                </div>

                <div className="flex justify-end gap-3 pt-2">
                  <Button
                    onClick={() => setSelectedItem(null)}
                    variant="outline"
                    size="sm"
                    className="text-xs font-mono"
                  >
                    Cancel
                  </Button>
                  <Button
                    onClick={handleResolve}
                    size="sm"
                    disabled={submitting}
                    className="text-xs font-mono"
                  >
                    {submitting ? "Registering Decision..." : "Submit Review Decision"}
                  </Button>
                </div>
              </div>
            ) : (
              <div className="p-3 border border-border bg-canvas text-center text-xs text-ink-secondary">
                Review decision submission is disabled for Auditor accounts.
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );
}
