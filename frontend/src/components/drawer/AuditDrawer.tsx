"use client";

import React, { useState } from "react";
import { X, Copy, Check, ArrowDown, FileText, AlertCircle, ShieldCheck, Download } from "lucide-react";
import { formatINR } from "@/lib/utils";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";

export interface TransactionAuditItem {
  id: string;
  orderId: string;
  paymentId: string;
  gatewayRef: string;
  settlementRef: string;
  bankUtr: string;
  orderDate: string;
  shopifyGross: number;
  gatewayCapture: number;
  mdrFee: number;
  applicableGst: number;
  refundsAdjustments: number;
  settlementNet: number;
  bankCredit: number;
  variance: number;
  matchStatus: "MATCHED_PASS_1" | "MATCHED_PASS_2" | "MATCHED_PASS_4" | "LEAKAGE_OVERCHARGE" | "LEAKAGE_MISSING_SETTLEMENT" | "UNRESOLVED";
  matchingMethod: string;
  ruleVersion: string;
  runId: string;
  sourceFile: string;
  sourceRow: number;
  investigation?: {
    hypotheses: string[];
    supportingEvidence: string[];
    contradictingEvidence: string[];
    missingInformation: string[];
    recommendedSteps: string[];
  };
  disputeDraft?: string;
}

interface AuditDrawerProps {
  item: TransactionAuditItem | null;
  isOpen: boolean;
  onClose: () => void;
}

export function AuditDrawer({ item, isOpen, onClose }: AuditDrawerProps) {
  const [copiedDraft, setCopiedDraft] = useState(false);
  const [activeTab, setActiveTab] = useState<"flow" | "evidence" | "investigation" | "dispute">("flow");

  if (!isOpen || !item) return null;

  const handleCopyDraft = () => {
    if (item.disputeDraft) {
      navigator.clipboard.writeText(item.disputeDraft);
      setCopiedDraft(true);
      setTimeout(() => setCopiedDraft(false), 2000);
    }
  };

  const getStatusBadgeVariant = (status: TransactionAuditItem["matchStatus"]) => {
    if (status.startsWith("LEAKAGE")) return "leakage";
    if (status === "UNRESOLVED") return "pending";
    return "matched";
  };

  return (
    <div className="fixed inset-0 z-50 overflow-hidden bg-black/20 backdrop-blur-[1px]">
      <div className="absolute inset-0" onClick={onClose} />

      <aside className="fixed inset-y-0 right-0 w-[480px] max-w-full bg-surface border-l border-border shadow-lg flex flex-col justify-between overflow-y-auto">
        {/* Header */}
        <div className="p-5 border-b border-border bg-canvas/40 sticky top-0 z-10">
          <div className="flex items-center justify-between mb-2">
            <div className="flex items-center gap-2">
              <span className="text-[11px] font-mono uppercase text-ink-muted">AUDIT DOSSIER</span>
              <Badge variant={getStatusBadgeVariant(item.matchStatus)}>
                {item.matchStatus}
              </Badge>
            </div>
            <button
              onClick={onClose}
              className="p-1 text-ink-muted hover:text-ink-primary hover:bg-hover transition-colors"
            >
              <X className="h-4 w-4" strokeWidth={1.5} />
            </button>
          </div>

          <h2 className="text-base font-semibold text-ink-primary tracking-tight font-mono">
            {item.orderId}
          </h2>
          <div className="text-xs text-ink-secondary mt-0.5">
            Gateway Ref: <span className="font-mono text-ink-primary">{item.paymentId}</span>
          </div>

          {/* Sub-tabs */}
          <div className="flex gap-2 mt-4 border-b border-border text-xs">
            <button
              onClick={() => setActiveTab("flow")}
              className={`pb-2 font-medium border-b-2 -mb-[1px] transition-colors ${
                activeTab === "flow" ? "border-brand-black text-ink-primary" : "border-transparent text-ink-muted hover:text-ink-secondary"
              }`}
            >
              Financial Flow
            </button>
            <button
              onClick={() => setActiveTab("evidence")}
              className={`pb-2 font-medium border-b-2 -mb-[1px] transition-colors ${
                activeTab === "evidence" ? "border-brand-black text-ink-primary" : "border-transparent text-ink-muted hover:text-ink-secondary"
              }`}
            >
              Matching Evidence
            </button>
            <button
              onClick={() => setActiveTab("investigation")}
              className={`pb-2 font-medium border-b-2 -mb-[1px] transition-colors ${
                activeTab === "investigation" ? "border-brand-black text-ink-primary" : "border-transparent text-ink-muted hover:text-ink-secondary"
              }`}
            >
              AI Investigation
            </button>
            <button
              onClick={() => setActiveTab("dispute")}
              className={`pb-2 font-medium border-b-2 -mb-[1px] transition-colors ${
                activeTab === "dispute" ? "border-brand-black text-ink-primary" : "border-transparent text-ink-muted hover:text-ink-secondary"
              }`}
            >
              Dispute Draft
            </button>
          </div>
        </div>

        {/* Body Content */}
        <div className="p-5 space-y-6 flex-1 text-xs">
          {/* TAB 1: FINANCIAL FLOW & VARIANCE */}
          {activeTab === "flow" && (
            <div className="space-y-6">
              {/* Identity Matrix */}
              <div className="border border-border p-3.5 bg-canvas/30 space-y-2">
                <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                  A. TRANSACTION IDENTIFIERS
                </div>
                <div className="grid grid-cols-2 gap-2 text-xs font-mono">
                  <div>
                    <span className="text-ink-muted text-[10px] block">ORDER ID</span>
                    <span className="text-ink-primary">{item.orderId}</span>
                  </div>
                  <div>
                    <span className="text-ink-muted text-[10px] block">GATEWAY PAYMENT ID</span>
                    <span className="text-ink-primary">{item.paymentId}</span>
                  </div>
                  <div>
                    <span className="text-ink-muted text-[10px] block">SETTLEMENT BATCH</span>
                    <span className="text-ink-primary">{item.settlementRef}</span>
                  </div>
                  <div>
                    <span className="text-ink-muted text-[10px] block">BANK UTR NUMBER</span>
                    <span className="text-ink-primary">{item.bankUtr}</span>
                  </div>
                </div>
              </div>

              {/* Waterfall Flow */}
              <div className="space-y-2">
                <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                  B. RECONCILIATION WATERFALL
                </div>
                <div className="border border-border p-3 space-y-2 bg-surface">
                  <div className="flex justify-between items-center py-1 border-b border-border/50">
                    <span className="text-ink-secondary">Shopify Gross</span>
                    <span className="font-mono text-ink-primary tabular-nums">{formatINR(item.shopifyGross)}</span>
                  </div>
                  <div className="flex justify-center text-ink-muted">
                    <ArrowDown className="h-3 w-3" />
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/50">
                    <span className="text-ink-secondary">Gateway Capture</span>
                    <span className="font-mono text-ink-primary tabular-nums">{formatINR(item.gatewayCapture)}</span>
                  </div>
                  <div className="flex justify-center text-ink-muted">
                    <ArrowDown className="h-3 w-3" />
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/50">
                    <span className="text-ink-secondary">Contractual MDR</span>
                    <span className="font-mono text-ink-secondary tabular-nums">-{formatINR(item.mdrFee)}</span>
                  </div>
                  <div className="flex justify-center text-ink-muted">
                    <ArrowDown className="h-3 w-3" />
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/50">
                    <span className="text-ink-secondary">Applicable GST (18%)</span>
                    <span className="font-mono text-ink-secondary tabular-nums">-{formatINR(item.applicableGst)}</span>
                  </div>
                  <div className="flex justify-center text-ink-muted">
                    <ArrowDown className="h-3 w-3" />
                  </div>
                  <div className="flex justify-between items-center py-1 border-b border-border/50">
                    <span className="text-ink-secondary">Refunds / Adjustments</span>
                    <span className="font-mono text-ink-secondary tabular-nums">-{formatINR(item.refundsAdjustments)}</span>
                  </div>
                  <div className="flex justify-center text-ink-muted">
                    <ArrowDown className="h-3 w-3" />
                  </div>
                  <div className="flex justify-between items-center py-1 bg-canvas p-1.5 border border-border">
                    <span className="font-medium text-ink-primary">Expected Net Settlement</span>
                    <span className="font-mono font-semibold text-ink-primary tabular-nums">{formatINR(item.settlementNet)}</span>
                  </div>
                </div>
              </div>

              {/* Exact Variance Analysis */}
              <div className="space-y-2">
                <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                  C. VARIANCE AUDIT
                </div>
                <div className="border border-border p-3.5 space-y-2 bg-surface">
                  <div className="flex justify-between text-xs">
                    <span className="text-ink-secondary">Expected Net Settlement:</span>
                    <span className="font-mono tabular-nums text-ink-primary">{formatINR(item.settlementNet)}</span>
                  </div>
                  <div className="flex justify-between text-xs">
                    <span className="text-ink-secondary">Actual Bank Credit Received:</span>
                    <span className="font-mono tabular-nums text-ink-primary">{formatINR(item.bankCredit)}</span>
                  </div>
                  <div className="pt-2 border-t border-border flex justify-between text-xs items-center">
                    <span className="font-semibold text-ink-primary">Deterministic Variance:</span>
                    <span
                      className={`font-mono font-bold tabular-nums text-sm ${
                        item.variance !== 0 ? "text-[#DC2626]" : "text-ink-primary"
                      }`}
                    >
                      {formatINR(item.variance)}
                    </span>
                  </div>
                </div>
                <p className="text-[10px] text-ink-muted italic">
                  Deterministic backend calculation using arbitrary-precision Decimals. Zero AI calculation delegated.
                </p>
              </div>
            </div>
          )}

          {/* TAB 2: MATCHING EVIDENCE */}
          {activeTab === "evidence" && (
            <div className="space-y-4">
              <div className="border border-border p-3.5 space-y-3 bg-canvas/30">
                <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                  PROVENANCE & MATCHING METRICS
                </div>
                <div className="space-y-2 font-mono text-xs">
                  <div>
                    <span className="text-ink-muted text-[10px] block">MATCHING PASS & METHOD</span>
                    <span className="text-ink-primary">{item.matchingMethod}</span>
                  </div>
                  <div>
                    <span className="text-ink-muted text-[10px] block">RECONCILIATION RULE VERSION</span>
                    <span className="text-ink-primary">{item.ruleVersion}</span>
                  </div>
                  <div>
                    <span className="text-ink-muted text-[10px] block">RECONCILIATION RUN ID</span>
                    <span className="text-ink-primary">{item.runId}</span>
                  </div>
                  <div>
                    <span className="text-ink-muted text-[10px] block">SOURCE CSV PROVENANCE</span>
                    <span className="text-ink-primary">{item.sourceFile} (Row #{item.sourceRow})</span>
                  </div>
                </div>
              </div>

              <div className="border border-border p-3 space-y-2 bg-surface">
                <div className="text-[11px] font-semibold text-ink-primary flex items-center gap-1.5">
                  <ShieldCheck className="h-4 w-4 text-zinc-700" strokeWidth={1.5} />
                  Traceability Hash Verified
                </div>
                <p className="text-xs text-ink-secondary leading-relaxed">
                  Both the gross capture and bank credit nodal deposit contain matching references confirmed against cryptographic file checksums.
                </p>
              </div>
            </div>
          )}

          {/* TAB 3: AI FORENSIC INVESTIGATION */}
          {activeTab === "investigation" && (
            <div className="space-y-4">
              <div className="border border-border p-3.5 space-y-3 bg-surface">
                <div className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                  E. FORENSIC HYPOTHESIS & CITATION
                </div>

                {item.investigation ? (
                  <div className="space-y-4">
                    <div>
                      <span className="text-[11px] font-semibold text-ink-primary block mb-1">
                        Root-Cause Hypothesis
                      </span>
                      <ul className="list-disc pl-4 space-y-1 text-ink-secondary">
                        {item.investigation.hypotheses.map((h, i) => (
                          <li key={i}>{h}</li>
                        ))}
                      </ul>
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-ink-primary block mb-1">
                        Supporting Evidence
                      </span>
                      <ul className="list-disc pl-4 space-y-1 text-ink-secondary font-mono text-[11px]">
                        {item.investigation.supportingEvidence.map((s, i) => (
                          <li key={i}>{s}</li>
                        ))}
                      </ul>
                    </div>

                    <div>
                      <span className="text-[11px] font-semibold text-ink-primary block mb-1">
                        Contradicting / Inconclusive Evidence
                      </span>
                      <ul className="list-disc pl-4 space-y-1 text-ink-secondary">
                        {item.investigation.contradictingEvidence.map((c, i) => (
                          <li key={i}>{c}</li>
                        ))}
                      </ul>
                    </div>

                    <div className="bg-canvas border border-border p-2.5">
                      <span className="text-[10px] font-semibold uppercase font-mono text-ink-primary block mb-1">
                        Recommended Next Action
                      </span>
                      <p className="text-xs text-ink-secondary">
                        {item.investigation.recommendedSteps[0] || "Review gateway rate schedule."}
                      </p>
                    </div>
                  </div>
                ) : (
                  <p className="text-xs text-ink-muted italic">
                    No active anomaly detected requiring forensic AI investigation for this transaction.
                  </p>
                )}
              </div>
            </div>
          )}

          {/* TAB 4: DISPUTE DRAFT */}
          {activeTab === "dispute" && (
            <div className="space-y-4">
              <div className="flex items-center justify-between">
                <span className="text-[10px] uppercase font-mono text-ink-muted font-semibold">
                  F. EVIDENCE-BASED DISPUTE DRAFT
                </span>
                <button
                  onClick={handleCopyDraft}
                  className="flex items-center gap-1 text-[11px] font-mono text-ink-secondary hover:text-ink-primary"
                >
                  {copiedDraft ? <Check className="h-3 w-3 text-zinc-800" /> : <Copy className="h-3 w-3" />}
                  <span>{copiedDraft ? "COPIED" : "COPY DRAFT"}</span>
                </button>
              </div>

              <textarea
                readOnly
                value={
                  item.disputeDraft ||
                  `DISPUTE CLAIM: OVERCHARGE RECOVERY\nMerchant: Finora Production Enterprise\nOrder Ref: ${item.orderId}\nPayment ID: ${item.paymentId}\nUTR Reference: ${item.bankUtr}\nDiscrepancy: ${formatINR(item.variance)}\n\nEvidence Summary:\nContractual Tariff: 1.85% + 18% GST\nApplied Gateway MDR: 2.15%\nTotal Unjustified Surcharge: ${formatINR(Math.abs(item.variance))}\n\nPlease credit the excess deduction to merchant settlement nodal account.`
                }
                rows={10}
                className="w-full text-xs font-mono p-3 bg-canvas border border-border text-ink-primary focus:outline-none resize-none leading-relaxed"
              />

              <div className="p-3 border border-border bg-canvas/40 text-[11px] text-ink-secondary space-y-1">
                <div className="font-semibold text-ink-primary flex items-center gap-1.5">
                  <AlertCircle className="h-3.5 w-3.5 text-ink-muted" />
                  Human Approval Mandate
                </div>
                <p>
                  Finora never automatically transmits dispute claims. Finance team review and authorized CA submission is strictly required.
                </p>
              </div>
            </div>
          )}
        </div>

        {/* Footer */}
        <div className="p-4 border-t border-border bg-surface flex items-center justify-between sticky bottom-0">
          <Button variant="secondary" size="sm" onClick={onClose}>
            Close Dossier
          </Button>
          <Button
            variant="primary"
            size="sm"
            onClick={handleCopyDraft}
            className="flex items-center gap-1.5"
          >
            <Download className="h-3.5 w-3.5" strokeWidth={1.5} />
            <span>Export Evidence Pack</span>
          </Button>
        </div>
      </aside>
    </div>
  );
}
