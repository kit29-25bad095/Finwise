import React from "react";
import { cn } from "@/lib/utils";

export type BadgeVariant = "leakage" | "pending" | "matched" | "neutral" | "unverified";

interface BadgeProps {
  children: React.ReactNode;
  variant?: BadgeVariant;
  className?: string;
  size?: "sm" | "md";
}

export function Badge({
  children,
  variant = "neutral",
  className,
  size = "sm",
}: BadgeProps) {
  const variantStyles: Record<BadgeVariant, string> = {
    // Confirmed financial leakage
    leakage: "text-[#DC2626] bg-[#FEF2F2] border-[#FECACA]",
    // Pending settlement
    pending: "text-[#D97706] bg-[#FFFBEB] border-[#FDE68A]",
    // Matched / healthy
    matched: "text-[#52525B] bg-[#F4F4F5] border-[#E4E4E7]",
    // Neutral default
    neutral: "text-[#71717A] bg-[#FFFFFF] border-[#E4E4E7]",
    // Unverified / Disconnected
    unverified: "text-[#71717A] bg-[#F4F4F5] border-[#E4E4E7]",
  };

  const sizeStyles = {
    sm: "px-2 py-0.5 text-[11px] font-medium leading-none",
    md: "px-2.5 py-1 text-xs font-medium",
  };

  return (
    <span
      className={cn(
        "inline-flex items-center gap-1 rounded border tracking-tight transition-colors",
        variantStyles[variant],
        sizeStyles[size],
        className
      )}
    >
      {children}
    </span>
  );
}
