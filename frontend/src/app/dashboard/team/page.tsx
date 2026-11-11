"use client";

import React, { useState } from "react";
import { Topbar } from "@/components/shell/Topbar";
import { Badge } from "@/components/ui/Badge";
import { Button } from "@/components/ui/Button";
import { Users, UserPlus, Shield } from "lucide-react";

export default function TeamPage() {
  const [members, setMembers] = useState([
    { id: "1", name: "Ananya Sharma", email: "ananya@finora.internal", role: "ADMIN", status: "ACTIVE", lastActive: "Just now" },
    { id: "2", name: "Vikram Mehta", email: "vikram@finora.internal", role: "FINANCE_MANAGER", status: "ACTIVE", lastActive: "10 mins ago" },
    { id: "3", name: "Rohan Kapoor (Statutory CA)", email: "rohan.ca@auditfirm.in", role: "AUDITOR", status: "ACTIVE", lastActive: "Yesterday" },
  ]);

  return (
    <>
      <Topbar title="Team & Access Control" breadcrumb="Administration" />
      <main className="p-6 space-y-6 max-w-7xl mx-auto w-full">
        <div className="flex justify-between items-center border-b border-border pb-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight text-ink-primary">
              Team & Role-Based Access Control
            </h1>
            <p className="text-xs text-ink-secondary mt-1">
              Multi-tenant role permissions enforcing least privilege across ADMIN, FINANCE_MANAGER, and AUDITOR tiers.
            </p>
          </div>
          <Button variant="primary" size="sm" className="flex items-center gap-1.5">
            <UserPlus className="h-3.5 w-3.5" />
            <span>Invite Team Member</span>
          </Button>
        </div>

        <div className="bg-surface border border-border overflow-x-auto">
          <table className="w-full text-xs text-left border-collapse">
            <thead>
              <tr className="border-b border-border bg-canvas text-[11px] font-mono text-ink-muted uppercase">
                <th className="py-2.5 px-3">Full Name</th>
                <th className="py-2.5 px-3">Email Address</th>
                <th className="py-2.5 px-3">RBAC Role</th>
                <th className="py-2.5 px-3">Last Active</th>
                <th className="py-2.5 px-3 text-center">Status</th>
              </tr>
            </thead>
            <tbody className="divide-y divide-border">
              {members.map((m) => (
                <tr key={m.id} className="hover:bg-hover/60 h-11">
                  <td className="py-2 px-3 font-medium text-ink-primary">{m.name}</td>
                  <td className="py-2 px-3 font-mono text-ink-secondary">{m.email}</td>
                  <td className="py-2 px-3 font-mono text-xs">
                    <span className="px-2 py-0.5 border border-border bg-canvas text-ink-primary">
                      {m.role}
                    </span>
                  </td>
                  <td className="py-2 px-3 text-ink-muted font-mono text-[11px]">{m.lastActive}</td>
                  <td className="py-2 px-3 text-center">
                    <Badge variant="matched">{m.status}</Badge>
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
