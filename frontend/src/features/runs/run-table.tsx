"use client";

import Link from "next/link";
import type { Schema } from "@/shared/api/client";
import { dateTime, modeNames, number, sourceNames } from "@/shared/lib/format";
import { Empty, State } from "@/shared/ui/feedback";

export function RunTable({ items }: { items: Schema["RequestInfo"][] }) {
  if (!items.length)
    return (
      <Empty title="아직 수집 요청이 없어요">
        키워드를 등록하고 미리보기나 수집을 실행해 보세요.
      </Empty>
    );
  return (
    <div className="table-wrap">
      <table>
        <thead>
          <tr>
            <th scope="col">검색 조건</th>
            <th scope="col">채널 / 유형</th>
            <th scope="col">상태</th>
            <th scope="col">확보 건수</th>
            <th scope="col">요청 시각</th>
          </tr>
        </thead>
        <tbody>
          {items.map((run) => (
            <tr key={run.id}>
              <td>
                <Link href={`/runs/${run.id}`} className="table-title">
                  {run.definition.name}
                </Link>
                <div className="table-sub">
                  {run.start_date} ~ {run.end_date}
                </div>
              </td>
              <td className="nowrap">
                {sourceNames[run.source]}
                <div className="table-sub">{modeNames[run.mode]}</div>
              </td>
              <td>
                <State value={run.status} />
                {run.reviewed_at && <div className="table-sub">확인 완료</div>}
              </td>
              <td className="mono-value">
                {number(run.summary.retrieved_count as number | undefined)}
              </td>
              <td className="nowrap">
                <time dateTime={run.created_at}>
                  {dateTime(run.created_at)}
                </time>
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
