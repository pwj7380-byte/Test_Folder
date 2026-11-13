#!/bin/sh
# 매 거래일 21:00 KST: 스크리너 실행 → 결과 커밋(post-commit 훅이 GitHub로 push) → 메일 발송
cd "$(dirname "$0")/.." || exit 1
echo "=== $(TZ=Asia/Seoul date '+%F %T KST') ==="
python3 -I stock/screen.py || { echo "스크리너 종료 코드 $? — 생략"; exit 0; }
git add stocks.html stock/
git diff --cached --quiet || git commit -q -m "스크리너 결과 $(TZ=Asia/Seoul date +%F)"
python3 -I stock/mail.py || echo "메일 발송 실패"
