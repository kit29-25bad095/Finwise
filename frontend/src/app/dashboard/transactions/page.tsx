"use client";

import React, { useState, useEffect } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR, formatDateTime } from "@/lib/utils";
import { ApiClient } from "@/lib/api";
import {
  Search,
  Download,
  ArrowLeftRight,
  RefreshCw,
  Sliders,
  ChevronLeft,
  ChevronRight,
  X,
  CreditCard,
  ShoppingBag,
} from "lucide-react";

export default function TransactionsPage() {
  const [activeTab, setActiveTab] = useState<"PAYMENTS" | "ORDERS">("PAYMENTS");
  const [payments, setPayments] = useState<any[]>([]);
  const [orders, setOrders] = useState<any[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [selectedTx, setSelectedTx] = useState<any | null>(null);

  // Pagination
  const [page, setPage] = useState(1);
  const limit = 25;

  const fetchData = async () => {
    try {
      setLoading(true);
      setError(null);
      if (activeTab === "PAYMENTS") {
        const res = await ApiClient.listCanonicalPayments(limit, (page - 1) * limit);
        setPayments(res);
      } else {
        const res = await ApiClient.listCanonicalOrders(limit, (page - 1) * limit);
        setOrders(res);
      }
    } catch (err: any) {
      setError(err.message || "Failed to load canonical transaction records.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchData();
  }, [activeTab, page]);

  const filteredPayments = payments.filter((p) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      p.gateway_payment_id?.toLowerCase().includes(q) ||
      p.order_reference?.toLowerCase().includes(q) ||
      p.payment_method?.toLowerCase().includes(q)
    );
  });

  const filteredOrders = orders.filter((o) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      o.order_reference?.toLowerCase().includes(q) ||
      o.order_number?.toLowerCase().includes(q) ||
      o.customer_reference?.toLowerCase().includes(q)
    );
  });

  return (
    <div className="flex flex-col min-h-screen bg-canvas">
      <Topbar title="Transaction Explorer" breadcrumb="Workspace" />

      <main className="p-6 md:p-8 space-y-6 max-w-7xl mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Canonical Transaction Explorer
            </h1>
            <p className="text-xs text-ink-secondary mt-0.5">
              Granular inspection of normalized line-item transactions across OMS and payment gateways
            </p>
          </div>

          <div className="flex items-center gap-3">
            <Button
              onClick={fetchData}
              variant="outline"
              size="sm"
              disabled={loading}
              className="text-xs font-mono"
            >
              <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
              Refresh
            </Button>
          </div>
        </div>

        {/* Tab Switcher & Search Bar */}
        <div className="border border-border bg-surface p-4 space-y-4">
          <div className="flex flex-col sm:flex-row items-stretch sm:items-center justify-between gap-3">
            <div className="flex items-center gap-1 border border-border bg-canvas p-1">
              <button
                onClick={() => {
                  setActiveTab("PAYMENTS");
                  setPage(1);
                }}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-mono transition-colors ${
                  activeTab === "PAYMENTS"
                    ? "bg-surface text-ink-primary shadow-sm font-semibold"
                    : "text-ink-secondary hover:text-ink-primary"
                }`}
              >
                <CreditCard className="h-3.5 w-3.5" />
                <span>Gateway Payments</span>
              </button>
              <button
                onClick={() => {
                  setActiveTab("ORDERS");
                  setPage(1);
                }}
                className={`flex items-center gap-1.5 px-3 py-1 text-xs font-mono transition-colors ${
                  activeTab === "ORDERS"
                    ? "bg-surface text-ink-primary shadow-sm font-semibold"
                    : "text-ink-secondary hover:text-ink-primary"
                }`}
              >
                <ShoppingBag className="h-3.5 w-3.5" />
                <span>Shopify Orders</span>
              </button>
            </div>

            <div className="relative flex-1 max-w-sm">
              <Search className="h-3.5 w-3.5 text-ink-muted absolute left-3 top-2.5" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder={
                  activeTab === "PAYMENTS"
                    ? "Search payment ID or order ref..."
                    : "Search order ref or customer..."
                }
                className="w-full pl-9 pr-3 py-1.5 border border-border bg-canvas text-xs font-mono text-ink-primary focus:outline-none"
              />
            </div>
          </div>

          {/* Table */}
          <div className="border border-border overflow-x-auto">
            {activeTab === "PAYMENTS" ? (
              <table className="w-full text-xs text-left border-collapse font-mono">
                <thead>
                  <tr className="border-b border-border bg-canvas text-[10px] text-ink-muted uppercase">
                    <th className="py-2.5 px-3">Payment ID</th>
                    <th className="py-2.5 px-3">Order Ref</th>
                    <th className="py-2.5 px-3">Instrument</th>
                    <th className="py-2.5 px-3 text-right">Captured</th>
                    <th className="py-2.5 px-3 text-right">Reported Fee</th>
                    <th className="py-2.5 px-3 text-right">GST</th>
                    <th className="py-2.5 px-3 text-right">Unallocated Balance</th>
                    <th className="py-2.5 px-3">Captured At</th>
                    <th className="py-2.5 px-3 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {loading ? (
                    <tr>
                      <td colSpan={9} className="py-8 text-center text-ink-muted">
                        Loading gateway payments...
                      </td>
                    </tr>
                  ) : filteredPayments.length === 0 ? (
                    <tr>
                      <td colSpan={9} className="py-8 text-center text-ink-muted">
                        No canonical payment records found. Ingest a Razorpay CSV batch to explore.
                      </td>
                    </tr>
                  ) : (
                    filteredPayments.map((p) => (
                      <tr key={p.id} className="hover:bg-hover transition-colors">
                        <td className="py-2 px-3 font-semibold text-ink-primary">
                          {p.gateway_payment_id}
                        </td>
                        <td className="py-2 px-3 text-ink-secondary">{p.order_reference || "—"}</td>
                        <td className="py-2 px-3 text-ink-secondary">{p.payment_method || "UPI"}</td>
                        <td className="py-2 px-3 text-right font-medium text-ink-primary">
                          {formatINR(p.captured_amount)}
                        </td>
                        <td className="py-2 px-3 text-right text-ink-secondary">
                          {formatINR(p.reported_fee)}
                        </td>
                        <td className="py-2 px-3 text-right text-ink-secondary">
                          {formatINR(p.reported_tax)}
                        </td>
                        <td className="py-2 px-3 text-right font-semibold">
                          <span
                            className={
                              Number(p.unallocated_balance) > 0
                                ? "text-status-pending-text"
                                : "text-status-matched-text"
                            }
                          >
                            {formatINR(p.unallocated_balance)}
                          </span>
                        </td>
                        <td className="py-2 px-3 text-ink-muted text-[11px]">
                          {formatDateTime(p.captured_at)}
                        </td>
                        <td className="py-2 px-3 text-center">
                          <button
                            onClick={() => setSelectedTx(p)}
                            className="text-[11px] font-mono text-ink-primary hover:underline"
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            ) : (
              <table className="w-full text-xs text-left border-collapse font-mono">
                <thead>
                  <tr className="border-b border-border bg-canvas text-[10px] text-ink-muted uppercase">
                    <th className="py-2.5 px-3">Order Ref</th>
                    <th className="py-2.5 px-3">Order #</th>
                    <th className="py-2.5 px-3">Customer</th>
                    <th className="py-2.5 px-3 text-right">Gross Amount</th>
                    <th className="py-2.5 px-3 text-right">Discount</th>
                    <th className="py-2.5 px-3 text-right">Tax</th>
                    <th className="py-2.5 px-3">Order Date</th>
                    <th className="py-2.5 px-3 text-center">Action</th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {loading ? (
                    <tr>
                      <td colSpan={8} className="py-8 text-center text-ink-muted">
                        Loading Shopify orders...
                      </td>
                    </tr>
                  ) : filteredOrders.length === 0 ? (
                    <tr>
                      <td colSpan={8} className="py-8 text-center text-ink-muted">
                        No canonical orders found. Ingest a Shopify CSV batch to explore.
                      </td>
                    </tr>
                  ) : (
                    filteredOrders.map((o) => (
                      <tr key={o.id} className="hover:bg-hover transition-colors">
                        <td className="py-2 px-3 font-semibold text-ink-primary">
                          {o.order_reference}
                        </td>
                        <td className="py-2 px-3 text-ink-secondary">{o.order_number || "—"}</td>
                        <td className="py-2 px-3 text-ink-secondary truncate max-w-xs">
                          {o.customer_reference || "—"}
                        </td>
                        <td className="py-2 px-3 text-right font-medium text-ink-primary">
                          {formatINR(o.gross_amount)}
                        </td>
                        <td className="py-2 px-3 text-right text-ink-secondary">
                          {formatINR(o.discount_amount)}
                        </td>
                        <td className="py-2 px-3 text-right text-ink-secondary">
                          {formatINR(o.tax_amount)}
                        </td>
                        <td className="py-2 px-3 text-ink-muted text-[11px]">
                          {formatDateTime(o.order_timestamp)}
                        </td>
                        <td className="py-2 px-3 text-center">
                          <button
                            onClick={() => setSelectedTx(o)}
                            className="text-[11px] font-mono text-ink-primary hover:underline"
                          >
                            Inspect
                          </button>
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            )}
          </div>

          {/* Pagination Controls */}
          <div className="flex items-center justify-between text-xs font-mono pt-2">
            <span className="text-ink-muted">Page {page}</span>
            <div className="flex items-center gap-2">
              <Button
                onClick={() => setPage(Math.max(1, page - 1))}
                disabled={page <= 1 || loading}
                variant="outline"
                size="sm"
                className="h-7 px-2"
              >
                <ChevronLeft className="h-3.5 w-3.5 mr-1" /> Prev
              </Button>
              <Button
                onClick={() => setPage(page + 1)}
                disabled={
                  (activeTab === "PAYMENTS" ? payments.length : orders.length) < limit || loading
                }
                variant="outline"
                size="sm"
                className="h-7 px-2"
              >
                Next <ChevronRight className="h-3.5 w-3.5 ml-1" />
              </Button>
            </div>
          </div>
        </div>
      </main>

      {/* Transaction Inspection Drawer */}
      {selectedTx && (
        <div className="fixed inset-0 z-50 bg-black/40 backdrop-blur-sm flex justify-end">
          <div className="w-full max-w-md bg-surface border-l border-border h-full p-6 overflow-y-auto space-y-6">
            <div className="flex items-center justify-between border-b border-border pb-3">
              <div>
                <span className="text-[10px] font-mono uppercase text-ink-muted">
                  RECORD DETAILS
                </span>
                <h3 className="text-base font-semibold text-ink-primary font-mono">
                  {selectedTx.gateway_payment_id || selectedTx.order_reference}
                </h3>
              </div>
              <button
                onClick={() => setSelectedTx(null)}
                className="p-1 hover:bg-hover border border-border"
              >
                <X className="h-4 w-4 text-ink-secondary" />
              </button>
            </div>

            <div className="space-y-4 text-xs font-mono">
              <div className="p-3 border border-border bg-canvas space-y-2">
                {Object.entries(selectedTx)
                  .filter(([k]) => k !== "raw_source_data")
                  .map(([key, value]) => (
                    <div key={key} className="flex justify-between border-b border-border pb-1">
                      <span className="text-ink-muted text-[11px]">{key}:</span>
                      <span className="text-ink-primary text-right max-w-xs break-all">
                        {String(value ?? "—")}
                      </span>
                    </div>
                  ))}
              </div>

              <Button
                onClick={() => setSelectedTx(null)}
                variant="outline"
                size="sm"
                className="w-full text-xs font-mono"
              >
                Close Record
              </Button>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}
