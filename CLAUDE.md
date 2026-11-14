# Test_Folder — 개인 대시보드

GitHub Pages: https://pwj7380-byte.github.io/Test_Folder/ (index.html)

## 주의
- `.git/hooks/post-commit`이 자동으로 push → **커밋하면 바로 공개 저장소에 올라감.** 비밀정보 커밋 금지.
- `RwsDiff/`는 별도 git 저장소(.gitignore 처리). 여기서 건드리지 말 것.

## 대시보드 (index.html)
- 단일 파일, 다크/골드, 모바일 우선. 하단 탭 구조(현재: 운동). 새 섹션은 `<section id="tab-xxx">` + nav 버튼으로 같은 스타일로 추가.
- 운동 상태는 localStorage `dash.fit.v1` (기기별, 백업/불러오기 버튼).
- 이 VM엔 브라우저 없음 → 로직은 Node vm 하네스로 테스트.
