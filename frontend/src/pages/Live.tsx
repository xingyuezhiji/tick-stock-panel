import { useEffect, useMemo, useState, type Dispatch, type SetStateAction } from 'react'
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'
import { AlertTriangle, CheckCircle2, RefreshCcw, ShieldCheck, ShoppingCart, TrendingDown } from 'lucide-react'
import { api, type LiveOrderBatchResult } from '@/lib/api'
import { QK } from '@/lib/queryKeys'
import { cn } from '@/lib/cn'
import { priceColorClass } from '@/lib/format'
import { PageHeader } from '@/components/PageHeader'
import { Modal } from '@/components/Modal'

const ACC_STORAGE_KEY = 'paper.account'

const ORDER_TYPE_LABEL: Record<string, string> = {
  market: '即时',
  next_open: '次日开盘',
  close: '当日收盘',
}

function fmtNum(v: number | null | undefined, digits = 2) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return Number(v).toLocaleString('zh-CN', { minimumFractionDigits: digits, maximumFractionDigits: digits })
}

function scoreText(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return Number(v).toFixed(4)
}

function fmtPctPercent(v: number | null | undefined) {
  if (v == null || Number.isNaN(Number(v))) return '--'
  return `${Number(v) >= 0 ? '+' : ''}${Number(v).toFixed(2)}%`
}

function ResultPanel({ result }: { result: LiveOrderBatchResult | null }) {
  if (!result) return null
  return (
    <section className="rounded-card border border-border bg-surface p-4">
      <div className="flex items-center gap-2 text-sm font-medium">
        <CheckCircle2 className="h-4 w-4 text-accent" />
        委托结果
        <span className="rounded-full bg-elevated px-2 py-0.5 text-[11px] text-muted">{result.broker}</span>
      </div>
      <div className="mt-3 grid gap-3 lg:grid-cols-3">
        <div>
          <div className="text-xs text-muted">已创建</div>
          <div className="mt-1 space-y-1 text-xs">
            {result.created.length === 0 && <div className="text-muted">无</div>}
            {result.created.map(o => (
              <div key={o.id} className="font-mono text-foreground">{o.symbol} {o.side === 'buy' ? '买入' : '卖出'} {o.qty}股</div>
            ))}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted">已跳过</div>
          <div className="mt-1 space-y-1 text-xs">
            {result.skipped.length === 0 && <div className="text-muted">无</div>}
            {result.skipped.map((s, i) => (
              <div key={`${s.symbol}-${i}`}><span className="font-mono">{s.symbol}</span> · {s.message || s.reason}</div>
            ))}
          </div>
        </div>
        <div>
          <div className="text-xs text-muted">错误</div>
          <div className="mt-1 space-y-1 text-xs">
            {result.errors.length === 0 && <div className="text-muted">无</div>}
            {result.errors.map((e, i) => (
              <div key={i} className="text-danger">{e.symbol ? `${e.symbol} · ` : ''}{e.message}</div>
            ))}
          </div>
        </div>
      </div>
    </section>
  )
}

export function Live() {
  const qc = useQueryClient()
  const [account, setAccount] = useState(() => localStorage.getItem(ACC_STORAGE_KEY) || 'default')
  const [strategyId, setStrategyId] = useState('')
  const [asOf, setAsOf] = useState('')
  const [broker, setBroker] = useState('paper')
  const [topN, setTopN] = useState(30)
  const [bufferN, setBufferN] = useState(45)
  const [amount, setAmount] = useState(10000)
  const [orderType, setOrderType] = useState<'market' | 'next_open' | 'close'>('next_open')
  const [selectedBuy, setSelectedBuy] = useState<Set<string>>(new Set())
  const [selectedSell, setSelectedSell] = useState<Set<string>>(new Set())
  const [confirm, setConfirm] = useState<'buy' | 'sell' | null>(null)
  const [lastResult, setLastResult] = useState<LiveOrderBatchResult | null>(null)

  const accountsQ = useQuery({ queryKey: QK.paperAccounts, queryFn: api.paperAccounts })
  const brokersQ = useQuery({ queryKey: QK.liveBrokers, queryFn: api.liveBrokers })
  const strategiesQ = useQuery({
    queryKey: QK.screenerStrategies('stock', 'all'),
    queryFn: () => api.screenerStrategies('stock', 'all'),
  })

  const strategies = strategiesQ.data?.presets ?? []
  useEffect(() => {
    if (!strategyId && strategies.length > 0) setStrategyId(strategies[0].id)
  }, [strategyId, strategies])

  const poolQ = useQuery({
    queryKey: QK.liveStrategyPool(strategyId, account, broker, asOf, topN, bufferN),
    queryFn: () => api.liveStrategyPool({
      strategy_id: strategyId,
      account,
      broker,
      as_of: asOf || undefined,
      asset_type: 'stock',
      timeframe: '1d',
      top_n: topN,
      buffer_n: bufferN,
    }),
    enabled: !!strategyId,
  })

  const candidates = poolQ.data?.candidates ?? []
  const holdings = poolQ.data?.holdings ?? []
  const buyable = useMemo(() => candidates.filter(r => !r.in_position).map(r => r.symbol), [candidates])
  const sellable = useMemo(() => holdings.filter(r => !r.in_buffer && Number(r.available_qty) > 0).map(r => r.symbol), [holdings])
  const selectedBuyList = useMemo(() => buyable.filter(s => selectedBuy.has(s)), [buyable, selectedBuy])
  const selectedSellList = useMemo(() => sellable.filter(s => selectedSell.has(s)), [sellable, selectedSell])
  const brokerInfo = brokersQ.data?.brokers.find(b => b.id === broker)
  const brokerDisabled = brokerInfo?.enabled === false

  useEffect(() => {
    setSelectedBuy(new Set(buyable))
  }, [buyable.join('|')])
  useEffect(() => {
    setSelectedSell(new Set(sellable))
  }, [sellable.join('|')])

  const invalidateAfterOrder = () => {
    qc.invalidateQueries({ queryKey: QK.paperAll })
    qc.invalidateQueries({ queryKey: ['live'] })
  }
  const buyM = useMutation({
    mutationFn: () => api.liveBuySelected({
      strategy_id: strategyId,
      symbols: selectedBuyList,
      account,
      broker,
      as_of: asOf || undefined,
      asset_type: 'stock',
      timeframe: '1d',
      top_n: topN,
      buffer_n: bufferN,
      size_mode: 'fixed_amount',
      amount_per_symbol: amount,
      order_type: orderType,
    }),
    onSuccess: data => {
      setLastResult(data)
      setConfirm(null)
      invalidateAfterOrder()
    },
  })
  const sellM = useMutation({
    mutationFn: () => api.liveSellOutOfBuffer({
      strategy_id: strategyId,
      symbols: selectedSellList,
      account,
      broker,
      as_of: asOf || undefined,
      asset_type: 'stock',
      timeframe: '1d',
      top_n: topN,
      buffer_n: bufferN,
      order_type: orderType,
    }),
    onSuccess: data => {
      setLastResult(data)
      setConfirm(null)
      invalidateAfterOrder()
    },
  })

  const toggle = (set: Dispatch<SetStateAction<Set<string>>>, symbol: string) => {
    set(prev => {
      const next = new Set(prev)
      next.has(symbol) ? next.delete(symbol) : next.add(symbol)
      return next
    })
  }
  const setAccountAndPersist = (id: string) => {
    setAccount(id)
    localStorage.setItem(ACC_STORAGE_KEY, id)
  }

  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <PageHeader
        title="实盘"
        subtitle="策略候选池 · 手动确认 · V1 模拟盘执行"
        titleExtra={<span className="rounded-full bg-accent/10 px-2 py-0.5 text-[10px] text-accent">模拟盘</span>}
        right={
          <button
            onClick={() => poolQ.refetch()}
            className="flex items-center gap-1 rounded-btn border border-border px-2 py-1 text-xs text-muted transition-colors hover:border-accent/40 hover:text-accent"
            disabled={poolQ.isFetching}
          >
            <RefreshCcw className={cn('h-3.5 w-3.5', poolQ.isFetching && 'animate-spin')} />
            刷新
          </button>
        }
      />
      <div className="min-h-0 flex-1 space-y-4 overflow-y-auto p-5">
        <section className="rounded-card border border-border bg-surface p-4">
          <div className="grid gap-3 lg:grid-cols-[1.4fr_1fr_1fr_0.8fr_0.8fr_0.8fr_1fr]">
            <label className="text-xs text-muted">
              策略
              <select value={strategyId} onChange={e => setStrategyId(e.target.value)} className="mt-1 w-full rounded-btn border border-border bg-base px-2 py-2 text-sm text-foreground outline-none focus:border-accent/50">
                {strategies.map(s => <option key={s.id} value={s.id}>{s.name || s.id}</option>)}
              </select>
            </label>
            <label className="text-xs text-muted">
              账户
              <select value={account} onChange={e => setAccountAndPersist(e.target.value)} className="mt-1 w-full rounded-btn border border-border bg-base px-2 py-2 text-sm text-foreground outline-none focus:border-accent/50">
                {(accountsQ.data?.accounts ?? [{ id: account, name: account }]).map(a => <option key={a.id} value={a.id}>{a.name || a.id}</option>)}
              </select>
            </label>
            <label className="text-xs text-muted">
              Broker
              <select value={broker} onChange={e => setBroker(e.target.value)} className="mt-1 w-full rounded-btn border border-border bg-base px-2 py-2 text-sm text-foreground outline-none focus:border-accent/50">
                {(brokersQ.data?.brokers ?? [{ id: 'paper', label: '模拟盘', enabled: true }]).map(b => (
                  <option key={b.id} value={b.id} disabled={!b.enabled}>{b.label}{b.enabled ? '' : '（未配置）'}</option>
                ))}
              </select>
            </label>
            <label className="text-xs text-muted">
              日期
              <input type="date" value={asOf} onChange={e => setAsOf(e.target.value)} className="mt-1 w-full rounded-btn border border-border bg-base px-2 py-2 text-sm text-foreground outline-none focus:border-accent/50" />
            </label>
            <label className="text-xs text-muted">
              TopN
              <input type="number" min={1} value={topN} onChange={e => setTopN(Math.max(1, Number(e.target.value) || 1))} className="mt-1 w-full rounded-btn border border-border bg-base px-2 py-2 text-sm text-foreground outline-none focus:border-accent/50" />
            </label>
            <label className="text-xs text-muted">
              BufferN
              <input type="number" min={1} value={bufferN} onChange={e => setBufferN(Math.max(1, Number(e.target.value) || 1))} className="mt-1 w-full rounded-btn border border-border bg-base px-2 py-2 text-sm text-foreground outline-none focus:border-accent/50" />
            </label>
            <label className="text-xs text-muted">
              单票金额
              <input type="number" min={100} step={100} value={amount} onChange={e => setAmount(Math.max(100, Number(e.target.value) || 100))} className="mt-1 w-full rounded-btn border border-border bg-base px-2 py-2 text-sm text-foreground outline-none focus:border-accent/50" />
            </label>
          </div>
          <div className="mt-3 flex flex-wrap items-center gap-2">
            {(['next_open', 'market', 'close'] as const).map(t => (
              <button
                key={t}
                onClick={() => setOrderType(t)}
                className={cn(
                  'rounded-btn border px-3 py-1 text-xs transition-colors',
                  orderType === t ? 'border-accent bg-accent/10 text-accent' : 'border-border text-muted hover:border-accent/40 hover:text-accent',
                )}
              >
                {ORDER_TYPE_LABEL[t]}
              </button>
            ))}
            {brokerDisabled && (
              <span className="inline-flex items-center gap-1 rounded-full bg-warning/10 px-2 py-1 text-[11px] text-warning">
                <AlertTriangle className="h-3 w-3" />
                当前 broker 未配置
              </span>
            )}
          </div>
        </section>

        <div className="grid gap-4 xl:grid-cols-2">
          <section className="rounded-card border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div>
                <div className="flex items-center gap-2 text-sm font-medium"><ShoppingCart className="h-4 w-4 text-accent" />候选买入</div>
                <div className="mt-0.5 text-[11px] text-muted">{poolQ.data?.strategy_name ?? '策略'} · {poolQ.data?.as_of ?? '--'}</div>
              </div>
              <button
                onClick={() => setConfirm('buy')}
                disabled={selectedBuyList.length === 0 || brokerDisabled || buyM.isPending}
                className="rounded-btn bg-accent px-3 py-1.5 text-xs text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
              >
                买入 {selectedBuyList.length}
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-border text-muted">
                  <tr>
                    <th className="w-10 px-3 py-2"><input type="checkbox" checked={buyable.length > 0 && selectedBuyList.length === buyable.length} onChange={e => setSelectedBuy(new Set(e.target.checked ? buyable : []))} /></th>
                    <th className="px-3 py-2">排名</th>
                    <th className="px-3 py-2">股票</th>
                    <th className="px-3 py-2 text-right">分数</th>
                    <th className="px-3 py-2 text-right">参考价</th>
                    <th className="px-3 py-2 text-right">持仓</th>
                  </tr>
                </thead>
                <tbody>
                  {poolQ.isFetching && <tr><td colSpan={6} className="px-3 py-8 text-center text-muted">加载中…</td></tr>}
                  {!poolQ.isFetching && candidates.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-muted">暂无候选</td></tr>}
                  {candidates.map(r => {
                    const disabled = r.in_position
                    return (
                      <tr key={r.symbol} className="border-b border-border/60 last:border-b-0 hover:bg-elevated/40">
                        <td className="px-3 py-2"><input type="checkbox" disabled={disabled} checked={selectedBuy.has(r.symbol)} onChange={() => toggle(setSelectedBuy, r.symbol)} /></td>
                        <td className="px-3 py-2 font-mono text-muted">#{r.rank}</td>
                        <td className="px-3 py-2"><div className="font-mono text-foreground">{r.symbol}</div><div className="text-[11px] text-muted">{r.name || '--'}</div></td>
                        <td className="px-3 py-2 text-right font-mono">{scoreText(r.score)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtNum(r.ref_price)}</td>
                        <td className="px-3 py-2 text-right">{r.in_position ? <span className="text-muted">已持 {fmtNum(r.held_qty, 0)}</span> : <span className="text-accent">可买</span>}</td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>

          <section className="rounded-card border border-border bg-surface">
            <div className="flex items-center justify-between border-b border-border px-4 py-3">
              <div>
                <div className="flex items-center gap-2 text-sm font-medium"><TrendingDown className="h-4 w-4 text-danger" />缓冲池卖出</div>
                <div className="mt-0.5 text-[11px] text-muted">当前持仓 · Buffer {poolQ.data?.buffer_n ?? bufferN}</div>
              </div>
              <button
                onClick={() => setConfirm('sell')}
                disabled={selectedSellList.length === 0 || brokerDisabled || sellM.isPending}
                className="rounded-btn bg-danger px-3 py-1.5 text-xs text-white transition-opacity disabled:cursor-not-allowed disabled:opacity-40"
              >
                卖出 {selectedSellList.length}
              </button>
            </div>
            <div className="overflow-x-auto">
              <table className="w-full text-left text-xs">
                <thead className="border-b border-border text-muted">
                  <tr>
                    <th className="w-10 px-3 py-2"><input type="checkbox" checked={sellable.length > 0 && selectedSellList.length === sellable.length} onChange={e => setSelectedSell(new Set(e.target.checked ? sellable : []))} /></th>
                    <th className="px-3 py-2">股票</th>
                    <th className="px-3 py-2 text-right">数量</th>
                    <th className="px-3 py-2 text-right">可卖</th>
                    <th className="px-3 py-2 text-right">盈亏</th>
                    <th className="px-3 py-2 text-right">状态</th>
                  </tr>
                </thead>
                <tbody>
                  {poolQ.isFetching && <tr><td colSpan={6} className="px-3 py-8 text-center text-muted">加载中…</td></tr>}
                  {!poolQ.isFetching && holdings.length === 0 && <tr><td colSpan={6} className="px-3 py-8 text-center text-muted">暂无持仓</td></tr>}
                  {holdings.map(r => {
                    const canSell = !r.in_buffer && Number(r.available_qty) > 0
                    return (
                      <tr key={r.symbol} className="border-b border-border/60 last:border-b-0 hover:bg-elevated/40">
                        <td className="px-3 py-2"><input type="checkbox" disabled={!canSell} checked={selectedSell.has(r.symbol)} onChange={() => toggle(setSelectedSell, r.symbol)} /></td>
                        <td className="px-3 py-2"><div className="font-mono text-foreground">{r.symbol}</div><div className="text-[11px] text-muted">{r.name || '--'}</div></td>
                        <td className="px-3 py-2 text-right font-mono">{fmtNum(r.qty, 0)}</td>
                        <td className="px-3 py-2 text-right font-mono">{fmtNum(r.available_qty, 0)}</td>
                        <td className={cn('px-3 py-2 text-right font-mono', priceColorClass(r.pnl_pct))}>{fmtNum(r.pnl)} · {fmtPctPercent(r.pnl_pct)}</td>
                        <td className="px-3 py-2 text-right">
                          {r.in_buffer ? <span className="text-muted">缓冲内</span> : canSell ? <span className="text-danger">可卖</span> : <span className="text-warning">T+1</span>}
                        </td>
                      </tr>
                    )
                  })}
                </tbody>
              </table>
            </div>
          </section>
        </div>

        <ResultPanel result={lastResult} />
      </div>

      {confirm && (
        <Modal onClose={() => setConfirm(null)} panelClassName="w-[92vw] max-w-md rounded-card border border-border bg-surface shadow-xl">
          <div className="border-b border-border px-4 py-3">
            <div className="flex items-center gap-2 text-sm font-medium">
              <ShieldCheck className="h-4 w-4 text-accent" />
              确认{confirm === 'buy' ? '买入' : '卖出'}
            </div>
          </div>
          <div className="space-y-3 p-4 text-sm">
            <div className="text-muted">Broker: {brokerInfo?.label ?? broker} · {ORDER_TYPE_LABEL[orderType]} · 仅创建模拟盘委托</div>
            <div className="max-h-32 overflow-y-auto rounded border border-border bg-base p-2 font-mono text-xs">
              {(confirm === 'buy' ? selectedBuyList : selectedSellList).join(', ') || '无'}
            </div>
            {confirm === 'buy' && <div className="text-xs text-muted">单票金额 {fmtNum(amount, 0)}，实际股数由参考价折算到整手。</div>}
          </div>
          <div className="flex justify-end gap-2 border-t border-border px-4 py-3">
            <button onClick={() => setConfirm(null)} className="rounded-btn border border-border px-3 py-1.5 text-xs text-muted hover:text-foreground">取消</button>
            <button
              onClick={() => confirm === 'buy' ? buyM.mutate() : sellM.mutate()}
              disabled={buyM.isPending || sellM.isPending}
              className="rounded-btn bg-accent px-3 py-1.5 text-xs text-white disabled:opacity-50"
            >
              确认提交
            </button>
          </div>
        </Modal>
      )}
    </div>
  )
}
