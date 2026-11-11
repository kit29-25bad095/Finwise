import React from "react";
import Image from "next/image";
import { cn } from "@/lib/utils";

interface LogoProps {
  className?: string;
  size?: number;
}

export function Logo({ className, size = 22 }: LogoProps) {
  return (
    <div
      className={cn("relative flex items-center justify-center shrink-0", className)}
      style={{ width: size, height: size }}
    >
      <Image
        src="/logo.png"
        alt="Finora"
        width={size}
        height={size}
        className="object-contain"
        priority
      />
    </div>
  );
}
