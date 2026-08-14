"""Performance statistics for a completed backtest."""
from __future__ import annotations
import math
from collections import defaultdict

from .runner import BacktestResult

TRADING_DAYS_PER_YEAR = 252


def _safe_div(a: float, b: float, default: float = 0.0) -> float:
    return a / b if b else default


def _drawdown(series: list[float]) -> float:
    peak=float("-inf"); worst=0.0
    for value in series:
        peak=max(peak,value)
        if peak>0: worst=min(worst,(value/peak-1)*100)
    return abs(worst)


def _sharpe(daily_returns: list[float]) -> float:
    if len(daily_returns)<2:return 0.0
    avg=sum(daily_returns)/len(daily_returns)
    variance=sum((r-avg)**2 for r in daily_returns)/(len(daily_returns)-1)
    sd=math.sqrt(variance)
    return _safe_div(avg,sd)*math.sqrt(TRADING_DAYS_PER_YEAR) if sd else 0.0


def _bucket(trades,key)->dict:
    grouped=defaultdict(list)
    for trade in trades: grouped[key(trade)].append(trade)
    out={}
    for name,group in sorted(grouped.items(),key=lambda kv:str(kv[0])):
        wins=[t for t in group if t.pnl>0]
        losses=[t for t in group if t.pnl<=0]
        gross_win=sum(t.pnl for t in wins); gross_loss=abs(sum(t.pnl for t in losses))
        out[str(name)]={
            "trades":len(group),
            "win_rate_pct":round(_safe_div(len(wins),len(group))*100,1),
            "avg_r":round(_safe_div(sum(t.r_multiple for t in group),len(group)),3),
            "total_pnl":round(sum(t.pnl for t in group),2),
            "profit_factor":round(_safe_div(gross_win,gross_loss,float("inf") if gross_win else 0.0),2),
        }
    return out


def summarize(result: BacktestResult)->dict:
    trades=result.trades
    ending_equity=result.daily_equity[-1][1] if result.daily_equity else result.starting_equity
    daily_returns=[]; previous=result.starting_equity
    for _,equity in result.daily_equity:
        if previous>0: daily_returns.append(equity/previous-1)
        previous=equity
    wins=[t for t in trades if t.pnl>0]; losses=[t for t in trades if t.pnl<=0]
    gross_win=sum(t.pnl for t in wins); gross_loss=abs(sum(t.pnl for t in losses)); r_values=[t.r_multiple for t in trades]
    return {
        "period":{"sessions":result.sessions,"first_day":str(result.daily_equity[0][0]) if result.daily_equity else None,"last_day":str(result.daily_equity[-1][0]) if result.daily_equity else None},
        "equity":{"starting":round(result.starting_equity,2),"ending":round(ending_equity,2),"total_return_pct":round(_safe_div(ending_equity-result.starting_equity,result.starting_equity)*100,2),"max_drawdown_pct":round(_drawdown([p.equity for p in result.equity_curve]),2),"sharpe":round(_sharpe(daily_returns),2)},
        "trades":{"count":len(trades),"orders_placed":result.orders_placed,"orders_never_filled":result.orders_cancelled,"fill_rate_pct":round(_safe_div(len(trades),result.orders_placed)*100,1),"trades_per_session":round(_safe_div(len(trades),result.sessions),2),"win_rate_pct":round(_safe_div(len(wins),len(trades))*100,1),"avg_r":round(_safe_div(sum(r_values),len(r_values)),3),"expectancy_r":round(_safe_div(sum(r_values),len(r_values)),3),"avg_win_r":round(_safe_div(sum(t.r_multiple for t in wins),len(wins)),3),"avg_loss_r":round(_safe_div(sum(t.r_multiple for t in losses),len(losses)),3),"best_r":round(max(r_values),3) if r_values else 0.0,"worst_r":round(min(r_values),3) if r_values else 0.0,"profit_factor":round(_safe_div(gross_win,gross_loss,float("inf") if gross_win else 0.0),2)},
        "risk":{"daily_loss_guard_days":result.guard_days,"guard_rate_pct":round(_safe_div(result.guard_days,result.sessions)*100,1)},
        "by_exit_reason":_bucket(trades,lambda t:t.reason),
        "by_grade":_bucket(trades,lambda t:t.meta.get("grade") or "?"),
        "by_strategy":_bucket(trades,lambda t:t.meta.get("strategy_family") or "UNKNOWN"),
        "by_entry_hour":_bucket(trades,lambda t:f"{t.meta.get('entry_hour','?')}:00 ET"),
        "top_reject_reasons":dict(list(result.diagnostics.get("reject_reasons",{}).items())[:10]),
    }


def format_report(summary:dict,config_notes:list[str]|None=None)->str:
    equity=summary["equity"]; trades=summary["trades"]; period=summary["period"]
    lines=["="*62,"  BACKTEST REPORT","="*62,f"  Sessions          {period['sessions']}  ({period['first_day']} → {period['last_day']})","","  EQUITY",f"    Start / End     ${equity['starting']:,.2f} → ${equity['ending']:,.2f}",f"    Total return    {equity['total_return_pct']:+.2f}%",f"    Max drawdown    {equity['max_drawdown_pct']:.2f}%",f"    Sharpe          {equity['sharpe']:.2f}","","  TRADES",f"    Orders placed   {trades['orders_placed']}  (filled {trades['count']}, {trades['fill_rate_pct']}%)",f"    Per session     {trades['trades_per_session']}",f"    Win rate        {trades['win_rate_pct']:.1f}%",f"    Expectancy      {trades['expectancy_r']:+.3f} R",f"    Avg win / loss  {trades['avg_win_r']:+.2f} R / {trades['avg_loss_r']:+.2f} R",f"    Best / worst    {trades['best_r']:+.2f} R / {trades['worst_r']:+.2f} R",f"    Profit factor   {trades['profit_factor']}","",f"  RISK    daily-loss-guard hit on {summary['risk']['daily_loss_guard_days']} day(s) ({summary['risk']['guard_rate_pct']}%)"]
    for title,key in (("EXITS","by_exit_reason"),("BY GRADE","by_grade"),("BY STRATEGY FAMILY","by_strategy"),("BY ENTRY HOUR","by_entry_hour")):
        rows=summary.get(key) or {}
        if not rows:continue
        lines += ["",f"  {title}"]
        for name,stats in rows.items():
            lines.append(f"    {name:<24} {stats['trades']:>4} trades   win {stats['win_rate_pct']:>5.1f}%   avg {stats['avg_r']:+.2f} R   PF {stats['profit_factor']:<5}   ${stats['total_pnl']:>10,.2f}")
    rejects=summary.get("top_reject_reasons") or {}
    if rejects:
        lines += ["","  WHY CANDIDATES WERE REJECTED (scan-level counts)"]
        for reason,count in rejects.items(): lines.append(f"    {reason:<46} {count:>8,}")
    if config_notes:
        lines += ["","  MODELLING ASSUMPTIONS"]+[f"    - {note}" for note in config_notes]
    lines.append("="*62)
    return "\n".join(lines)
