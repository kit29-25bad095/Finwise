"use client";

import React from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { FileCheck2, Plus, Shield } from "lucide-react";

export default function ContractsPage() {
  const rateCards = [
    { instrument: "UPI (Standard)", contractMdr: "0.00%", gstRate: "0%", effectiveDate: "01 Jan 2026", status: "ACTIVE" },
    { instrument: "Domestic Debit Cards (RuPay)", contractMdr: "0.00%", gstRate: "0%", effectiveDate: "01 Jan 2026", status: "ACTIVE" },
    { instrument: "Domestic Debit Cards (Visa/Mastercard)", contractMdr: "0.90%", gstRate: "18%", effectiveDate: "01 Jan 2026", status: "ACTIVE" },
    { instrument: "Domestic Credit Cards (Consumer)", contractMdr: "1.85%", gstRate: "18%", effectiveDate: "01 Jan 2026", status: "ACTIVE" },
    { instrument: "Corporate / Commercial Credit Cards", contractMdr: "2.15%", gstRate: "18%", effectiveDate: "01 Jan 2026", status: "ACTIVE" },
    { instrument: "Netbanking (Top 10 Banks)", contractMdr: "₹15.00 flat", gstRate: "18%", effectiveDate: "01 Jan 2026", status: "ACTIVE" },
  ];

  return (
    <>
      <Topbar title="Fee Contracts & Tariffs" breadcrumb="Data" />
      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        <div className="flex justify-between items-center border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Contractual Fee Schedules
            </h1>
            <p className="text-xs text-ink-secondary mt-1">
              Deterministic tariff cards used by Detector 3 to identify fee overcharges. Zero hardcoded universal fee assumptions.
            </p>
          </div>
          <Button variant="secondary" size="sm" className="flex items-center gap-1.5">
            <Plus className="h-3.5 w-3.5" />
            <span>Upload New Fee Schedule</span>
          </Button>
        </div>

        <div className="bg-surface border border-border p-4 space-y-3">
          <div className="flex items-center justify-between border-b border-border pb-2">
            <div>
              <span className="text-[10px] uppercase font-mono text-ink-muted">GATEWAY PARTNER</span>
              <h2 className="text-sm font-semibold text-ink-primary">Razorpay Merchant Agreement (Schedule B)</h2>
            </div>
            <Badge variant="matched">ACTIVE VERSION: 2026.1</Badge>
          </div>

          <div className="overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse">
              <thead>
                <tr className="border-b border-border bg-canvas text-[11px] font-mono text-ink-muted uppercase">
                  <th className="py-2 px-3">Payment Instrument</th>
                  <th className="py-2 px-3 text-right">Contracted Base MDR</th>
                  <th className="py-2 px-3 text-right">GST Rate</th>
                  <th className="py-2 px-3">Effective Date</th>
                  <th className="py-2 px-3 text-center">Status</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {rateCards.map((rc, i) => (
                  <tr key={i} className="hover:bg-hover/60 h-10">
                    <td className="py-2 px-3 font-medium text-ink-primary">{rc.instrument}</td>
                    <td className="py-2 px-3 font-mono text-right text-ink-primary tabular-nums">{rc.contractMdr}</td>
                    <td className="py-2 px-3 font-mono text-right text-ink-secondary tabular-nums">{rc.gstRate}</td>
                    <td className="py-2 px-3 font-mono text-ink-muted">{rc.effectiveDate}</td>
                    <td className="py-2 px-3 text-center">
                      <Badge variant="matched">{rc.status}</Badge>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </>
  );
}
