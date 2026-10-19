"use client";


import Link from "next/link";
import { useParams } from "next/navigation";
import { useApiQuery } from "../../../src/api/useApi";
import { readCapsule } from "../../../src/api/readers";
import { asRecord, pickArray, pickStr, str } from "../../../src/api/domain";
import { AsyncSection } from "../../../components/ui/StateView";
import { CapsuleStatusBadge, Tile, formatTimestamp } from "../../../components/ui/Cards";

export default function CapsuleDetailPage() {
  const params = useParams<{ id: string }>();
  const capsuleId = typeof params.id === "string" ? params.id : "";
  const query = useApiQuery(["capsule", capsuleId], `/api/v1/capsules/${encodeURIComponent(capsuleId)}`, undefined, capsuleId.length > 0);
  const capsule = query.data ? readCapsule(query.data) : null;
  const provenance = query.data ? asRecord(asRecord(query.data)?.provenance) : null;
  const evidenceRefs = provenance ? pickArray(provenance, "evidence") : [];
  const llmTraces = provenance ? pickArray(provenance, "llm_traces") : [];
  const patches = query.data ? pickArray(query.data, "patches") : [];

  return (
    <div className="stack">
      <section className="panel">
        <p className="eyebrow">CAPSULE</p>
        <div className="spread">
          <div>
            <h1 className="mono">{capsule?.id ?? capsuleId}</h1>
            <p className="muted small mono" style={{ margin: 0 }}>
              {capsule?.format ?? "格式未知"} · {capsule?.repo ?? "仓库未知"} · {capsule?.commit?.slice(0, 12) ?? "commit 未知"}
            </p>
          </div>
          {capsule ? <CapsuleStatusBadge status={capsule.status} /> : null}
        </div>

        <AsyncSection
          loading={query.isLoading}
          error={query.error}
          empty={query.data !== undefined && !capsule ? { title: "无法解析胶囊 manifest", reason: "响应缺少 id/status 等字段，读取器拒绝渲染。", next: null } : null}
        >
          <div className="grid-4" style={{ marginTop: 16 }}>
            <Tile label="评分 total" value={capsule?.scoreTotal ?? "—"} tone={capsule?.status === "unknown" || !capsule ? "neutral" : capsule.status} />
            <Tile label="补丁数" value={capsule?.patchCount ?? "—"} />
            <Tile label="SBOM digest" value={<span className="mono" style={{ fontSize: 12 }}>{capsule?.sbomDigest ?? "—"}</span>} />
            <Tile label="创建时间" value={<span style={{ fontSize: 13 }}>{formatTimestamp(capsule?.createdAt ?? null)}</span>} />
          </div>
        </AsyncSection>

        <div className="row" style={{ marginTop: 12 }}>
          <a className="btn btn-primary" href={`/api/v1/capsules/${encodeURIComponent(capsuleId)}/download`}>
            下载 .revive
          </a>
          <span className="muted small">下载走 API 的 presigned 302；前端不拼接签名 URL。</span>
        </div>
      </section>

      <section className="panel">
        <h2>Manifest 结构</h2>
        {query.isLoading ? (
          <p className="muted small">正在读取…</p>
        ) : query.data === undefined ? (
          <p className="muted small">未取得 manifest。</p>
        ) : (
          <table>
            <thead>
              <tr>
                <th>字段</th>
                <th>值</th>
              </tr>
            </thead>
            <tbody>
              <tr>
                <td className="mono small">format</td>
                <td className="mono small">{capsule?.format ?? "—"}</td>
              </tr>
              <tr>
                <td className="mono small">source.repo</td>
                <td className="mono small">{capsule?.repo ?? "—"}</td>
              </tr>
              <tr>
                <td className="mono small">source.commit</td>
                <td className="mono small">{capsule?.commit ?? "—"}</td>
              </tr>
              <tr>
                <td className="mono small">genome_ref</td>
                <td className="mono small">{pickStr(query.data, "genome_ref") ?? "—"}</td>
              </tr>
              <tr>
                <td className="mono small">behavior.compatibility</td>
                <td className="mono small">{pickStr(query.data, "behavior.compatibility") ?? "—"}</td>
              </tr>
              <tr>
                <td className="mono small">sbom_digest</td>
                <td className="mono small">{capsule?.sbomDigest ?? "—"}</td>
              </tr>
              <tr>
                <td className="mono small">patches</td>
                <td className="mono small">{patches.length > 0 ? patches.map((patch) => String(str(patch) ?? JSON.stringify(patch))).join(", ") : "—"}</td>
              </tr>
            </tbody>
          </table>
        )}
      </section>

      <section className="panel">
        <h2>Provenance</h2>
        {provenance === null ? (
          <p className="muted small">API 未返回 provenance 字段。</p>
        ) : (
          <div className="grid-2">
            <div>
              <h3>证据引用（哪个证据支撑哪个版本决策）</h3>
              {evidenceRefs.length === 0 ? (
                <p className="muted small">没有证据引用。</p>
              ) : (
                <ul className="list" style={{ listStyle: "none", padding: 0 }}>
                  {evidenceRefs.map((entry, index) => (
                    <li key={index} className="list-item mono small">
                      {String(str(entry) ?? JSON.stringify(entry))}
                    </li>
                  ))}
                </ul>
              )}
            </div>
            <div>
              <h3>LLM 轨迹</h3>
              {llmTraces.length === 0 ? (
                <p className="muted small">没有 LLM 轨迹记录。</p>
              ) : (
                <ul className="list" style={{ listStyle: "none", padding: 0 }}>
                  {llmTraces.map((entry, index) => (
                    <li key={index} className="list-item mono small">
                      {String(str(entry) ?? JSON.stringify(entry))}
                    </li>
                  ))}
                </ul>
              )}
            </div>
          </div>
        )}
        <p className="muted small">
          胶囊 manifest 来自 schemas/revive-manifest.schema.json 契约；控制台不解析 .revive 压缩包内容。
        </p>
      </section>

      <section className="panel">
        <Link className="btn btn-ghost" href="/capsules">
          返回胶囊列表
        </Link>
      </section>
    </div>
  );
}
