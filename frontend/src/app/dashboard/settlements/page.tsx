"use client";

import React, { useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR } from "@/lib/utils";
import { Landmark, Download, Search, CheckCircle2 } from "lucide-react";

export default function SettlementsPage() {
  const [search, setSearch] = useState("");

  const settlementBatches = [
    { batchId: "SETL-20261110-09", gateway: "Razorpay", bankUtr: "HDFCR5202611110098", txCount: 142, grossAmount: 1250000.0, feeDeductions: 28450.0, netCredited: 1221550.0, status: "CREDITED_MATCHED", date: "11 Nov 2026, 11:30" },
    { batchId: "SETL-20261111-01", gateway: "Razorpay", bankUtr: "HDFCR5202611110099", txCount: 89, grossAmount: 890000.0, feeDeductions: 19800.0, netCredited: 870200.0, status: "CREDITED_MATCHED", date: "11 Nov 2026, 17:45" },
    { batchId: "SETL-20261111-02", gateway: "Razorpay", bankUtr: "HDFCR5202611120014", txCount: 210, grossAmount: 1840000.0, feeDeductions: 41200.0, netCredited: 1798800.0, status: "CREDITED_MATCHED", date: "12 Nov 2026, 10:15" },
    { batchId: "SETL-20261112-PEND", gateway: "Razorpay", bankUtr: "PENDING_RTGS", txCount: 165, grossAmount: 1420000.0, feeDeductions: 31800.0, netCredited: 1388200.0, status: "IN_TRANSIT", date: "12 Nov 2026, 18:00 (Due)" },
  ];

  return (
    <>
      <Topbar title="Settlement Batches" breadcrumb="Workspace" />
      <main className="p-6 space-y-4 max-w-7xl mx-auto w-full">
        <div className="flex justify-between items-center border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Settlements & Nodal Credits
            </h1>
            <p className="text-xs text-ink-secondary mt-1">
              Gateway settlement batches linked to bank UTR references and RTGS/NEFT clearing entries.
            </p>
          </div>
          <Button variant="secondary" size="sm" className="flex items-center gap-1.5">
            <Download className="h-3.5 w-3.5" />
            <span>Export Settlements</span>
          </Button>
        </div>

        <div className="bg-surface border border-border p-3 flex items-center justify-between">
          <div className="relative flex-1 max-w-sm">
            <Search className="h-3.5 w-3.5 text-ink-muted absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search Settlement Batch ID or Bank UTR..."
              className="w-full pl-8 pr-3 py-1.5 border border-border bg-canvas text-xs font-mono text-ink-primary focus:outline-none"
            />
          </div>
          <span className="text-xs font-mono text-ink-muted">
            Nodal Account: HDFC Current (•••• 4912)
          </span>
        </div>

        <div className="bg-surface border border-border overflow-x-auto">
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-border bg-canvas/80 text-[11px] font-mono text-ink-muted uppercase">
                <th className="py-2.5 px-3">Batch ID</th>
                <th className="py-2.5 px-3">Gateway</th>
                <th className="py-2.5 px-3">Bank UTR</th>
                <th className="py-2.5 px-3 text-center">Transactions</th>
                <th className="py-2.5 px-3 text-right">Gross Capture</th>
                <th className="py-2.5 px-3 text-right">MDR & Tax</th>
                <th className="py-2.5 px-3 text-right">Net Credited</th>
                <th className="py-2.5 px-3">Clearing Date</th>
                <th className="py-2.5 px-3 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {settlementBatches.map((b) => (
                <tr key={b.batchId} className="hover:bg-hover/60 h-11">
                  <td className="py-2 px-3 font-mono font-medium text-ink-primary">{b.batchId}</td>
                  <td className="py-2 px-3 text-ink-secondary">{b.gateway}</td>
                  <td className="py-2 px-3 font-mono text-ink-primary">{b.bankUtr}</td>
                  <td className="py-2 px-3 font-mono text-center text-ink-secondary">{b.txCount} tx</td>
                  <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary">{formatINR(b.grossAmount)}</td>
                  <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-secondary">-{formatINR(b.feeDeductions)}</td>
                  <td className="py-2 px-3 font-mono text-right tabular-nums font-semibold text-ink-primary">{formatINR(b.netCredited)}</td>
                  <td className="py-2 px-3 text-ink-muted font-mono text-[11px]">{b.date}</td>
                  <td className="py-2 px-3 text-center">
                    <Badge variant={b.status === "CREDITED_MATCHED" ? "matched" : "pending"}>
                      {b.status}
                    </Badge>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}
