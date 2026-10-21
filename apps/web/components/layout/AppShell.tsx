"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";
import { AuthMenu } from "./AuthMenu";
import { WallpaperBackground } from "../theme/WallpaperBackground";
import { PointerEffects } from "../theme/PointerEffects";

const NAV_ITEMS = [
  { href: "/", label: "总览", marker: "01" },
  { href: "/projects", label: "项目档案", marker: "02" },
  { href: "/jobs", label: "复生任务", marker: "03" },
  { href: "/capsules", label: "记忆胶囊", marker: "04" },
  { href: "/settings", label: "系统设置", marker: "05" },
] as const;

function isActive(pathname: string, href: string): boolean {
  if (href === "/") return pathname === "/";
  return pathname === href || pathname.startsWith(`${href}/`);
}

export function AppShell({ children, headerStatus }: { children: ReactNode; headerStatus: ReactNode }) {
  const pathname = usePathname() ?? "/";
  return (
    <>
      <WallpaperBackground />
      <PointerEffects />
      <header className="app-header">
        <Link className="brand" href="/" aria-label="ReviveOS 总览">
          ReviveOS<span>Software ICU</span>
        </Link>
        <nav className="top-nav" aria-label="主导航">
          {NAV_ITEMS.map((item) => (
            <Link key={item.href} href={item.href} aria-current={isActive(pathname, item.href) ? "page" : undefined}>
              <span className="nav-marker">{item.marker}</span>
              <span>{item.label}</span>
            </Link>
          ))}
        </nav>
        <div className="header-right">
          {headerStatus}
          <AuthMenu />
        </div>
      </header>
      <div className="shell">
        <main>{children}</main>
      </div>
      <footer className="app-footer">
        <span>ReviveOS · Evidence First, AI Second</span>
        <span className="footer-dot" aria-hidden="true">·</span>
        <span>把死掉的软件，重新带回来。</span>
      </footer>
    </>
  );
}
