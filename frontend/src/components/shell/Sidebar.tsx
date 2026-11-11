"use client";

import React, { useState } from "react";
import Link from "next/link";
import { usePathname, useRouter } from "next/navigation";
import {
  LayoutDashboard,
  GitCompare,
  ArrowLeftRight,
  Landmark,
  AlertOctagon,
  Radar,
  Sparkles,
  FileSpreadsheet,
  Database,
  FileClock,
  FileCheck2,
  FileText,
  Users,
  ScrollText,
  Sliders,
  LogOut,
  ChevronDown,
  Circle,
  Building2,
} from "lucide-react";
import { cn } from "@/lib/utils";
import { ApiClient, User, TenantMembership } from "@/lib/api";

interface SidebarProps {
  user: User | null;
  memberships: TenantMembership[];
  activeTenantId: string | null;
  onSelectTenant: (tenantId: string) => void;
}

export function Sidebar({
  user,
  memberships,
  activeTenantId,
  onSelectTenant,
}: SidebarProps) {
  const pathname = usePathname();
  const router = useRouter();
  const [dropdownOpen, setDropdownOpen] = useState(false);

  const activeTenant = memberships.find((m) => m.tenant_id === activeTenantId)?.tenant;
  const activeRole = memberships.find((m) => m.tenant_id === activeTenantId)?.role || "FINANCE_MANAGER";

  const handleLogout = () => {
    ApiClient.clearSession();
    router.push("/login");
  };

  const navGroups = [
    {
      group: "WORKSPACE",
      items: [
        { name: "Overview", href: "/dashboard", icon: LayoutDashboard },
        { name: "Reconciliation", href: "/dashboard/reconciliation", icon: GitCompare },
        { name: "Transactions", href: "/dashboard/transactions", icon: ArrowLeftRight },
        { name: "Settlements", href: "/dashboard/settlements", icon: Landmark },
      ],
    },
    {
      group: "INVESTIGATION",
      items: [
        { name: "Exceptions", href: "/dashboard/exceptions", icon: AlertOctagon },
        { name: "Leakage Detection", href: "/dashboard/leakage-detection", icon: Radar },
        { name: "AI Investigations", href: "/dashboard/investigations", icon: Sparkles },
        { name: "Dispute Management", href: "/dashboard/disputes", icon: FileSpreadsheet },
      ],
    },
    {
      group: "DATA",
      items: [
        { name: "Data Sources", href: "/dashboard/data-sources", icon: Database },
        { name: "Upload History", href: "/dashboard/upload-history", icon: FileClock },
        { name: "Fee Contracts", href: "/dashboard/contracts", icon: FileCheck2 },
        { name: "Reports", href: "/dashboard/reports", icon: FileText },
      ],
    },
    {
      group: "ADMINISTRATION",
      items: [
        { name: "Team & Access", href: "/dashboard/team", icon: Users },
        { name: "Audit Logs", href: "/dashboard/audit", icon: ScrollText },
        { name: "Settings", href: "/dashboard/settings", icon: Sliders },
      ],
    },
  ];

  return (
    <aside className="w-[220px] bg-surface border-r border-border flex flex-col justify-between shrink-0 select-none h-screen sticky top-0 overflow-y-auto">
      <div className="flex flex-col">
        {/* Top: Finora Wordmark & Minimalist Monogram */}
        <div className="h-14 px-4 border-b border-border flex items-center justify-between">
          <Link href="/dashboard" className="flex items-center gap-2">
            <div className="w-5 h-5 bg-brand-black text-white flex items-center justify-center text-[11px] font-bold tracking-tighter">
              F
            </div>
            <span className="font-semibold text-sm tracking-tight text-ink-primary">
              Finora
            </span>
          </Link>
          <span className="text-[10px] font-mono px-1.5 py-0.5 border border-border text-ink-secondary bg-canvas">
            v1.0
          </span>
        </div>

        {/* Workspace Switcher */}
        <div className="p-3 border-b border-border relative">
          <button
            onClick={() => setDropdownOpen(!dropdownOpen)}
            className="w-full text-left p-2 border border-border bg-canvas hover:bg-hover transition-colors flex items-center justify-between text-xs"
          >
            <div className="flex items-center gap-2 min-w-0">
              <Building2 className="h-3.5 w-3.5 text-ink-secondary shrink-0" strokeWidth={1.5} />
              <div className="truncate">
                <div className="text-[10px] uppercase font-mono text-ink-muted leading-none">
                  WORKSPACE
                </div>
                <div className="font-medium text-xs text-ink-primary truncate mt-0.5">
                  {activeTenant?.name || "Production Enterprise"}
                </div>
              </div>
            </div>
            <ChevronDown className="h-3 w-3 text-ink-muted shrink-0" strokeWidth={1.5} />
          </button>

          {dropdownOpen && (
            <div className="absolute top-full left-3 right-3 mt-1 bg-surface border border-border shadow-sm z-30 py-1">
              {memberships.length > 0 ? (
                memberships.map((m) => (
                  <button
                    key={m.tenant_id}
                    onClick={() => {
                      onSelectTenant(m.tenant_id);
                      setDropdownOpen(false);
                    }}
                    className={cn(
                      "w-full text-left px-3 py-1.5 text-xs flex items-center justify-between hover:bg-hover transition-colors",
                      m.tenant_id === activeTenantId && "font-semibold bg-canvas text-ink-primary"
                    )}
                  >
                    <span className="truncate">{m.tenant?.name || m.tenant_id.substring(0, 10)}</span>
                    <span className="text-[10px] font-mono text-ink-muted">{m.role}</span>
                  </button>
                ))
              ) : (
                <div className="px-3 py-2 text-xs text-ink-muted">
                  Default Organization
                </div>
              )}
            </div>
          )}
        </div>

        {/* Navigation Sections */}
        <nav className="p-2 space-y-4">
          {navGroups.map((group) => (
            <div key={group.group}>
              <div className="px-2.5 mb-1 text-[10px] font-semibold uppercase tracking-wider text-ink-muted font-mono">
                {group.group}
              </div>
              <div className="space-y-0.5">
                {group.items.map((item) => {
                  const Icon = item.icon;
                  const isActive = pathname === item.href;
                  return (
                    <Link
                      key={item.name}
                      href={item.href}
                      className={cn(
                        "flex items-center gap-2.5 px-2.5 py-1.5 text-xs font-normal transition-colors rounded-none border border-transparent",
                        isActive
                          ? "bg-hover text-ink-primary font-medium border-border"
                          : "text-ink-secondary hover:text-ink-primary hover:bg-hover/60"
                      )}
                    >
                      <Icon className="h-4 w-4 shrink-0" strokeWidth={1.5} />
                      <span className="truncate">{item.name}</span>
                    </Link>
                  );
                })}
              </div>
            </div>
          ))}
        </nav>
      </div>

      {/* Bottom: Integration & Auth Status */}
      <div className="border-t border-border p-3 space-y-3 bg-canvas/40">
        {/* Source Connection Status (Truthful verification: never fake live status) */}
        <div className="border border-border bg-surface p-2.5 space-y-2">
          <div className="text-[10px] font-semibold uppercase tracking-wider text-ink-muted font-mono">
            DATA INGESTION STATUS
          </div>
          <div className="space-y-1.5 text-[11px] font-mono">
            <div className="flex items-center justify-between text-ink-secondary">
              <span className="flex items-center gap-1.5">
                <Circle className="h-1.5 w-1.5 fill-zinc-300 text-zinc-300" />
                Shopify
              </span>
              <span className="text-[10px] text-ink-muted">NOT CONNECTED</span>
            </div>
            <div className="flex items-center justify-between text-ink-secondary">
              <span className="flex items-center gap-1.5">
                <Circle className="h-1.5 w-1.5 fill-zinc-300 text-zinc-300" />
                Razorpay
              </span>
              <span className="text-[10px] text-ink-muted">NOT CONNECTED</span>
            </div>
            <div className="flex items-center justify-between text-ink-secondary">
              <span className="flex items-center gap-1.5">
                <Circle className="h-1.5 w-1.5 fill-amber-500 text-amber-500" />
                HDFC Bank
              </span>
              <span className="text-[10px] text-[#D97706]">STAGED CSV</span>
            </div>
          </div>
        </div>

        {/* Current User Profile & Logout */}
        <div className="flex items-center justify-between pt-1">
          <div className="min-w-0 pr-2">
            <div className="text-xs font-medium text-ink-primary truncate">
              {user?.full_name || "Finance Manager"}
            </div>
            <div className="text-[10px] font-mono text-ink-muted truncate">
              {activeRole}
            </div>
          </div>
          <button
            onClick={handleLogout}
            title="Sign Out"
            className="p-1.5 text-ink-secondary hover:text-ink-primary hover:bg-hover border border-transparent hover:border-border transition-colors"
          >
            <LogOut className="h-3.5 w-3.5" strokeWidth={1.5} />
          </button>
        </div>
      </div>
    </aside>
  );
}
