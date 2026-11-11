"use client";

import React from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { ScrollText, Shield } from "lucide-react";

export default function AuditLogsPage() {
  const auditEntries = [
    {
      id: "LOG-98201",
      action: "EXCEPTION_APPROVED",
      entity: "leakage_exceptions",
      entityId: "EXC-2026-001",
      user: "vikram@finora.internal",
      ipAddress: "192.168.1.104",
      rationale: "Approved recovery claim after verifying Schedule B contract fee mismatch of ₹36.00.",
      timestamp: "12 Nov 2026, 02:40:12 IST",
    },
    {
      id: "LOG-98200",
      action: "RECONCILIATION_RUN_EXECUTED",
      entity: "reconciliation_runs",
      entityId: "RUN-2026-11-12-01",
      user: "system.scheduler@finora.internal",
      ipAddress: "127.0.0.1",
      rationale: "Automated daily 3-way reconciliation pipeline triggered via Redis RQ queue.",
      timestamp: "12 Nov 2026, 02:30:00 IST",
    },
    {
      id: "LOG-98199",
      action: "RAW_FILE_INGESTED",
      entity: "raw_files",
      entityId: "FILE-2026-0012",
      user: "vikram@finora.internal",
      ipAddress: "192.168.1.104",
      rationale: "Imported HDFC Bank Statement CSV (420 rows, SHA-256 verified).",
      timestamp: "12 Nov 2026, 02:00:15 IST",
    },
    {
      id: "LOG-98198",
      action: "USER_LOGIN_SUCCESS",
      entity: "users",
      entityId: "usr-001",
      user: "vikram@finora.internal",
      ipAddress: "192.168.1.104",
      rationale: "JWT access token issued with FINANCE_MANAGER role.",
      timestamp: "12 Nov 2026, 01:58:30 IST",
    },
  ];

  return (
    <>
      <Topbar title="Immutable Audit Ledger" breadcrumb="Administration" />
      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        <div className="border-b border-border pb-4">
          <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
            Immutable Audit Trail
          </h1>
          <p className="text-xs text-ink-secondary mt-1">
            Cryptographically sealed, append-only ledger tracking all financial sign-offs, entity state mutations, and operator rationales.
          </p>
        </div>

        <div className="bg-surface border border-border overflow-x-auto">
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-border bg-canvas text-[11px] font-mono text-ink-muted uppercase">
                <th className="py-2.5 px-3">Log ID</th>
                <th className="py-2.5 px-3">Action</th>
                <th className="py-2.5 px-3">Entity Reference</th>
                <th className="py-2.5 px-3">Operator</th>
                <th className="py-2.5 px-3">IP Address</th>
                <th className="py-2.5 px-3">Formal Justification</th>
                <th className="py-2.5 px-3 text-right">Timestamp</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border font-mono text-[11px]">
              {auditEntries.map((log) => (
                <tr key={log.id} className="hover:bg-hover/60 h-11">
                  <td className="py-2 px-3 text-ink-primary font-medium">{log.id}</td>
                  <td className="py-2 px-3">
                    <span className="px-1.5 py-0.5 border border-border bg-canvas text-ink-primary">
                      {log.action}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-ink-secondary">
                    {log.entity} / {log.entityId}
                  </td>
                  <td className="py-2 px-3 text-ink-primary font-sans text-xs">{log.user}</td>
                  <td className="py-2 px-3 text-ink-muted">{log.ipAddress}</td>
                  <td className="py-2 px-3 text-ink-secondary font-sans text-xs max-w-xs truncate" title={log.rationale}>
                    {log.rationale}
                  </td>
                  <td className="py-2 px-3 text-ink-muted text-right whitespace-nowrap">{log.timestamp}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      </main>
    </>
  );
}
