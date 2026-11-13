#!/bin/sh
# 매 거래일 21:00 KST: 스크리너 실행 → 결과 커밋 (post-commit 훅이 GitHub로 push)
cd "$(dirname "$0")/.." || exit 1
echo "=== $(TZ=Asia/Seoul date '+%F %T KST') ==="
python3 -I stock/screen.py || { echo "스크리너 종료 코드 $? — 커밋 생략"; exit 0; }
git add stocks.html stock/
git diff --cached --quiet && { echo "변경 없음"; exit 0; }
git commit -q -m "스크리너 결과 $(TZ=Asia/Seoul date +%F)"
