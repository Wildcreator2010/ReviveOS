"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

const SECTIONS = [
  { slug: "", label: "总览" },
  { slug: "genome", label: "Genome" },
  { slug: "evidence", label: "证据" },
  { slug: "patches", label: "Patch/Diff" },
  { slug: "behavior", label: "行为" },
  { slug: "report", label: "复生评分" },
  { slug: "capsules", label: "胶囊" },
] as const;

export function ProjectTabs({ projectId }: { projectId: string }) {
  const pathname = usePathname() ?? "";
  const base = `/projects/${encodeURIComponent(projectId)}`;
  return (
    <nav className="tabs" aria-label="项目视图">
      {SECTIONS.map((section) => {
        const href = section.slug.length === 0 ? base : `${base}/${section.slug}`;
        const active = section.slug.length === 0 ? pathname === base : pathname === href;
        return (
          <Link key={section.slug || "overview"} href={href} role="tab" aria-selected={active} style={{ color: active ? "var(--text)" : undefined, borderBottom: active ? "2px solid var(--accent)" : "2px solid transparent", borderRadius: 0 }}>
            {section.label}
          </Link>
        );
      })}
    </nav>
  );
}
