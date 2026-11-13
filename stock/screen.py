"""국내 주식 단기 반등 스크리너 (매일 장마감 후 실행).

데이터: 네이버 증권 (종목 목록 + 일봉 OHLCV). 표준 라이브러리만 사용.
출력: stock/data/YYYYMMDD.json, stock/latest.json, stock/index.json

사용법: python3 screen.py [--force]   (--force: 오늘 거래일이 아니어도 저장)
"""
import json
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from pathlib import Path

UA = {"User-Agent": "Mozilla/5.0"}
BASE = Path(__file__).resolve().parent
KST = timezone(timedelta(hours=9))
MIN_TRADING_VALUE = 5e8  # 20일 평균 거래대금 5억원 미만은 제외

# 신호 정의 (웹페이지에서도 이 설명을 사용)
SIGNALS = {
    "rsi":    "RSI(14) 과매도 — 최근 5일 중 RSI < 30",
    "macd":   "MACD 골든크로스 — 최근 5일 내 MACD선이 시그널선 상향 돌파",
    "stoch":  "스토캐스틱 골든크로스 — 최근 3일 내 %K가 %D 상향 돌파 (20 이하 구간)",
    "bb":     "볼린저밴드 하단 반등 — 최근 3일 내 하단 터치 후 오늘 밴드 안에서 상승 마감",
    "div":    "RSI 상승 다이버전스 — 주가는 저점 갱신, RSI는 저점 상승",
    "disp":   "이격도 과대 — 종가가 20일 이동평균 대비 -10% 이하",
    "volup":  "거래량 급증 양봉 — 거래량이 20일 평균의 2배 이상 + 양봉",
    "hammer": "망치형 캔들 — 하락 추세에서 긴 아래꼬리",
}


def get(url, encoding="utf-8"):
    for attempt in range(3):
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                return r.read().decode(encoding, errors="replace")
        except Exception:
            time.sleep(1 + attempt)
    return None


def list_stocks(market):
    out, page = [], 1
    while True:
        txt = get(f"https://m.stock.naver.com/api/stocks/marketValue/{market}?page={page}&pageSize=100")
        stocks = json.loads(txt).get("stocks", []) if txt else []
        if not stocks:
            return out
        for s in stocks:
            if s.get("stockEndType") == "stock" and s.get("tradeStopType", {}).get("name") == "TRADING":
                out.append({"code": s["itemCode"], "name": s["stockName"], "market": market,
                            "marketValue": s.get("marketValueHangeul", "")})
        page += 1


def daily_bars(code, count=200):
    txt = get(f"https://fchart.stock.naver.com/sise.nhn?symbol={code}&timeframe=day&count={count}&requestType=0",
              encoding="euc-kr")
    bars = []
    for part in (txt or "").split('<item data="')[1:]:
        d, o, h, l, c, v = part.split('"')[0].split("|")
        if float(c) > 0:
            bars.append((d, float(o), float(h), float(l), float(c), float(v)))
    return bars


# ---------- 지표 ----------
def sma(values, n):
    return [None if i < n - 1 else sum(values[i - n + 1:i + 1]) / n for i in range(len(values))]


def ema(values, n):
    k, out = 2 / (n + 1), [values[0]]
    for v in values[1:]:
        out.append(v * k + out[-1] * (1 - k))
    return out


def rsi(closes, n=14):
    gains = [max(closes[i] - closes[i - 1], 0) for i in range(1, len(closes))]
    losses = [max(closes[i - 1] - closes[i], 0) for i in range(1, len(closes))]
    ag, al = sum(gains[:n]) / n, sum(losses[:n]) / n
    out = [50.0] * (n + 1)
    out[n] = 100 - 100 / (1 + ag / al) if al else 100
    for i in range(n, len(gains)):  # Wilder 평활
        ag = (ag * (n - 1) + gains[i]) / n
        al = (al * (n - 1) + losses[i]) / n
        out.append(100 - 100 / (1 + ag / al) if al else 100)
    return out


def stochastic(highs, lows, closes, n=14, k=3, d=3):
    fast = []
    for i in range(len(closes)):
        hh, ll = max(highs[max(0, i - n + 1):i + 1]), min(lows[max(0, i - n + 1):i + 1])
        fast.append(50.0 if hh == ll else (closes[i] - ll) / (hh - ll) * 100)
    slow_k = [x if x is not None else 50.0 for x in sma(fast, k)]
    slow_d = [x if x is not None else 50.0 for x in sma(slow_k, d)]
    return slow_k, slow_d


def crossed_up(a, b, i):
    return a[i - 1] <= b[i - 1] and a[i] > b[i]


def analyze(stock):
    bars = daily_bars(stock["code"])
    if len(bars) < 60:
        return None
    dates = [b[0] for b in bars]
    o, h, l, c, v = ([b[j] for b in bars] for j in range(1, 6))
    last = len(c) - 1

    avg_value = sum(c[i] * v[i] for i in range(last - 19, last + 1)) / 20
    if avg_value < MIN_TRADING_VALUE:
        return None

    r = rsi(c)
    macd = [a - b for a, b in zip(ema(c, 12), ema(c, 26))]
    sig = ema(macd, 9)
    sk, sd = stochastic(h, l, c)
    ma20 = sma(c, 20)
    std20 = [None if ma20[i] is None else (sum((x - ma20[i]) ** 2 for x in c[i - 19:i + 1]) / 20) ** 0.5
             for i in range(len(c))]
    lower = [None if ma20[i] is None else ma20[i] - 2 * std20[i] for i in range(len(c))]
    vol20 = sma(v, 20)

    macd_cross = [i for i in range(last - 4, last + 1) if crossed_up(macd, sig, i)]
    body = abs(c[last] - o[last])
    lower_shadow = min(o[last], c[last]) - l[last]
    upper_shadow = h[last] - max(o[last], c[last])
    early, recent = range(last - 19, last - 4), range(last - 4, last + 1)

    hit = {
        "rsi": min(r[i] for i in recent) < 30,
        "macd": bool(macd_cross),
        "stoch": any(crossed_up(sk, sd, i) and sk[i - 1] < 20 for i in range(last - 2, last + 1)),
        "bb": any(l[i] <= lower[i] for i in range(last - 2, last + 1))
              and c[last] > lower[last] and c[last] > c[last - 1],
        "div": min(l[i] for i in recent) < min(l[i] for i in early)
               and min(r[i] for i in recent) > min(r[i] for i in early)
               and min(r[i] for i in early) < 35,
        "disp": c[last] / ma20[last] <= 0.90,
        "volup": v[last] >= 2 * vol20[last - 1] and c[last] > o[last],
        "hammer": c[last] < ma20[last] and body > 0
                  and lower_shadow >= 2 * body and upper_shadow <= body,
    }
    signals = [k for k, ok in hit.items() if ok]
    core = hit["rsi"] and hit["macd"]  # 원래 요청 조건
    if not core and len(signals) < 3:
        return None

    return {
        **stock,
        "date": dates[last],
        "close": c[last],
        "change": round((c[last] / c[last - 1] - 1) * 100, 2),
        "rsi": round(r[last], 1),
        "rsiMin5d": round(min(r[i] for i in recent), 1),
        "stochK": round(sk[last], 1),
        "disparity": round(c[last] / ma20[last] * 100, 1),
        "volRatio": round(v[last] / vol20[last - 1], 2) if vol20[last - 1] else None,
        "tradingValue": round(c[last] * v[last] / 1e8, 1),  # 억원
        "crossDate": dates[macd_cross[-1]] if macd_cross else None,
        "core": core,
        "strict": core and bool(macd_cross) and macd_cross[-1] == last and r[last] < 30,
        "signals": signals,
        "score": len(signals),
    }


def main():
    force = "--force" in sys.argv
    stocks = list_stocks("KOSPI") + list_stocks("KOSDAQ")
    print(f"대상 종목: {len(stocks)}개")
    with ThreadPoolExecutor(max_workers=8) as ex:
        hits = [h for h in ex.map(analyze, stocks) if h]

    # 기준일 = 삼성전자 마지막 거래일
    ref = daily_bars("005930", 1)
    trade_date = ref[-1][0] if ref else datetime.now(KST).strftime("%Y%m%d")
    today = datetime.now(KST).strftime("%Y%m%d")
    if trade_date != today and not force:
        print(f"오늘({today})은 거래일이 아님 (마지막 거래일 {trade_date}) — 저장 안 함")
        return 2
    hits = [h for h in hits if h["date"] == trade_date]
    hits.sort(key=lambda h: (not h["strict"], not h["core"], -h["score"], h["rsiMin5d"]))

    result = {"date": trade_date, "generated": datetime.now(KST).strftime("%Y-%m-%d %H:%M KST"),
              "scanned": len(stocks), "minTradingValue": MIN_TRADING_VALUE,
              "signalInfo": SIGNALS, "stocks": hits}
    data_dir = BASE / "data"
    data_dir.mkdir(exist_ok=True)
    payload = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    (data_dir / f"{trade_date}.json").write_text(payload)
    (BASE / "latest.json").write_text(payload)
    dates = sorted((p.stem for p in data_dir.glob("*.json")), reverse=True)
    (BASE / "index.json").write_text(json.dumps(dates))

    print(f"{trade_date}: 후보 {len(hits)}개 (핵심조건 {sum(h['core'] for h in hits)}, "
          f"당일동시 {sum(h['strict'] for h in hits)})")
    for h in hits[:15]:
        print(f'  {h["score"]}점 {h["code"]} {h["name"]:<12} RSI {h["rsi"]:>5}  {",".join(h["signals"])}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
