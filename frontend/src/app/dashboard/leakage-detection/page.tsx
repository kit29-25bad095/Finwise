"use client";

import React from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR } from "@/lib/utils";
import { Radar, Sliders, ShieldCheck } from "lucide-react";

export default function LeakageDetectionPage() {
  const detectors = [
    {
      id: "DETECTOR-1",
      name: "Missing Gateway Settlement",
      description: "Identifies captured transactions where settlement batch has not arrived after contractual due date (T+2 cutoff).",
      formula: "DueDate = AddBusinessDays(CaptureDate, T_contract, Calendar_RBI)",
      tolerance: "0.00 (Zero Tolerance)",
      leakageCount: 1,
      leakageValue: 13890.01,
      status: "ACTIVE",
    },
    {
      id: "DETECTOR-2",
      name: "Settlement Not Credited to Bank",
      description: "Detects settlement batches marked 'settled' with valid UTR references that never appeared in the verified bank statement.",
      formula: "Delta_Bank = NetSettlementAmount - Sum(AllocatedBankCredit)",
      tolerance: "0.00 (Zero Tolerance)",
      leakageCount: 0,
      leakageValue: 0.0,
      status: "ACTIVE",
    },
    {
      id: "DETECTOR-3",
      name: "Contractual Fee Overcharge",
      description: "Compares applied gateway MDR and GST against the merchant's signed fee schedule across payment instruments.",
      formula: "Delta_Fee = (ReportedFee + ReportedTax) - (ContractBaseFee + ContractGST)",
      tolerance: "₹0.05 (Sub-paisa rounding buffer)",
      leakageCount: 32,
      leakageValue: 22109.99,
      status: "ACTIVE",
    },
    {
      id: "DETECTOR-4",
      name: "Duplicate or Unauthorized Refund",
      description: "Flags refunds exceeding original gross capture, duplicate gateway refund IDs, or refunds with no Shopify return event.",
      formula: "Delta_Excess = max(0, Sum(RefundAmount) - CapturedAmount)",
      tolerance: "0.00 (Zero Tolerance)",
      leakageCount: 0,
      leakageValue: 0.0,
      status: "ACTIVE",
    },
  ];

  return (
    <>
      <Topbar title="Leakage Detection Architecture" breadcrumb="Investigation" />
      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        <div className="border-b border-border pb-4">
          <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
            The Four Core Leakage Detectors
          </h1>
          <p className="text-xs text-ink-secondary mt-1">
            Deterministic mathematical engines executing continuously without AI delegation.
          </p>
        </div>

        <div className="grid grid-cols-1 md:grid-cols-2 gap-4">
          {detectors.map((d) => (
            <div key={d.id} className="bg-surface border border-border p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-border pb-2.5">
                <span className="text-[11px] font-mono text-ink-muted uppercase">{d.id}</span>
                <Badge variant={d.leakageCount > 0 ? "leakage" : "matched"}>
                  {d.leakageCount > 0 ? `${d.leakageCount} LEAKAGES` : "HEALTHY"}
                </Badge>
              </div>

              <div>
                <h2 className="text-sm font-semibold text-ink-primary">{d.name}</h2>
                <p className="text-xs text-ink-secondary mt-1 leading-relaxed">{d.description}</p>
              </div>

              <div className="bg-canvas border border-border p-2.5 font-mono text-[11px] text-ink-secondary space-y-1">
                <div>FORMULA: <span className="text-ink-primary font-semibold">{d.formula}</span></div>
                <div>TOLERANCE: <span className="text-ink-primary">{d.tolerance}</span></div>
              </div>

              <div className="flex items-center justify-between pt-2 border-t border-border text-xs font-mono">
                <span className="text-ink-secondary">QUANTIFIED LOSS:</span>
                <span className={`font-semibold ${d.leakageValue > 0 ? "text-[#DC2626]" : "text-ink-primary"}`}>
                  {formatINR(d.leakageValue)}
                </span>
              </div>
            </div>
          ))}
        </div>
      </main>
    </>
  );
}
