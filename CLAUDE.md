# Test_Folder — 개인 대시보드 + 국내주식 반등 스크리너

GitHub Pages: https://pwj7380-byte.github.io/Test_Folder/ (index.html = 대시보드, stocks.html = 스크리너 결과)

## 주의
- `.git/hooks/post-commit`이 자동으로 push → **커밋하면 바로 공개 저장소에 올라감.** 비밀정보 커밋 금지.
- `RwsDiff/`는 별도 git 저장소(.gitignore 처리). 여기서 건드리지 말 것.
- index.html이 `stock/latest.json`, `stock/strategies.json`을 같은 출처에서 fetch → 경로 바꾸면 대시보드 깨짐.

## 대시보드 (index.html)
- 단일 파일, 다크/골드, 모바일 우선. 탭: 운동 / 주식. 새 기능은 같은 스타일의 탭·카드로 추가.
- 운동 상태는 localStorage `dash.fit.v1` (기기별).
- 이 VM엔 브라우저 없음 → 로직은 Node vm 하네스로 테스트.

## 스크리너 (stock/)
- `screen.py`: 표준 라이브러리 Python, 네이버 금융 API 사용 (KRX/KIND는 이 서버 IP 차단). 실행은 `python3 -I`.
- 필터: 20일 평균 거래대금 5억 미만, 시총 1000억 미만 제외.
- 출력: stock/latest.json, stock/index.json, stock/data/YYYYMMDD.json
- cron `0 12 * * 1-5` UTC (= 21:00 KST) → `stock/run_daily.sh` → 커밋(자동 push) → `mail.py`. 비거래일엔 exit 2로 커밋 생략. 로그 stock/cron.log (gitignore).
- 백테스트: `backtest.py` → backtest.json, `strategies.py`(약 5분) → strategies.json
