"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";
import type { ReactNode } from "react";

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
      <header className="app-header">
        <span className="brand">
          ReviveOS<span>Software ICU</span>
        </span>
        <span className="header-spacer" />
        {headerStatus}
      </header>
      <div className="shell">
        <aside className="sidebar">
          <div className="sidebar-label">WORKSPACE</div>
          <nav aria-label="主导航">
            {NAV_ITEMS.map((item) => (
              <Link key={item.href} href={item.href} aria-current={isActive(pathname, item.href) ? "page" : undefined}>
                <span className="nav-marker">{item.marker}</span>
                <span>{item.label}</span>
                {isActive(pathname, item.href) ? <span className="nav-current" aria-hidden="true">●</span> : null}
              </Link>
            ))}
          </nav>
          <div className="sidebar-foot">
            <span className="sidebar-pulse" aria-hidden="true" />
            <span>复生控制台</span>
            <span className="mono small">v1</span>
          </div>
        </aside>
        <main>{children}</main>
      </div>
    </>
  );
}
