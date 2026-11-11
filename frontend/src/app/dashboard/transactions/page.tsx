"use client";

import React, { useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR } from "@/lib/utils";
import { Search, Download, ArrowLeftRight } from "lucide-react";

export default function TransactionsPage() {
  const [search, setSearch] = useState("");

  const transactions = [
    { id: "ORD-98420", paymentId: "pay_Oz91M202Kaa", method: "UPI", gross: 15400.0, fee: 284.9, tax: 51.28, net: 15063.82, date: "10 Nov 2026", status: "MATCHED" },
    { id: "ORD-98421", paymentId: "pay_Oz91M203Nba", method: "Cards (Visa)", gross: 12500.0, fee: 231.25, tax: 41.63, net: 12227.12, date: "10 Nov 2026", status: "MATCHED" },
    { id: "ORD-98422", paymentId: "pay_Oz91M204Kpq", method: "Cards (Corp)", gross: 8400.0, fee: 180.6, tax: 32.51, net: 8186.89, date: "10 Nov 2026", status: "LEAKAGE_OVERCHARGE" },
    { id: "ORD-98423", paymentId: "pay_Oz91M205Zaa", method: "Netbanking", gross: 14200.0, fee: 262.7, tax: 47.29, net: 13890.01, date: "08 Nov 2026", status: "LEAKAGE_MISSING" },
    { id: "ORD-98424", paymentId: "pay_Oz91M206Cdd", method: "UPI", gross: 6200.0, fee: 114.7, tax: 20.65, net: 6064.65, date: "09 Nov 2026", status: "MATCHED" },
    { id: "ORD-98425", paymentId: "pay_Oz91M207Rtt", method: "Cards (Mastercard)", gross: 29500.0, fee: 545.75, tax: 98.24, net: 28856.01, date: "09 Nov 2026", status: "MATCHED" },
  ];

  return (
    <>
      <Topbar title="Transactions Ledger" breadcrumb="Workspace" />
      <main className="p-6 space-y-4 max-w-7xl mx-auto w-full">
        <div className="flex justify-between items-center border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Transactions
            </h1>
            <p className="text-xs text-ink-secondary mt-1">
              Authoritative transaction capture events ingested from order management and payment gateways.
            </p>
          </div>
          <Button variant="secondary" size="sm" className="flex items-center gap-1.5">
            <Download className="h-3.5 w-3.5" />
            <span>Export CSV</span>
          </Button>
        </div>

        <div className="bg-surface border border-border p-3 flex items-center justify-between">
          <div className="relative flex-1 max-w-sm">
            <Search className="h-3.5 w-3.5 text-ink-muted absolute left-2.5 top-1/2 -translate-y-1/2" />
            <input
              type="text"
              value={search}
              onChange={(e) => setSearch(e.target.value)}
              placeholder="Search by Order ID or Payment ID..."
              className="w-full pl-8 pr-3 py-1.5 border border-border bg-canvas text-xs font-mono text-ink-primary focus:outline-none"
            />
          </div>
          <span className="text-xs font-mono text-ink-muted">
            Showing {transactions.length} canonical records
          </span>
        </div>

        <div className="bg-surface border border-border overflow-x-auto">
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-border bg-canvas/80 text-[11px] font-mono text-ink-muted uppercase">
                <th className="py-2.5 px-3">Order ID</th>
                <th className="py-2.5 px-3">Payment ID</th>
                <th className="py-2.5 px-3">Instrument</th>
                <th className="py-2.5 px-3">Date</th>
                <th className="py-2.5 px-3 text-right">Gross Capture</th>
                <th className="py-2.5 px-3 text-right">MDR Fee</th>
                <th className="py-2.5 px-3 text-right">GST (18%)</th>
                <th className="py-2.5 px-3 text-right">Net Settlement</th>
                <th className="py-2.5 px-3 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {transactions.map((tx) => (
                <tr key={tx.id} className="hover:bg-hover/60 h-11">
                  <td className="py-2 px-3 font-mono font-medium text-ink-primary">{tx.id}</td>
                  <td className="py-2 px-3 font-mono text-ink-secondary">{tx.paymentId}</td>
                  <td className="py-2 px-3 text-ink-secondary">{tx.method}</td>
                  <td className="py-2 px-3 text-ink-muted">{tx.date}</td>
                  <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-primary">{formatINR(tx.gross)}</td>
                  <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-secondary">-{formatINR(tx.fee)}</td>
                  <td className="py-2 px-3 font-mono text-right tabular-nums text-ink-secondary">-{formatINR(tx.tax)}</td>
                  <td className="py-2 px-3 font-mono text-right tabular-nums font-medium text-ink-primary">{formatINR(tx.net)}</td>
                  <td className="py-2 px-3 text-center">
                    <Badge variant={tx.status.startsWith("LEAKAGE") ? "leakage" : "matched"}>
                      {tx.status}
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
