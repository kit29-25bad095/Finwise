"use client";

import React, { useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR } from "@/lib/utils";
import { FileSpreadsheet, Download, Send, Check } from "lucide-react";

export default function DisputesPage() {
  const claims = [
    {
      id: "DISP-2026-0012",
      gateway: "Razorpay",
      claimType: "MDR Tariff Overcharge",
      totalClaimAmount: 36000.0,
      affectedTxCount: 32,
      evidencePackStatus: "PACK_GENERATED",
      approvalStatus: "HUMAN_APPROVED",
      dateCreated: "12 Nov 2026",
    },
    {
      id: "DISP-2026-0013",
      gateway: "Razorpay",
      claimType: "Delayed Settlement Release",
      totalClaimAmount: 13890.01,
      affectedTxCount: 1,
      evidencePackStatus: "PENDING_APPROVAL",
      approvalStatus: "UNDER_REVIEW",
      dateCreated: "12 Nov 2026",
    },
  ];

  return (
    <>
      <Topbar title="Dispute Management" breadcrumb="Investigation" />
      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        <div className="flex justify-between items-center border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Dispute Claims & Recovery Packs
            </h1>
            <p className="text-xs text-ink-secondary mt-1">
              Forensic recovery packages substantiated with contractual tariffs and bank statement evidence.
            </p>
          </div>
          <span className="text-[11px] font-mono text-ink-muted">
            Mandate: No automated submission without human CA sign-off.
          </span>
        </div>

        <div className="space-y-4">
          {claims.map((claim) => (
            <div key={claim.id} className="bg-surface border border-border p-5 space-y-3">
              <div className="flex items-center justify-between border-b border-border pb-2.5">
                <div className="flex items-center gap-3">
                  <span className="font-mono text-xs font-semibold text-ink-primary">{claim.id}</span>
                  <span className="text-xs text-ink-secondary">Gateway: <strong>{claim.gateway}</strong></span>
                </div>
                <Badge variant={claim.approvalStatus === "HUMAN_APPROVED" ? "matched" : "pending"}>
                  {claim.approvalStatus}
                </Badge>
              </div>

              <div className="grid grid-cols-2 md:grid-cols-4 gap-3 text-xs font-mono">
                <div>
                  <span className="text-ink-muted text-[10px] block">DISPUTE CATEGORY</span>
                  <span className="text-ink-primary font-medium">{claim.claimType}</span>
                </div>
                <div>
                  <span className="text-ink-muted text-[10px] block">CLAIM AMOUNT</span>
                  <span className="text-ink-primary font-semibold text-[#DC2626]">{formatINR(claim.totalClaimAmount)}</span>
                </div>
                <div>
                  <span className="text-ink-muted text-[10px] block">AFFECTED TRANSACTIONS</span>
                  <span className="text-ink-primary">{claim.affectedTxCount} items</span>
                </div>
                <div>
                  <span className="text-ink-muted text-[10px] block">DATE COMPILED</span>
                  <span className="text-ink-primary">{claim.dateCreated}</span>
                </div>
              </div>

              <div className="flex items-center justify-between pt-3 border-t border-border">
                <span className="text-[11px] font-mono text-ink-secondary">
                  EVIDENCE ATTACHED: Contract Schedule B.pdf, Nodal Bank Statement.csv, Gateway Fee Report.csv
                </span>
                <div className="flex items-center gap-2">
                  <Button variant="secondary" size="sm" className="flex items-center gap-1">
                    <Download className="h-3 w-3" />
                    <span>Download Evidence Pack (ZIP)</span>
                  </Button>
                </div>
              </div>
            </div>
          ))}
        </div>
      </main>
    </>
  );
}
