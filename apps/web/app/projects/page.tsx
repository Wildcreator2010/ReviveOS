"use client";

import Link from "next/link";
import { useQuery } from "@tanstack/react-query";
import { useState } from "react";
import { apiGet } from "../../src/api/client";
import { nextCursorOf, readProjects } from "../../src/api/readers";
import { describeApiError } from "../../src/api/useApi";
import { AsyncSection } from "../../components/ui/StateView";
import { ProjectCard } from "../../components/ui/Cards";

export default function ProjectsPage() {
  const [cursor, setCursor] = useState<string | null>(null);
  const query = useQuery({
    queryKey: ["projects", cursor],
    queryFn: () => apiGet<unknown>("/api/v1/projects", { query: { limit: 20, cursor: cursor ?? undefined } }),
  });
  const items = query.data ? readProjects(query.data) : [];
  const nextCursor = query.data ? nextCursorOf(query.data) : null;

  return (
    <div className="stack">
      <section className="panel">
        <div className="panel-head">
          <div>
            <p className="eyebrow">PROJECTS</p>
            <h1>项目</h1>
            <p className="muted small" style={{ margin: 0 }}>
              游标分页由后端负责：本页只透传 limit / cursor，不在前端过滤或改序。
            </p>
          </div>
          <div className="row">
            <button type="button" className="btn btn-ghost" onClick={() => void query.refetch()} disabled={query.isFetching}>
              {query.isFetching ? "刷新中…" : "刷新"}
            </button>
            <Link className="btn btn-primary" href="/">
              提交新项目
            </Link>
          </div>
        </div>

        <AsyncSection
          loading={query.isPending}
          error={query.error ? describeApiError(query.error) : null}
          empty={
            query.data && items.length === 0
              ? {
                  title: "还没有项目",
                  reason: "控制面返回空列表。粘贴一个 github.com 仓库地址即可开始第一次复生。",
                  next: (
                    <Link className="btn" href="/">
                      去提交
                    </Link>
                  ),
                }
              : null
          }
        >
          <div className="list">
            {items.map((project) => (
              <ProjectCard key={project.id} project={project} />
            ))}
          </div>
          <div className="row" style={{ marginTop: 16 }}>
            <button type="button" className="btn btn-ghost" disabled={cursor === null} onClick={() => setCursor(null)}>
              回到首页
            </button>
            <button type="button" className="btn" disabled={nextCursor === null} onClick={() => setCursor(nextCursor)}>
              {nextCursor === null ? "没有更多" : "下一页"}
            </button>
            {cursor ? <span className="muted small mono">cursor {cursor}</span> : null}
          </div>
        </AsyncSection>
      </section>
    </div>
  );
}
