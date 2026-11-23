"use client";

import React, { useState, useEffect } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatINR } from "@/lib/utils";
import { ApiClient, FeeAnalyticsResponse } from "@/lib/api";
import { FileCheck2, Plus, Shield, RefreshCw, AlertTriangle, CheckCircle2 } from "lucide-react";

export default function ContractsPage() {
  const [data, setData] = useState<FeeAnalyticsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const fetchFeeAnalytics = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ApiClient.getFeeAnalytics();
      setData(res);
    } catch (err: any) {
      setError(err.message || "Failed to load fee contract analytics.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchFeeAnalytics();
  }, []);

  const contract = data?.active_contract;
  const gstPercentage = data
    ? (Number(data.gst_rate) * 100).toFixed(2) + "%"
    : "18.00%";

  return (
    <div className="flex flex-col min-h-screen bg-canvas">
      <Topbar title="Fee & Contract Analytics" breadcrumb="Financial Intelligence" />

      <main className="p-6 md:p-8 space-y-8 max-w-7xl mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Contractual Fee & Tariff Analytics
            </h1>
            <p className="text-xs text-ink-secondary mt-0.5">
              Deterministic comparison of gateway deductions against versioned contractual tariffs
            </p>
          </div>

          <Button
            onClick={fetchFeeAnalytics}
            variant="outline"
            size="sm"
            disabled={loading}
            className="text-xs font-mono"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
            Refresh Tariffs
          </Button>
        </div>

        {/* Contract Metadata Banner */}
        <div className="border border-border bg-surface p-6 space-y-6">
          <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
            <div className="flex items-center gap-3">
              <div className="p-2 border border-border bg-canvas">
                <FileCheck2 className="h-5 w-5 text-ink-primary" />
              </div>
              <div>
                <div className="flex items-center gap-2">
                  <h2 className="text-sm font-semibold text-ink-primary">
                    {contract?.contract_name || "Standard Enterprise Gateway Tariff"}
                  </h2>
                  <Badge variant="matched">
                    ACTIVE VERSION: {data?.contract_version || 1}
                  </Badge>
                  <span className="text-[10px] font-mono px-1.5 py-0.5 border border-border bg-canvas text-ink-secondary">
                    Gateway: {contract?.gateway_name || "RAZORPAY"}
                  </span>
                </div>
                <p className="text-xs text-ink-secondary mt-0.5">
                  Applicable GST Rate: <strong>{gstPercentage}</strong> • Sub-paisa Tolerance: <strong>₹0.05</strong>
                </p>
              </div>
            </div>

            <div className="flex items-center gap-6 text-xs font-mono">
              <div>
                <span className="text-ink-muted block text-[10px] uppercase">Total Fee Drift</span>
                <span className="font-semibold text-ink-primary text-sm">
                  {formatINR(data?.total_fee_drift || 0)}
                </span>
              </div>
              <div className="h-8 w-px bg-border" />
              <div>
                <span className="text-ink-muted block text-[10px] uppercase">Verified Overcharges</span>
                <span className="font-semibold text-status-leakage-text text-sm">
                  {formatINR(data?.total_fee_overcharges || 0)}
                </span>
              </div>
            </div>
          </div>

          {/* Aggregate Totals */}
          <div className="grid grid-cols-2 md:grid-cols-4 gap-4 text-xs font-mono">
            <div className="p-3 border border-border bg-canvas">
              <span className="text-[10px] text-ink-muted uppercase block">Total Gross Volume</span>
              <div className="text-sm font-semibold text-ink-primary mt-1">
                {formatINR(data?.total_gross_volume || 0)}
              </div>
            </div>
            <div className="p-3 border border-border bg-canvas">
              <span className="text-[10px] text-ink-muted uppercase block">Actual Reported Fees</span>
              <div className="text-sm font-semibold text-ink-primary mt-1">
                {formatINR(data?.total_reported_fees || 0)}
              </div>
            </div>
            <div className="p-3 border border-border bg-canvas">
              <span className="text-[10px] text-ink-muted uppercase block">Contractual Expected Fees</span>
              <div className="text-sm font-semibold text-ink-primary mt-1">
                {formatINR(data?.total_contractual_fees || 0)}
              </div>
            </div>
            <div className="p-3 border border-border bg-canvas">
              <span className="text-[10px] text-ink-muted uppercase block">Discrepancy (Overcharge)</span>
              <div className="text-sm font-semibold text-status-leakage-text mt-1">
                {formatINR(data?.total_fee_overcharges || 0)}
              </div>
            </div>
          </div>
        </div>

        {/* Tier-by-Tier Instrument Table */}
        <div className="border border-border bg-surface p-4 space-y-4">
          <div className="flex items-center justify-between">
            <h2 className="text-xs font-mono uppercase tracking-wider text-ink-muted">
              Payment Instrument Fee Schedule Tiers
            </h2>
            <span className="text-xs text-ink-secondary font-mono">
              Zero universal MDR assumptions
            </span>
          </div>

          <div className="border border-border overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse font-mono">
              <thead>
                <tr className="border-b border-border bg-canvas text-[10px] text-ink-muted uppercase">
                  <th className="py-2.5 px-3">Instrument Category</th>
                  <th className="py-2.5 px-3 text-right">Contracted MDR (%)</th>
                  <th className="py-2.5 px-3 text-right">Fixed Fee</th>
                  <th className="py-2.5 px-3 text-right">Transactions</th>
                  <th className="py-2.5 px-3 text-right">Gross Volume</th>
                  <th className="py-2.5 px-3 text-right">Actual Gateway Fee</th>
                  <th className="py-2.5 px-3 text-right">Expected Fee</th>
                  <th className="py-2.5 px-3 text-right">Variance</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {loading ? (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-ink-muted">
                      Calculating tariff schedule analytics...
                    </td>
                  </tr>
                ) : (data?.tiers || []).length === 0 ? (
                  <tr>
                    <td colSpan={8} className="py-8 text-center text-ink-muted">
                      No payment instrument data evaluated yet.
                    </td>
                  </tr>
                ) : (
                  (data?.tiers || []).map((tier) => {
                    const ratePct = (Number(tier.percentage_rate) * 100).toFixed(2) + "%";
                    const isOvercharge = Number(tier.variance) > 0.05;
                    return (
                      <tr key={tier.instrument_type} className="hover:bg-hover transition-colors">
                        <td className="py-2.5 px-3 font-semibold text-ink-primary">
                          {tier.instrument_type}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-secondary">{ratePct}</td>
                        <td className="py-2.5 px-3 text-right text-ink-secondary">
                          {formatINR(tier.fixed_fee_per_txn)}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-primary">
                          {tier.transactions_evaluated}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-primary font-medium">
                          {formatINR(tier.gross_volume)}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-secondary">
                          {formatINR(tier.actual_gateway_fees)}
                        </td>
                        <td className="py-2.5 px-3 text-right text-ink-secondary">
                          {formatINR(tier.contractual_expected_fees)}
                        </td>
                        <td className="py-2.5 px-3 text-right font-semibold">
                          <span
                            className={
                              isOvercharge
                                ? "text-status-leakage-text"
                                : "text-status-matched-text"
                            }
                          >
                            {Number(tier.variance) > 0 ? "+" : ""}
                            {formatINR(tier.variance)}
                          </span>
                        </td>
                      </tr>
                    );
                  })
                )}
              </tbody>
            </table>
          </div>
        </div>
      </main>
    </div>
  );
}
