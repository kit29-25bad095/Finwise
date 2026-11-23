"use client";

import React, { useState, useEffect } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { formatDateTime } from "@/lib/utils";
import { ApiClient, AuditLogItem, AuditLogsResponse } from "@/lib/api";
import { ScrollText, Shield, RefreshCw, Search, ChevronLeft, ChevronRight } from "lucide-react";

export default function AuditLogsPage() {
  const [data, setData] = useState<AuditLogsResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);
  const [search, setSearch] = useState("");
  const [page, setPage] = useState(1);
  const limit = 25;

  const fetchAuditLogs = async () => {
    try {
      setLoading(true);
      setError(null);
      const res = await ApiClient.getAuditLogs(limit, (page - 1) * limit);
      setData(res);
    } catch (err: any) {
      setError(err.message || "Failed to load audit logs.");
    } finally {
      setLoading(false);
    }
  };

  useEffect(() => {
    fetchAuditLogs();
  }, [page]);

  const filteredLogs = (data?.logs || []).filter((l) => {
    if (!search) return true;
    const q = search.toLowerCase();
    return (
      l.action.toLowerCase().includes(q) ||
      l.target_entity_type.toLowerCase().includes(q) ||
      (l.user_email && l.user_email.toLowerCase().includes(q)) ||
      (l.user_rationale && l.user_rationale.toLowerCase().includes(q))
    );
  });

  return (
    <div className="flex flex-col min-h-screen bg-canvas">
      <Topbar title="Immutable Audit Ledger" breadcrumb="Governance" />

      <main className="p-6 md:p-8 space-y-6 max-w-7xl mx-auto w-full">
        {/* Header */}
        <div className="flex flex-col md:flex-row md:items-center justify-between gap-4 border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Immutable Audit Trail
            </h1>
            <p className="text-xs text-ink-secondary mt-0.5">
              Append-only audit logs recording every financial mutation, review approval, and tariff modification
            </p>
          </div>

          <Button
            onClick={fetchAuditLogs}
            variant="outline"
            size="sm"
            disabled={loading}
            className="text-xs font-mono"
          >
            <RefreshCw className={`h-3.5 w-3.5 mr-1.5 ${loading ? "animate-spin" : ""}`} />
            Refresh Trail
          </Button>
        </div>

        {/* Audit Search Bar */}
        <div className="border border-border bg-surface p-4 space-y-4">
          <div className="flex items-center justify-between">
            <div className="relative flex-1 max-w-sm">
              <Search className="h-3.5 w-3.5 text-ink-muted absolute left-3 top-2.5" />
              <input
                type="text"
                value={search}
                onChange={(e) => setSearch(e.target.value)}
                placeholder="Search action, user, or entity..."
                className="w-full pl-9 pr-3 py-1.5 border border-border bg-canvas text-xs font-mono text-ink-primary focus:outline-none"
              />
            </div>

            <span className="text-xs font-mono text-ink-muted">
              Total Logged Events: {data?.total_logs || 0}
            </span>
          </div>

          {/* Audit Logs Table */}
          <div className="border border-border overflow-x-auto">
            <table className="w-full text-xs text-left border-collapse font-mono">
              <thead>
                <tr className="border-b border-border bg-canvas text-[10px] text-ink-muted uppercase">
                  <th className="py-2.5 px-3">Event Action</th>
                  <th className="py-2.5 px-3">Target Entity</th>
                  <th className="py-2.5 px-3">Performed By</th>
                  <th className="py-2.5 px-3">IP Address</th>
                  <th className="py-2.5 px-3">User Rationale</th>
                  <th className="py-2.5 px-3">Timestamp</th>
                </tr>
              </thead>
              <tbody className="divide-y divide-border">
                {loading ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-ink-muted">
                      Querying immutable audit ledger...
                    </td>
                  </tr>
                ) : filteredLogs.length === 0 ? (
                  <tr>
                    <td colSpan={6} className="py-8 text-center text-ink-muted">
                      No audit events recorded matching current query.
                    </td>
                  </tr>
                ) : (
                  filteredLogs.map((log) => (
                    <tr key={log.id} className="hover:bg-hover transition-colors">
                      <td className="py-2 px-3 font-semibold text-ink-primary">
                        <Badge variant="matched">{log.action}</Badge>
                      </td>
                      <td className="py-2 px-3 text-ink-secondary">
                        {log.target_entity_type}
                        {log.target_entity_id && (
                          <span className="text-[10px] text-ink-muted block truncate max-w-xs">
                            {log.target_entity_id}
                          </span>
                        )}
                      </td>
                      <td className="py-2 px-3 text-ink-primary">
                        {log.user_email || "System Service"}
                      </td>
                      <td className="py-2 px-3 text-ink-muted">{log.ip_address || "127.0.0.1"}</td>
                      <td className="py-2 px-3 text-ink-secondary max-w-sm truncate font-sans">
                        {log.user_rationale || "Automated deterministic pipeline execution"}
                      </td>
                      <td className="py-2 px-3 text-ink-muted text-[11px]">
                        {formatDateTime(log.performed_at)}
                      </td>
                    </tr>
                  ))
                )}
              </tbody>
            </table>
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
                disabled={(data?.logs || []).length < limit || loading}
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
    </div>
  );
}
