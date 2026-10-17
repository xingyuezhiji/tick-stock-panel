"""Fix sparse kline_daily partitions by downloading Fuyao daily-k dump.

覆盖区间: 2025-10-14 ~ 2026-10-09 (这 240 天原数据只有 10 只股票)
步骤:
  1. 下载扶摇 daily-k 全量 dump (~172MB)
  2. 解析并过滤缺失区间
  3. 覆盖写入 kline_daily 对应分区
  4. 重建 enriched 对应分区
  5. bump enriched generation, 清理矩阵缓存
  6. 验证分区行数恢复全市场规模
"""

from __future__ import annotations

import datetime as dt
import shutil
import sys
import time
from pathlib import Path

import polars as pl
import pyarrow.parquet as pq

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.enriched_generation import bump_enriched_generation
from app.indicators.pipeline import compute_enriched_history_window
from app.plugins.fuyao.client import FuyaoClient
from app.plugins.fuyao.provider import (
    _DAILY_DUMP_COLUMNS,
    _DAILY_DUMP_KIND,
    _SH_MS,
    get_api_key,
)
from app.tickflow.repository import DataStore, KlineRepository

# ========= 配置 =========
DATA_DIR = ROOT / "data"
CACHE_DIR = DATA_DIR / "cache" / "fuyao"
DUMP_PATH = CACHE_DIR / "daily_k_full.parquet"
FIX_START = dt.date(2025, 10, 14)   # 第一个 sparse 分区
FIX_END = dt.date(2026, 10, 9)       # 最后一个 sparse 分区
PRELOAD_START = dt.date(2025, 7, 1)  # 多 preload 3 个月, 让 rolling 指标有完整 warmup
PRELOAD_END = dt.date(2026, 10, 9)

MATRIX_CACHE = DATA_DIR / "cache" / "backtest" / "matrix_cache"

print(f"数据目录: {DATA_DIR}")
print(f"修复区间: {FIX_START} ~ {FIX_END} ({(FIX_END - FIX_START).days} 天)")
print(f"预载区间: {PRELOAD_START} ~ {PRELOAD_END}")


def step1_download_dump() -> Path:
    if DUMP_PATH.exists() and DUMP_PATH.stat().st_size > 10_000_000:
        print(f"[Step1] dump 已存在 ({DUMP_PATH.stat().st_size / 1024 / 1024:.1f}MB), 跳过下载")
        return DUMP_PATH
    api_key = get_api_key()
    if not api_key:
        raise RuntimeError("扶摇 API Key 未配置")
    print(f"[Step1] 下载 {_DAILY_DUMP_KIND} dump ...")
    client = FuyaoClient(api_key=api_key, timeout=30.0)
    try:
        t0 = time.time()
        CACHE_DIR.mkdir(parents=True, exist_ok=True)
        client.download_dump(_DAILY_DUMP_KIND, DUMP_PATH)
        print(f"[Step1] 下载完成: {DUMP_PATH.stat().st_size / 1024 / 1024:.1f}MB, 耗时 {time.time() - t0:.1f}s")
    finally:
        client.close()
    return DUMP_PATH


def step2_parse_dump(dump_path: Path) -> pl.DataFrame:
    print("[Step2] 解析 dump ...")
    t0 = time.time()
    dump = (
        pl.scan_parquet(dump_path)
        .filter((pl.col("interval") == "1d") & (pl.col("adjusted") == "none"))
        .with_columns(
            pl.from_epoch(pl.col("date_ms").cast(pl.Int64) + _SH_MS, time_unit="ms")
            .dt.date()
            .alias("date")
        )
        .filter((pl.col("date") >= PRELOAD_START) & (pl.col("date") <= PRELOAD_END))
        .collect()
    )
    print(f"[Step2] 原始过滤: {dump.height} 行, 日期 {dump['date'].min()} ~ {dump['date'].max()}, 耗时 {time.time() - t0:.1f}s")

    # thscode 格式是 "000001.SZ" — 直接当 symbol 用, 不要转换
    dump = dump.select(
        pl.col("thscode").alias("symbol"),
        pl.col("date"),
        pl.col("open_price").cast(pl.Float64).alias("open"),
        pl.col("high_price").cast(pl.Float64).alias("high"),
        pl.col("low_price").cast(pl.Float64).alias("low"),
        pl.col("close_price").cast(pl.Float64).alias("close"),
        (pl.col("volume").cast(pl.Float64) / 100.0).floor().alias("volume"),
        pl.col("turnover").cast(pl.Float64).alias("amount"),
    )
    dump = dump.filter(
        pl.col("open").is_finite() & pl.col("close").is_finite()
        & (pl.col("open") > 0) & (pl.col("close") > 0)
        & pl.col("symbol").str.contains(r"\.")
    )
    # 去重 (同 symbol + date 可能有重复行)
    dump = dump.unique(subset=["symbol", "date"], keep="last").sort(["symbol", "date"])
    print(f"[Step2] 转换后: {dump.height} 行, {dump['symbol'].n_unique()} 只股票, 耗时 {time.time() - t0:.1f}s")
    return dump


def step3_write_kline_daily(df: pl.DataFrame, repo: KlineRepository) -> None:
    """删除 FIX_START ~ FIX_END 原有分区, 从 dump 写入全市场版本."""
    kline_dir = DATA_DIR / "kline_daily"
    cur = FIX_START
    deleted = 0
    while cur <= FIX_END:
        part_file = kline_dir / f"date={cur.isoformat()}" / "part.parquet"
        if part_file.exists():
            part_file.unlink()
            deleted += 1
        cur += dt.timedelta(days=1)
        while cur.weekday() >= 5 and cur <= FIX_END:
            cur += dt.timedelta(days=1)

    fix_df = df.filter((pl.col("date") >= FIX_START) & (pl.col("date") <= FIX_END))
    print(f"[Step3] 删除 {deleted} 个旧分区, 写入 {fix_df.height} 行 ({fix_df['symbol'].n_unique()} 只)")
    t0 = time.time()
    repo._write_daily_partition(fix_df, "kline_daily")
    print(f"[Step3] kline_daily 写入完成, 耗时 {time.time() - t0:.1f}s")


def step4_rebuild_enriched(repo: KlineRepository) -> None:
    """重建 PRELOAD_START ~ PRELOAD_END 区间的 enriched."""
    print("[Step4] 重建 enriched ...")
    t0 = time.time()

    # 从 kline_daily parquet 直接读 (repo 只支持批量 symbol, 不支持 None)
    daily_df = (
        pl.scan_parquet(str(DATA_DIR / "kline_daily" / "date=*/part.parquet"),
            cast_options=pl.ScanCastOptions(integer_cast="allow-float"),
            extra_columns="ignore",
        )
        .select(["symbol", "date", "open", "high", "low", "close", "volume", "amount"])
        .filter(
            (pl.col("date") >= PRELOAD_START) & (pl.col("date") <= PRELOAD_END)
            & pl.col("symbol").is_not_null()
        )
        .sort(["symbol", "date"])
        .collect()
    )
    print(f"[Step4] 读取 kline_daily: {daily_df.height} 行, {daily_df['symbol'].n_unique()} 只")

    # compute_limit_signals 需要 raw_close/raw_high/raw_low
    daily_df = daily_df.with_columns(
        pl.col("close").alias("raw_close"),
        pl.col("high").alias("raw_high"),
        pl.col("low").alias("raw_low"),
    )

    instruments = repo.get_instruments_asset("stock")

    enriched_df = compute_enriched_history_window(
        daily_df,
        DATA_DIR,
        instruments=instruments,
        historical_shares=None,
    )
    print(f"[Step4] enriched 计算完成: {enriched_df.height} 行, 耗时 {time.time() - t0:.1f}s")

    # 删除 enriched 对应分区
    enrich_dir = DATA_DIR / "kline_daily_enriched"
    cur = PRELOAD_START
    while cur <= PRELOAD_END:
        part_file = enrich_dir / f"date={cur.isoformat()}" / "part.parquet"
        if part_file.exists():
            part_file.unlink()
        cur += dt.timedelta(days=1)
        while cur.weekday() >= 5 and cur <= PRELOAD_END:
            cur += dt.timedelta(days=1)

    fix_enriched = enriched_df.filter(
        (pl.col("date") >= PRELOAD_START) & (pl.col("date") <= PRELOAD_END)
    )
    repo._write_daily_partition(fix_enriched, "kline_daily_enriched")
    print(f"[Step4] enriched 写入完成, 总耗时 {time.time() - t0:.1f}s")


def step5_bump_and_clear(repo: KlineRepository) -> None:
    print("[Step5] bump enriched generation + 清理缓存")
    bump_enriched_generation(DATA_DIR, "stock")
    repo.clear_cache()
    if MATRIX_CACHE.exists():
        shutil.rmtree(MATRIX_CACHE, ignore_errors=True)
        print(f"[Step5] 已删除 {MATRIX_CACHE}")
    print("[Step5] 完成")


def step6_verify() -> None:
    print("[Step6] 验证修复结果")
    for name in ["kline_daily", "kline_daily_enriched"]:
        root = DATA_DIR / name
        sparse_dates = 0
        full_dates = 0
        total_rows = 0
        sample = []
        cur = FIX_START
        while cur <= FIX_END:
            p = root / f"date={cur.isoformat()}" / "part.parquet"
            if p.exists():
                try:
                    n = pq.read_metadata(p).num_rows
                except Exception:
                    n = -1
                total_rows += n if n > 0 else 0
                if n < 100:
                    sparse_dates += 1
                    sample.append(f"{cur.isoformat()}={n}")
                else:
                    full_dates += 1
            cur += dt.timedelta(days=1)
            while cur.weekday() >= 5 and cur <= FIX_END:
                cur += dt.timedelta(days=1)

        if sparse_dates == 0:
            print(f"  ✅ {name}: {full_dates} 个交易日, 总计 {total_rows} 行, 全部全市场规模")
        else:
            print(f"  ❌ {name}: 仍有 {sparse_dates} 个 sparse 分区, 示例: {sample[:5]}")


def main() -> None:
    t_total = time.time()
    store = DataStore(DATA_DIR)
    repo = KlineRepository(store)

    dump_path = step1_download_dump()
    df = step2_parse_dump(dump_path)
    step3_write_kline_daily(df, repo)
    step4_rebuild_enriched(repo)
    step5_bump_and_clear(repo)
    step6_verify()

    print(f"\n全部完成, 总耗时 {time.time() - t_total:.1f}s")


if __name__ == "__main__":
    main()
