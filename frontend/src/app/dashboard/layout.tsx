"use client";

import { useEffect, useState } from "react";
import { useRouter, usePathname } from "next/navigation";
import Link from "next/link";
import {
  LayoutDashboard,
  UploadCloud,
  GitCompare,
  AlertTriangle,
  FileText,
  History,
  Settings,
  LogOut,
  Building,
  Shield,
  Layers
} from "lucide-react";
import { ApiClient, User, TenantMembership } from "@/lib/api";

export default function DashboardLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  const router = useRouter();
  const pathname = usePathname();
  const [user, setUser] = useState<User | null>(null);
  const [memberships, setMemberships] = useState<TenantMembership[]>([]);
  const [activeTenantId, setActiveTenantId] = useState<string | null>(null);
  const [activeRole, setActiveRole] = useState<string>("FINANCE_MANAGER");

  useEffect(() => {
    const rawUser = localStorage.getItem("finora_user");
    const token = localStorage.getItem("finora_access_token");
    if (!token) {
      router.push("/login");
      return;
    }
    if (rawUser) {
      try {
        setUser(JSON.parse(rawUser));
      } catch {}
    }

    const currentTenant = localStorage.getItem("finora_active_tenant_id");
    const currentRole = localStorage.getItem("finora_active_role");
    setActiveTenantId(currentTenant);
    if (currentRole) setActiveRole(currentRole);

    ApiClient.listTenants()
      .then((mems) => {
        setMemberships(mems);
        if (!currentTenant && mems.length > 0) {
          setActiveTenantId(mems[0].tenant_id);
          setActiveRole(mems[0].role);
          localStorage.setItem("finora_active_tenant_id", mems[0].tenant_id);
          localStorage.setItem("finora_active_role", mems[0].role);
        }
      })
      .catch(() => {});
  }, [router]);

  const handleLogout = () => {
    ApiClient.clearSession();
    router.push("/login");
  };

  const navItems = [
    { name: "Overview", href: "/dashboard", icon: LayoutDashboard },
    { name: "Data Ingestion", href: "/dashboard/ingestion", icon: UploadCloud, badge: "Phase 2" },
    { name: "Reconciliation Runs", href: "/dashboard/reconciliation", icon: GitCompare, badge: "Phase 3" },
    { name: "Exceptions & Leaks", href: "/dashboard/exceptions", icon: AlertTriangle, badge: "Phase 4" },
    { name: "Dispute Claims", href: "/dashboard/disputes", icon: FileText, badge: "Phase 5" },
    { name: "Audit Trail", href: "/dashboard/audit", icon: History, badge: "Phase 6" },
  ];

  return (
    <div className="min-h-screen bg-background flex">
      {/* Sidebar */}
      <aside className="w-64 border-r border-border/50 bg-surface/50 flex flex-col justify-between shrink-0">
        <div>
          {/* Brand Header */}
          <div className="h-16 px-6 border-b border-border/40 flex items-center justify-between">
            <Link href="/" className="flex items-center space-x-2.5">
              <div className="h-7 w-7 rounded-lg bg-primary flex items-center justify-center font-bold text-white text-xs">
                F
              </div>
              <span className="font-semibold text-base tracking-tight text-white">Finora</span>
            </Link>
            <span className="text-[10px] uppercase font-mono px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
              v1.0
            </span>
          </div>

          {/* Tenant Selector */}
          <div className="p-4 border-b border-border/40">
            <div className="text-[11px] font-medium uppercase tracking-wider text-slate-400 mb-1.5 flex items-center justify-between">
              <span className="flex items-center space-x-1">
                <Building className="h-3 w-3" />
                <span>Active Tenant</span>
              </span>
              <span className="text-[10px] px-1.5 py-0.2 rounded bg-sky-950 text-sky-400 border border-sky-800 font-mono">
                {activeRole}
              </span>
            </div>
            <select
              value={activeTenantId || ""}
              onChange={(e) => {
                const newId = e.target.value;
                setActiveTenantId(newId);
                const mem = memberships.find((m) => m.tenant_id === newId);
                if (mem) {
                  setActiveRole(mem.role);
                  localStorage.setItem("finora_active_tenant_id", newId);
                  localStorage.setItem("finora_active_role", mem.role);
                  window.location.reload();
                }
              }}
              className="w-full bg-surfaceLight border border-border text-xs rounded-lg px-2.5 py-2 text-white focus:outline-none focus:border-primary transition"
            >
              {memberships.map((m) => (
                <option key={m.id} value={m.tenant_id}>
                  {m.tenant?.name || m.tenant_id} ({m.role})
                </option>
              ))}
            </select>
          </div>

          {/* Navigation Links */}
          <nav className="p-3 space-y-1">
            {navItems.map((item) => {
              const Icon = item.icon;
              const isActive = pathname === item.href;
              return (
                <Link
                  key={item.name}
                  href={item.href}
                  className={`flex items-center justify-between px-3 py-2 rounded-lg text-xs font-medium transition ${
                    isActive
                      ? "bg-primary text-white shadow-sm"
                      : "text-slate-400 hover:text-white hover:bg-surfaceLight/60"
                  }`}
                >
                  <div className="flex items-center space-x-2.5">
                    <Icon className="h-4 w-4" />
                    <span>{item.name}</span>
                  </div>
                  {item.badge && (
                    <span className="text-[9px] uppercase px-1.5 py-0.5 rounded bg-slate-800 text-slate-400 border border-slate-700">
                      {item.badge}
                    </span>
                  )}
                </Link>
              );
            })}
          </nav>
        </div>

        {/* User Card & Logout */}
        <div className="p-4 border-t border-border/40">
          <div className="flex items-center space-x-3 mb-3">
            <div className="h-8 w-8 rounded-full bg-sky-950 border border-sky-800 flex items-center justify-center font-medium text-sky-300 text-xs">
              {user?.full_name?.charAt(0) || "U"}
            </div>
            <div className="overflow-hidden">
              <div className="text-xs font-medium text-white truncate">{user?.full_name || "User"}</div>
              <div className="text-[11px] text-slate-500 truncate">{user?.email}</div>
            </div>
          </div>

          <button
            onClick={handleLogout}
            className="w-full py-1.5 px-3 rounded-lg bg-surfaceLight hover:bg-slate-800 border border-border text-xs text-slate-400 hover:text-rose-400 flex items-center justify-center space-x-2 transition"
          >
            <LogOut className="h-3.5 w-3.5" />
            <span>Sign Out</span>
          </button>
        </div>
      </aside>

      {/* Main Content Area */}
      <main className="flex-1 flex flex-col min-w-0 overflow-y-auto">
        {children}
      </main>
    </div>
  );
}
