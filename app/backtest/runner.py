"""Bar-by-bar replay of the live trading loop over historical data.

Every decision — screening, scoring, the intelligence gate, two-stage arming,
position sizing, and the manager's exit rules — is delegated to the same
production functions the live bot calls. The only things simulated here are the
market clock, order fills, and account state.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta

from ..arming import ArmingTracker
from ..exits import evaluate_exit
from ..indicators import compute_regime
from ..intelligence import enrich_candidate
from ..scanner import assemble_candidates
from ..session import NY, minutes_until_close, opening_delay_active, session_fraction
from ..strategy import position_size
from .broker import ClosedTrade, PendingOrder, SimulatedBroker
from .config import BacktestConfig, override_settings
from .data import BarStore
from .universe import DaySlice, UniverseBuilder, build_snapshot

BENCHMARK_SYMBOLS = ("SPY", "QQQ")
MAX_CANDIDATES_PER_SCAN = 3


@dataclass
class EquityPoint:
    at: datetime
    equity: float


@dataclass
class BacktestResult:
    trades: list[ClosedTrade]
    equity_curve: list[EquityPoint]
    daily_equity: list[tuple[date, float]]
    starting_equity: float
    sessions: int
    orders_placed: int
    orders_cancelled: int
    guard_days: int
    config: BacktestConfig
    diagnostics: dict = field(default_factory=dict)


class _DayContext:
    def __init__(self, store: BarStore, day: date, cfg: BacktestConfig, screener_top: int):
        tradeable = [s for s in cfg.symbols if s.upper() not in BENCHMARK_SYMBOLS]
        self.universe = UniverseBuilder(store, day, tradeable, screener_top)
        self.benchmarks = {
            symbol: DaySlice.build(symbol, store.minute_bars(symbol, day), store.prior_daily_close(symbol, day))
            for symbol in BENCHMARK_SYMBOLS
        }
        self.daily_history = {symbol: store.trailing_daily_bars(symbol, day, 20) for symbol in list(self.universe.slices)}
        times: set[datetime] = set()
        for day_slice in self.universe.slices.values(): times.update(day_slice.times)
        self.timeline = sorted(times)

    def regime_at(self, moment: datetime) -> dict:
        bars = {}
        for symbol, day_slice in self.benchmarks.items():
            index = day_slice.index_at(moment)
            bars[symbol] = day_slice.window(index) if index >= 0 else []
        return compute_regime(bars)

    def price_at(self, symbol: str, moment: datetime) -> float | None:
        day_slice = self.universe.slices.get(symbol)
        if not day_slice: return None
        index = day_slice.index_at(moment)
        return day_slice.price_at(index) if index >= 0 else None

    def bar_at(self, symbol: str, moment: datetime) -> dict | None:
        day_slice = self.universe.slices.get(symbol)
        if not day_slice: return None
        index = day_slice.index_at(moment)
        if index < 0 or day_slice.times[index] != moment: return None
        return day_slice.bars[index]

    def window_at(self, symbol: str, moment: datetime) -> list[dict]:
        day_slice = self.universe.slices.get(symbol)
        if not day_slice: return []
        index = day_slice.index_at(moment)
        return day_slice.window(index) if index >= 0 else []


def _prefilter(symbols: list[str], change_map: dict[str, float], ctx: _DayContext, moment: datetime, cfg_settings) -> list[str]:
    kept = []
    for symbol in symbols:
        price = ctx.price_at(symbol, moment)
        if price is None or not (cfg_settings.min_price <= price <= cfg_settings.max_price): continue
        change = change_map.get(symbol, 0.0)
        if not (cfg_settings.min_change_pct <= change <= cfg_settings.max_change_pct): continue
        kept.append(symbol)
    return kept


def run_backtest(store: BarStore, cfg: BacktestConfig, progress=None) -> BacktestResult:
    cfg_settings = cfg.effective_settings()
    broker = SimulatedBroker(cfg.starting_equity, cfg.execution)
    equity_curve=[]; daily_equity=[]; cooldowns={}; arming=ArmingTracker()
    orders_placed=0; guard_days=0; sessions=0; rejected_reasons={}
    days = [d for d in store.sessions() if cfg.start <= d <= cfg.end]

    with override_settings(cfg_settings):
        for day in days:
            ctx = _DayContext(store, day, cfg, cfg_settings.screener_top)
            if not ctx.timeline: continue
            sessions += 1; arming.clear(); day_start_equity=broker.equity({}); guard_tripped=False
            for moment in ctx.timeline:
                for symbol in list(broker.exposure_symbols()):
                    bar=ctx.bar_at(symbol,moment)
                    if bar is not None: broker.process_bar(symbol,bar,moment,cfg.use_true_initial_risk)
                marks={s:(ctx.price_at(s,moment) or p.entry_price) for s,p in broker.positions.items()}
                regime=ctx.regime_at(moment)
                for symbol in list(broker.positions):
                    position=broker.positions[symbol]
                    if position.entry_time >= moment: continue
                    current=marks.get(symbol)
                    if not current: continue
                    decision=evaluate_exit(position.state,current,ctx.window_at(symbol,moment),regime,moment,cfg_settings)
                    if decision:
                        broker.close(symbol,current,moment,decision.reason,decision.meta); marks.pop(symbol,None)
                equity=broker.equity(marks); equity_curve.append(EquityPoint(moment,equity))
                daily_return=(equity/day_start_equity-1)*100 if day_start_equity>0 else 0.0
                if not guard_tripped and daily_return <= -(cfg_settings.max_daily_loss*100):
                    guard_tripped=True; guard_days+=1; arming.clear()
                    if cfg_settings.close_on_daily_guard:
                        for symbol in list(broker.positions):
                            price=marks.get(symbol) or broker.positions[symbol].entry_price
                            broker.close(symbol,price,moment,"risk_guard_flatten")
                        for symbol in list(broker.pending): broker.cancel(symbol)
                if guard_tripped: continue
                if opening_delay_active(moment,cfg_settings.opening_delay_minutes): continue
                minutes_left=minutes_until_close(moment)
                if cfg.execution.flatten_at_close and cfg_settings.eod_flatten_enabled and minutes_left <= cfg_settings.eod_flatten_minutes:
                    for symbol in list(broker.positions):
                        price=marks.get(symbol) or broker.positions[symbol].entry_price
                        broker.close(symbol,price,moment,"eod_flatten")
                    for symbol in list(broker.pending): broker.cancel(symbol)
                    arming.clear(); continue
                if minutes_left <= cfg_settings.no_entry_minutes_before_close:
                    arming.clear(); continue

                symbols,change_map,active_rank,_=ctx.universe.select(moment,cfg.legacy_screener_change)
                symbols=_prefilter(symbols,change_map,ctx,moment,cfg_settings)
                if not symbols:
                    arming.retain_only(set(),"intel_or_setup_failed_recheck"); continue
                snapshots={}; bars_map={}
                for symbol in symbols:
                    day_slice=ctx.universe.slices[symbol]; index=day_slice.index_at(moment)
                    snapshots[symbol]=build_snapshot(day_slice,index,cfg.execution); bars_map[symbol]=day_slice.window(index)
                fraction=session_fraction(moment)
                rows=assemble_candidates(symbols,change_map,active_rank,snapshots,bars_map,ctx.daily_history,regime,fraction)
                enriched=[enrich_candidate(r) for r in rows]
                for row in enriched:
                    for reason in row.get("reject_reasons",[]): rejected_reasons[reason]=rejected_reasons.get(reason,0)+1
                eligible=[r for r in enriched if r.get("eligible") and r.get("decision",{}).get("action")=="ARM"]
                eligible.sort(key=lambda r:(r.get("intel_score",0),r.get("score",0),r.get("rvol",0)),reverse=True)
                arming.retain_only({r["symbol"].upper() for r in eligible},"intel_or_setup_failed_recheck")
                for candidate in eligible[:MAX_CANDIDATES_PER_SCAN]:
                    symbol=candidate["symbol"].upper()
                    if _cooldown_active(cooldowns,symbol,moment): continue
                    if arming.arm_or_confirm(candidate):
                        if _submit(broker,candidate,equity,moment,cfg,cfg_settings,cooldowns): orders_placed+=1
                        break

            last_moment=ctx.timeline[-1]
            if cfg.execution.flatten_at_close:
                for symbol in list(broker.positions):
                    price=ctx.price_at(symbol,last_moment) or broker.positions[symbol].entry_price
                    broker.close(symbol,price,last_moment,"session_close")
            for symbol in list(broker.pending): broker.cancel(symbol)
            closing_marks={s:(ctx.price_at(s,last_moment) or p.entry_price) for s,p in broker.positions.items()}
            daily_equity.append((day,broker.equity(closing_marks)))
            if progress: progress(day,len(broker.trades))

    return BacktestResult(trades=broker.trades,equity_curve=equity_curve,daily_equity=daily_equity,
        starting_equity=cfg.starting_equity,sessions=sessions,orders_placed=orders_placed,
        orders_cancelled=broker.cancelled,guard_days=guard_days,config=cfg,
        diagnostics={"reject_reasons":dict(sorted(rejected_reasons.items(),key=lambda kv:kv[1],reverse=True))})


def _cooldown_active(cooldowns: dict[str, datetime], symbol: str, moment: datetime) -> bool:
    until=cooldowns.get(symbol)
    if not until:return False
    if moment>=until:
        cooldowns.pop(symbol,None); return False
    return True


def _submit(broker: SimulatedBroker, candidate: dict, equity: float, moment: datetime,
            cfg: BacktestConfig, cfg_settings, cooldowns: dict[str, datetime]) -> bool:
    symbol=candidate["symbol"].upper(); entry=float(candidate.get("entry") or 0); stop=float(candidate.get("stop") or 0); target=float(candidate.get("target") or 0)
    if not (target>entry>stop>0):return False
    risk_pct=((entry-stop)/entry)*100
    if risk_pct>cfg_settings.max_stop_pct:return False
    if len(broker.positions)>=cfg_settings.max_open_positions:return False
    if symbol in broker.positions:return False
    qty=position_size(equity,entry,stop)
    if qty<1:return False
    profile=candidate.get("strategy_profile") or {}
    broker.place(PendingOrder(symbol=symbol,limit=entry,stop=stop,target=target,qty=qty,placed_at=moment,
        meta={"score":candidate.get("score"),"intel_score":candidate.get("intel_score"),"grade":candidate.get("grade"),
              "rvol":candidate.get("rvol"),"change_pct":candidate.get("change_pct"),"risk_pct":round(risk_pct,2),
              "entry_hour":moment.astimezone(NY).hour,"strategy_family":profile.get("family") or "UNKNOWN",
              "strategy_fit_score":profile.get("fit_score"),"strategy_confidence":profile.get("confidence")},))
    cooldowns[symbol]=moment+timedelta(minutes=cfg_settings.symbol_cooldown_minutes)
    return True
