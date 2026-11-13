"""여러 알려진 전략을 같은 조건으로 비교하는 백테스트.

공통 가정
- 대상: 코스피·코스닥 현재 상장 보통주 중 20일 평균 거래대금 5억 원 이상 (생존 편향 있음)
- 매일 장마감 후 신호 → 다음 날 시가 매수 → H 거래일 뒤 종가 매도
- 거래비용: 왕복 0.25% (수수료 + 매도 세금 근사)
- 기간을 앞(A)/뒤(B) 절반으로 나눠, A에서 좋았던 전략이 B에서도 좋은지 확인

거래 단위 지표: 승률, 평균(기대값), 중앙값 (비용 차감 전/후)
포트폴리오 지표: 매일 신규 신호 종목을 H일 보유, 보유 중인 종목에 균등 분산했을 때의
  연환산 수익률(CAGR), 최대 낙폭(MDD), 샤프 비율, 투자 비중(신호가 있던 날 비율)

출력: stock/strategies.json
"""
import json
import math
import statistics
import sys
import time
from array import array
from collections import deque
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from screen import BASE, KST, daily_bars, indicators, list_stocks, rsi, signals_at, sma

BARS = 750          # 약 3년
WARM = 252          # 52주 고가·200일선 계산용 준비 기간
HOLDS = (5, 10, 20)
PORT_HOLDS = (5, 20)
COST = 0.0025
TOPN = 30
NAN = float("nan")

STRATS = [
    ("base", "전체 종목 (기준선)", "유동성 조건을 통과한 모든 종목을 매일 산다고 가정"),
    ("screen", "현재 스크리너", "핵심조건 또는 반등 신호 3개 이상"),
    ("core", "핵심조건 (RSI<30 + MACD GC)", "최근 5일 RSI(14)<30 + MACD 골든크로스"),
    ("screen_trend", "스크리너 + 추세 필터", "현재 스크리너 선정 종목 중 종가 > 120일 이동평균"),
    ("rsi2", "RSI(2) 눌림목", "종가 > 200일 이동평균(상승 추세)에서 RSI(2) < 10 (래리 코너스 방식)"),
    ("trend", "이동평균 정배열", "종가 > 20일 > 60일 > 120일 이동평균"),
    ("high52", "52주 신고가 근처", "종가가 52주 최고가의 95% 이상"),
    ("mom6", "6개월 모멘텀 상위 30", "최근 1개월을 뺀 6개월 수익률 상위 30종목"),
    ("mom3", "3개월 모멘텀 상위 30", "최근 3개월 수익률 상위 30종목"),
    ("lowvol", "저변동성 30", "최근 60일 일간 변동성이 가장 낮은 30종목"),
]
BIT = {k: 1 << i for i, (k, _, _) in enumerate(STRATS)}
CROSS = {"mom6": "mom6", "mom3": "mom3", "lowvol": "vol60"}  # 종목 간 순위로 고르는 전략 → 사용할 값


def rolling_max(values, n):
    out, dq = [], deque()
    for i, v in enumerate(values):
        while dq and values[dq[-1]] <= v:
            dq.pop()
        dq.append(i)
        if dq[0] <= i - n:
            dq.popleft()
        out.append(values[dq[0]])
    return out


def prepare(stock, cal_index, T):
    bars = daily_bars(stock["code"], BARS)
    if len(bars) < WARM + 30:
        return None
    x = indicators(bars)
    o, h, c = x["o"], x["h"], x["c"]
    n = len(c)
    ma60, ma120, ma200 = sma(c, 60), sma(c, 120), sma(c, 200)
    r2 = rsi(c, 2)
    hi252 = rolling_max(h, 252)
    rets = [0.0] + [c[i] / c[i - 1] - 1 for i in range(1, n)]
    s1 = s2 = 0.0
    vol60 = [NAN] * n
    for i in range(n):  # 60일 변동성 (누적합)
        s1 += rets[i]; s2 += rets[i] ** 2
        if i >= 60:
            s1 -= rets[i - 60]; s2 -= rets[i - 60] ** 2
            vol60[i] = math.sqrt(max(s2 / 60 - (s1 / 60) ** 2, 0))

    A = {k: array("f", [NAN]) * T for k in ("O", "C", "mom6", "mom3", "vol60")}
    flags = array("H", [0]) * T
    for i in range(n):
        p = cal_index.get(x["dates"][i])
        if p is None:
            continue
        A["O"][p], A["C"][p] = o[i], c[i]
        if i < WARM:
            continue
        s = signals_at(x, i)
        if s is None:  # 유동성 미달
            continue
        screen = s["core"] or s["score"] >= 3
        f = BIT["base"]
        f |= BIT["screen"] if screen else 0
        f |= BIT["core"] if s["core"] else 0
        f |= BIT["screen_trend"] if screen and c[i] > ma120[i] else 0
        f |= BIT["rsi2"] if c[i] > ma200[i] and r2[i] < 10 else 0
        f |= BIT["trend"] if c[i] > x["ma20"][i] > ma60[i] > ma120[i] else 0
        f |= BIT["high52"] if c[i] >= 0.95 * hi252[i] else 0
        flags[p] = f
        A["mom6"][p] = c[i - 21] / c[i - 126] - 1
        A["mom3"][p] = c[i] / c[i - 63] - 1
        A["vol60"][p] = vol60[i]
    return A, flags


def summarize(rets):
    if not rets:
        return None
    return {"n": len(rets), "win": round(sum(r > 0 for r in rets) / len(rets) * 100, 1),
            "avg": round(statistics.fmean(rets) * 100, 2),
            "median": round(statistics.median(rets) * 100, 2),
            "net": round((statistics.fmean(rets) - COST) * 100, 2),
            "netWin": round(sum(r > COST for r in rets) / len(rets) * 100, 1)}


def portfolio(sums, cnts, lo, hi):
    daily = [sums[t] / cnts[t] if cnts[t] else 0.0 for t in range(lo, hi)]
    if not daily:
        return None
    eq, peak, mdd = 1.0, 1.0, 0.0
    for r in daily:
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
    sd = statistics.pstdev(daily)
    return {"cagr": round((eq ** (252 / len(daily)) - 1) * 100, 1), "total": round((eq - 1) * 100, 1),
            "mdd": round(mdd * 100, 1),
            "sharpe": round(statistics.fmean(daily) / sd * math.sqrt(252), 2) if sd else None,
            "exposure": round(sum(1 for t in range(lo, hi) if cnts[t]) / len(daily) * 100, 1)}


BENCH = [("069500", "KODEX 200 보유 (대형주 지수)"), ("229200", "KODEX 코스닥150 보유")]


def benchmarks(cal, periods):
    """지수 ETF를 그냥 들고 있었을 때 (기간 수익률, CAGR, MDD)."""
    out = []
    for code, name in BENCH:
        closes = {b[0]: b[4] for b in daily_bars(code, BARS)}
        row = {"code": code, "name": name}
        for p, (lo, hi) in periods.items():
            series = [closes[d] for d in cal[lo:hi + 1] if d in closes]
            peak, mdd = series[0], 0.0
            for v in series:
                peak = max(peak, v)
                mdd = min(mdd, v / peak - 1)
            total = series[-1] / series[0]
            row[p] = {"total": round((total - 1) * 100, 1), "cagr": round((total ** (252 / len(series)) - 1) * 100, 1),
                      "mdd": round(mdd * 100, 1)}
        out.append(row)
    return out


def main():
    t0 = time.time()
    cal = [b[0] for b in daily_bars("005930", BARS)]
    T = len(cal)
    cal_index = {d: i for i, d in enumerate(cal)}
    stocks = list_stocks("KOSPI") + list_stocks("KOSDAQ")
    print(f"달력 {cal[0]}~{cal[-1]} ({T}일), 종목 {len(stocks)}개 수집·계산 중…", flush=True)
    with ThreadPoolExecutor(max_workers=8) as ex:
        data = [d for d in ex.map(lambda s: prepare(s, cal_index, T), stocks) if d]
    print(f"데이터 준비 {len(data)}종목 ({time.time() - t0:.0f}초)", flush=True)

    start, end = WARM, T - max(HOLDS) - 1          # 신호일 범위
    mid = (start + end) // 2
    periods = {"full": (start, end), "A": (start, mid), "B": (mid, end)}
    trades = {k: {p: {h: array("f") for h in HOLDS} for p in periods} for k, _, _ in STRATS}
    psum = {k: {h: [0.0] * T for h in PORT_HOLDS} for k, _, _ in STRATS}
    pcnt = {k: {h: [0] * T for h in PORT_HOLDS} for k, _, _ in STRATS}

    def take(key, A, t):
        O, C = A["O"], A["C"]
        entry = O[t + 1]
        if not entry > 0 or any(math.isnan(C[t + h]) for h in HOLDS):
            return
        fwd = {h: C[t + h] / entry - 1 for h in HOLDS}
        if max(abs(r) for r in fwd.values()) > 3:  # 데이터 이상치
            return
        for p, (lo, hi) in periods.items():
            if lo <= t < hi:
                for h in HOLDS:
                    trades[key][p][h].append(fwd[h])
        for h in PORT_HOLDS:
            prev = entry
            for k in range(t + 1, t + h + 1):
                ck = C[k]
                if math.isnan(ck):
                    continue
                r = ck / prev - 1 - (COST if k == t + 1 else 0)
                prev = ck
                psum[key][h][k] += r
                pcnt[key][h][k] += 1

    for t in range(start, end):
        ranks = {k: [] for k in CROSS}
        for A, flags in data:
            f = flags[t]
            if not f:
                continue
            for key, bit in BIT.items():
                if f & bit:
                    take(key, A, t)
            for k, field in CROSS.items():
                v = A[field][t]
                if not math.isnan(v):
                    ranks[k].append((v, A))
        for k in CROSS:
            picks = sorted(ranks[k], key=lambda z: z[0], reverse=(k != "lowvol"))[:TOPN]
            for _, A in picks:
                take(k, A, t)
    print(f"백테스트 완료 ({time.time() - t0:.0f}초)", flush=True)

    out = []
    for key, name, desc in STRATS:
        out.append({
            "key": key, "name": name, "desc": desc,
            "trades": {p: {f"d{h}": summarize(trades[key][p][h]) for h in HOLDS} for p in periods},
            "port": {f"h{h}": {p: portfolio(psum[key][h], pcnt[key][h], lo + 1, hi + 1)
                               for p, (lo, hi) in periods.items()} for h in PORT_HOLDS},
        })
    result = {"generated": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
              "periods": {p: [cal[lo], cal[hi - 1]] for p, (lo, hi) in periods.items()},
              "stocks": len(data), "cost": COST * 100, "topN": TOPN, "strategies": out,
              "benchmarks": benchmarks(cal, periods)}
    (BASE / "strategies.json").write_text(json.dumps(result, ensure_ascii=False, indent=1))

    print("기간:", {p: f"{a}~{b}" for p, (a, b) in result["periods"].items()})
    hdr = f'{"전략":<22}{"건수":>9} | {"10일승률":>7} {"10일평균":>7} {"비용후":>6} | {"20일승률":>7} {"20일평균":>7} | ' \
          f'{"CAGR(H20)":>9} {"MDD":>6} {"샤프":>5} | A→B 20일평균'
    print(hdr)
    for s in out:
        tr, po = s["trades"]["full"], s["port"]["h20"]["full"]
        a, b = s["trades"]["A"]["d20"], s["trades"]["B"]["d20"]
        if not tr["d10"]:
            print(f'{s["name"]:<22} 신호 없음'); continue
        print(f'{s["name"][:22]:<22}{tr["d10"]["n"]:>9,} | {tr["d10"]["win"]:>7} {tr["d10"]["avg"]:>+7} {tr["d10"]["net"]:>+6} | '
              f'{tr["d20"]["win"]:>7} {tr["d20"]["avg"]:>+7} | {po["cagr"]:>+9} {po["mdd"]:>6} {po["sharpe"] or 0:>5} | '
              f'{a["avg"] if a else "-":>+6} → {b["avg"] if b else "-":>+6}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
