"""스크리너 백테스트: 점수별·신호별 과거 적중률과 수익률.

가정
- 매 거래일 장마감 후 스크리너 실행 → 다음 날 시가에 매수 → N 거래일 뒤 종가에 매도
- 적중 = 수익률 > 0. 수수료·세금 제외. 현재 상장 종목만 대상(상장폐지 종목 빠짐 = 생존 편향)
- 기준선(전체) = 같은 기간 유동성 조건을 통과한 모든 종목-일

출력: stock/backtest.json
"""
import json
import statistics
import sys
import time
from array import array
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))  # python -I 실행 시에도 screen.py 찾기
from screen import BASE, KST, SIGNALS, daily_bars, indicators, list_stocks, signals_at

BARS = 330          # 지표 준비 60일 + 검증 약 250거래일(1년) + 보유기간
HOLDS = (1, 5, 10)  # 보유 거래일


def run_stock(stock):
    bars = daily_bars(stock["code"], BARS)
    if len(bars) < 61 + max(HOLDS) + 1:
        return None
    x = indicators(bars)
    o, c = x["o"], x["c"]
    base = {h: array("f") for h in HOLDS}
    events = []
    for i in range(60, len(bars) - max(HOLDS) - 1):
        s = signals_at(x, i)
        if s is None or o[i + 1] <= 0:
            continue
        rets = {h: c[i + h] / o[i + 1] - 1 for h in HOLDS}
        if max(abs(r) for r in rets.values()) > 3:  # 액면분할 등 데이터 이상치 제외
            continue
        for h in HOLDS:
            base[h].append(rets[h])
        if s["score"]:
            events.append((s["score"], s["core"], s["strict"], s["signals"], rets, x["dates"][i]))
    return base, events


def stats(rets):
    if not rets:
        return None
    return {"n": len(rets), "win": round(sum(r > 0 for r in rets) / len(rets) * 100, 1),
            "avg": round(statistics.fmean(rets) * 100, 2), "median": round(statistics.median(rets) * 100, 2)}


def main():
    t0 = time.time()
    stocks = list_stocks("KOSPI") + list_stocks("KOSDAQ")
    print(f"대상 종목 {len(stocks)}개, 일봉 {BARS}개씩 수집·계산 중…", flush=True)
    base = {h: array("f") for h in HOLDS}
    events = []
    with ThreadPoolExecutor(max_workers=8) as ex:
        for res in ex.map(run_stock, stocks):
            if res:
                for h in HOLDS:
                    base[h].extend(res[0][h])
                events.extend(res[1])
    period = (min(e[5] for e in events), max(e[5] for e in events))

    def group(name, sel):
        g = [e for e in events if sel(e)]
        return {"name": name, **{f"d{h}": stats([e[4][h] for e in g]) for h in HOLDS}}

    by_score = [group(f"{k}점", lambda e, k=k: e[0] == k) for k in range(1, 5)]
    by_score.append(group("5점 이상", lambda e: e[0] >= 5))
    rules = [
        group("스크리너 선정 전체 (핵심조건 또는 3점 이상)", lambda e: e[1] or e[0] >= 3),
        group("핵심조건 (RSI<30 + MACD GC, 5일 이내)", lambda e: e[1]),
        group("당일 동시 발생 ★", lambda e: e[2]),
    ]
    by_signal = [group(SIGNALS[k].split(" — ")[0], lambda e, k=k: k in e[3]) for k in SIGNALS]
    for g, k in zip(by_signal, SIGNALS):
        g["key"] = k

    result = {
        "generated": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
        "period": period, "stocks": len(stocks), "holds": HOLDS,
        "baseline": {"name": "전체 종목 (기준선)", **{f"d{h}": stats(base[h]) for h in HOLDS}},
        "rules": rules, "byScore": by_score, "bySignal": by_signal,
    }
    (BASE / "backtest.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))

    def line(g):
        cells = []
        for h in HOLDS:
            s = g[f"d{h}"]
            cells.append(f"{h:>2}일 {s['win']:>5}% 평균{s['avg']:>+6}% 중앙{s['median']:>+6}%" if s else f"{h:>2}일 -")
        n = g[f"d{HOLDS[0]}"]["n"] if g[f"d{HOLDS[0]}"] else 0
        print(f"  {g['name'][:24]:<24} n={n:>7,} | " + " | ".join(cells))

    print(f"기간 {period[0]}~{period[1]} ({time.time() - t0:.0f}초)")
    print("[기준선]"); line(result["baseline"])
    print("[규칙]"); [line(g) for g in rules]
    print("[점수별]"); [line(g) for g in by_score]
    print("[신호별]"); [line(g) for g in by_signal]
    return 0


if __name__ == "__main__":
    sys.exit(main())
