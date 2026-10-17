import { useState } from 'react'
import { useMutation, useQueryClient, useQuery } from '@tanstack/react-query'
import { Loader2, Wand2, AlertTriangle } from 'lucide-react'
import { api } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { MissingCapChip } from '@/lib/capability-labels'
import { DatePicker } from '@/components/DatePicker'

function pad(n: number) { return String(n).padStart(2, '0') }
function todayStr() {
  const d = new Date()
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}
/** 往前推 N 天 */
function daysAgo(n: number): string {
  const d = new Date()
  d.setDate(d.getDate() - n)
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`
}

// hasCap: 日K批量能力当前是否可用 (路由矩阵判定, 生效源含插件/自定义源)
export function RepairDailyPanel({ hasCap, isRunning, latestDate, onStart }: {
  hasCap: boolean
  isRunning: boolean
  latestDate: string | null
  onStart: () => void
}) {
  const qc = useQueryClient()
  const hasBatchCap = hasCap

  // 默认起始日期: 最新数据往前推 30 天 (兼顾补缺口 + 复核近期数据, 成本不高)
  const [startDate, setStartDate] = useState(daysAgo(30))

  const repair = useMutation({
    mutationFn: () => api.repairDaily(startDate),
    onSuccess: () => {
      onStart()
      qc.invalidateQueries({ queryKey: QK.pipelineJobs })
    },
  })

  // 长窗口稀疏检测: 拿推荐起点
  const rec = useQuery({
    queryKey: QK.klineRepairRecommendation,
    queryFn: api.repairRecommendation,
    staleTime: 60_000,
    enabled: hasBatchCap,
  })

  const applyRecommendation = () => {
    if (rec.data?.recommended_start_date) {
      setStartDate(rec.data.recommended_start_date)
    }
  }

  const today = todayStr()
  const canSubmit = hasBatchCap && !isRunning && !repair.isPending && startDate <= today
  const gapDays = latestDate
    ? Math.max(0, Math.round((Date.parse(today) - Date.parse(latestDate)) / 86400000))
    : null

  const hasRecommendation = !!rec.data?.recommended_start_date
  const isRecommendationApplied = hasRecommendation && rec.data!.recommended_start_date === startDate

  return (
    <div className="space-y-3">
      <div className="rounded-card bg-accent/8 border border-accent/20 p-3 space-y-1.5">
        <div className="text-xs text-foreground">
          当数据出现缺口时(漏跑、停服),从这里重拉选定区间到今天的全部数据并重算。
        </div>
        <div className="text-[10px] text-muted leading-relaxed">
          完整复用盘后管道流程 (A股日K · 除权因子 · 指标重算 · 指数),新数据按 (个股, 日期) 覆盖旧值,不会重复,也无需先清除。
        </div>
      </div>

      {/* 推荐起点 — 自动检测按钮 */}
      <div className="rounded-card border border-accent/15 p-2.5 bg-accent/4">
        <div className="flex items-center justify-between gap-2 mb-1.5">
          <span className="text-[11px] text-secondary font-medium">
            全历史稀疏检测
          </span>
          {rec.isFetching && (
            <span className="text-[10px] text-muted inline-flex items-center gap-1">
              <Loader2 className="h-2.5 w-2.5 animate-spin" />
              扫描中…
            </span>
          )}
        </div>

        {rec.isError && (
          <div className="text-[10px] text-warning leading-relaxed mb-1.5">
            扫描失败: {(rec.error as Error).message}
          </div>
        )}

        {rec.data && (
          <>
            {rec.data.has_issues ? (
              <div className="text-[11px] leading-relaxed mb-2">
                <div className="inline-flex items-center gap-1 text-warning mb-1">
                  <AlertTriangle className="h-3 w-3" />
                  发现 {rec.data.issue_count} 个稀疏/缺失分区
                </div>
                {rec.data.recommended_start_date && (
                  <div className="text-muted">
                    推荐从此日期起全量重拉:{' '}
                    <span className="font-mono text-secondary">
                      {rec.data.recommended_start_date}
                    </span>
                  </div>
                )}
                {rec.data.details.length > 0 && (
                  <div className="text-[10px] text-muted mt-0.5 leading-relaxed">
                    {rec.data.details.join('；')}
                  </div>
                )}
              </div>
            ) : (
              <div className="text-[11px] text-success leading-relaxed mb-2">
                ✅ 全历史分区行数正常, 无需回溯修复
              </div>
            )}
          </>
        )}

        <button
          onClick={applyRecommendation}
          disabled={!hasBatchCap || !hasRecommendation || isRecommendationApplied}
          className="w-full inline-flex items-center justify-center gap-1.5 px-2.5 py-1 rounded-btn text-[11px] font-medium transition-colors duration-150 bg-accent/80 text-white hover:bg-accent disabled:opacity-40 disabled:pointer-events-none"
        >
          <Wand2 className="h-3 w-3" />
          {isRecommendationApplied
            ? '已应用推荐起点'
            : hasRecommendation
              ? `应用推荐起点 (${rec.data!.recommended_start_date})`
              : rec.isFetching
                ? '扫描中…'
                : rec.data?.has_issues
                  ? '无可用推荐'
                  : '全历史正常, 无需回溯'}
        </button>
      </div>

      {/* 起始日期 — 用户主要操作,放上面 */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-secondary">起始日期</span>
        <DatePicker
          value={startDate}
          onChange={setStartDate}
          max={today}
          align="right"
          buttonClassName="font-mono text-xs"
        />
      </div>

      {/* 本地最新数据 — 参考信息,放下面 */}
      <div className="flex items-center justify-between gap-2">
        <span className="text-xs text-muted">本地最新数据</span>
        <span className="font-mono text-xs text-secondary">
          {latestDate ?? '—'}
          {gapDays !== null && gapDays > 0 && (
            <span className="ml-2 text-warning/90">已落后 {gapDays} 天</span>
          )}
        </span>
      </div>

      <div className="text-[10px] text-muted -mt-1">
        将重拉 <span className="font-mono text-secondary">{startDate}</span>
        {' → '}<span className="font-mono text-secondary">{today}</span>(今天) 的 A股日K · 除权 · 指数并重算指标
      </div>

      <button
        onClick={() => repair.mutate()}
        disabled={!canSubmit}
        className="w-full inline-flex items-center justify-center gap-1.5 px-3 py-1.5 rounded-btn bg-accent/90 text-white text-xs font-medium hover:bg-accent disabled:opacity-40 disabled:pointer-events-none transition-colors duration-150"
      >
        {repair.isPending ? (
          <>
            <Loader2 className="h-3 w-3 animate-spin" />
            请求中…
          </>
        ) : (
          <>开始修正</>
        )}
      </button>

      {!hasBatchCap && (
        <span className="block text-center">
          <MissingCapChip capKey="kline.daily.batch" />
        </span>
      )}
    </div>
  )
}
