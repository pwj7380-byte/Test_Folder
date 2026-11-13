"""스크리너 결과(latest.json)를 HTML 메일로 발송.

설정 파일: ~/.config/stock-mail.env  (GitHub에 올라가지 않음)
    GMAIL_USER=보내는주소@gmail.com
    GMAIL_APP_PASSWORD=구글 앱 비밀번호 16자리
    MAIL_TO=받는주소1,받는주소2

사용법: python3 mail.py            → 발송
        python3 mail.py --preview  → 발송 없이 HTML만 출력
"""
import json
import smtplib
import sys
from email.mime.text import MIMEText
from html import escape
from pathlib import Path

BASE = Path(__file__).resolve().parent
ENV = Path.home() / ".config" / "stock-mail.env"
PAGE = "https://pwj7380-byte.github.io/Test_Folder/stocks.html"
SHORT = {"rsi": "RSI과매도", "macd": "MACD GC", "stoch": "스토캐스틱 GC", "bb": "볼밴 하단반등",
         "div": "RSI 다이버전스", "disp": "이격도 과대", "volup": "거래량 급증", "hammer": "망치형"}
TOP = 30


def build(d):
    s = d["stocks"]
    date = f'{d["date"][:4]}-{d["date"][4:6]}-{d["date"][6:]}'
    core = sum(x["core"] for x in s)
    rows = "".join(
        f'<tr style="background:{"#fff4d6" if x["core"] else "#fff"}">'
        f'<td style="padding:6px 8px">{"★ " if x["strict"] else ""}'
        f'<a href="https://finance.naver.com/item/main.naver?code={x["code"]}">{escape(x["name"])}</a>'
        f' <span style="color:#888;font-size:12px">{x["code"]}</span></td>'
        f'<td style="padding:6px 8px;text-align:center">{x["score"]}</td>'
        f'<td style="padding:6px 8px;text-align:right">{x["close"]:,.0f}</td>'
        f'<td style="padding:6px 8px;text-align:right;color:{"#d92d20" if x["change"] > 0 else "#1f5fd1"}">'
        f'{x["change"]:+.2f}%</td>'
        f'<td style="padding:6px 8px;text-align:right">{x["rsi"]:.1f}</td>'
        f'<td style="padding:6px 8px;font-size:12px;color:#555">{", ".join(SHORT.get(k, k) for k in x["signals"])}</td></tr>'
        for x in sorted(s, key=lambda x: (not x["strict"], not x["core"], -x["score"], x["rsiMin5d"]))[:TOP])
    th = 'style="padding:6px 8px;text-align:left;border-bottom:2px solid #ddd"'
    html = f"""<div style="font-family:sans-serif;font-size:14px;color:#16181d;max-width:760px">
<h2 style="margin:0 0 4px">단기 반등 스크리너 · {date}</h2>
<p style="margin:0 0 12px;color:#667085">{d["scanned"]:,}개 종목 스캔 · 후보 {len(s)}개 · 핵심조건(RSI&lt;30 + MACD GC) {core}개</p>
<table style="border-collapse:collapse;width:100%">
<tr><th {th}>종목</th><th {th}>점수</th><th {th}>종가</th><th {th}>등락</th><th {th}>RSI</th><th {th}>신호</th></tr>
{rows}</table>
<p style="margin-top:12px">상위 {min(TOP, len(s))}개만 표시 · 전체 목록과 필터: <a href="{PAGE}">{PAGE}</a></p>
<p style="color:#888;font-size:12px">노란 행 = 핵심조건 충족, ★ = 당일 동시 발생. 기술적 지표 기반 기계적 필터이며 투자 권유가 아닙니다.</p>
</div>"""
    return f"[반등 스크리너] {date} 후보 {len(s)}개 (핵심 {core}개)", html


def main():
    d = json.loads((BASE / "latest.json").read_text())
    subject, html = build(d)
    if "--preview" in sys.argv:
        print(subject)
        print(html)
        return 0
    if not ENV.exists():
        print(f"메일 설정 파일 없음({ENV}) — 발송 생략")
        return 0
    cfg = dict(l.split("=", 1) for l in ENV.read_text().splitlines() if "=" in l and not l.startswith("#"))
    user, pw = cfg["GMAIL_USER"].strip(), cfg["GMAIL_APP_PASSWORD"].replace(" ", "").strip()
    to = [a.strip() for a in cfg.get("MAIL_TO", user).split(",") if a.strip()]
    msg = MIMEText(html, "html", "utf-8")
    msg["Subject"], msg["From"], msg["To"] = subject, user, ", ".join(to)
    with smtplib.SMTP_SSL("smtp.gmail.com", 465, timeout=30) as smtp:
        smtp.login(user, pw)
        smtp.sendmail(user, to, msg.as_string())
    print(f"메일 발송 완료 → {', '.join(to)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
