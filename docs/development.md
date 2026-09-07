# 개발과 테스트

아래 명령은 저장소 루트에서 실행한다. 기본 검증은 네트워크·인증자료 없는 테스트다. 외부 integration은 별도 승인이 있을 때만 실행한다.

[문서 목록](README.md) · [프로젝트 소개](../README.md)

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium  # 브라우저 자동화를 실제 사용할 때만 필요
```

다른 프로젝트에서 사용할 때:

```bash
pip install -e /path/to/notion-native-toolkit

# Git 소스로 설치하는 경우
pip install git+https://github.com/seokmogu/notion-native-toolkit.git
```

## 테스트

`pytest`는 기본 런타임 의존성이 아니므로 `uv run --with pytest`로 실행합니다. 브라우저 어댑터는 `node --test tests/notion-desktop-adapter.test.mjs`로 별도 검증합니다. 외부 연동 없이 확인하려면 첫 번째 명령만 실행하세요.

```bash
# 유닛 테스트 (mock, API 호출 없음, 빠름)
uv run --with pytest pytest tests/ -q -m "not integration"

# Integration 테스트 전 Chrome 세션 동기화 및 내부 API 인증 확인
notion-native browser sync-chrome-cookies --profile worxphere --validate-internal

# Integration 테스트 (실제 Notion 내부 API read 호출, 유효한 token_v2 필요)
uv run --with pytest pytest tests/test_internal_integration.py -v

# 전체 테스트
uv run --with pytest pytest tests/ -v
```

### Integration 테스트의 역할

Integration 테스트는 **API 변경 감지기** 역할을 합니다. Notion이 내부 API를 변경하면 실패하는 테스트가 어떤 SDK 메서드가 영향 받았는지 정확히 알려줍니다.

| 테스트 카테고리 | 검증 항목 | 테스트 수 |
|--------------|----------|----------|
| Search | 풀텍스트 검색, 빈 쿼리 | 2 |
| Users | 사용자 검색, 팀, 도메인, 권한 그룹 | 6 |
| AI | 모델, 크레딧, 에이전트, 커넥터, 프롬프트 | 5 |
| Content | 페이지 로드, 백링크, 언어 감지 | 3 |
| Workspace | 사용량, Integration 검색 | 2 |
| **합계** | | **18** |

## 프로젝트 구조

```
notion-native-toolkit/
  src/notion_native_toolkit/
    __init__.py          # NotionToolkit 내보내기
    toolkit.py           # 프로필 기반 통합 진입점
    client.py            # 공식 API 클라이언트 (v1)
    internal.py          # 내부 API 클라이언트 (v3)
    browser.py           # Playwright 브라우저 자동화
    browser_state.py     # Playwright storage_state 쿠키 로더
    chrome_cookies.py    # Chrome 쿠키 → storage_state 동기화
    profiles.py          # 워크스페이스 프로필 관리
    credentials.py       # Keychain/환경변수 자격 증명
    cli.py               # CLI 인터페이스
    markdown.py          # 마크다운 ↔ Notion 블록 변환
    writer.py            # Notion 페이지 작성기
    deploy.py            # 디렉토리 → Notion 계층 배포
    mapping.py           # 페이지 매핑 (idempotent 배포)
    resolver.py          # 크로스 링크 해결
    forms.py             # 폼/템플릿 처리
    mcp_server.py        # 선택적 Notion 내부 API MCP
    ai_models.py         # 라이브 모델·추론 레벨 검증/메타데이터 선택
    context_files.py     # descriptor 기반 bounded/no-follow 읽기
    local_context.py     # 읽기 범위·지침·검색·마스킹
    local_context_mcp.py # 인증된 읽기 전용 역방향 MCP
    local_context_runtime.py # fixture/실제 루트 브로커·터널 실행기
    session_pool.py      # 독립 작업·시도·결과 상관관계/복구
    session_store.py     # private revision checkpoint 저장
    desktop_session_cli.py # JSON 실행 전달·결과 조회
  scripts/
    notion-desktop-adapter.mjs # 주입형 UI 어댑터 (실제 pool 연결은 잔여)
  tests/
    test_internal.py              # 내부 API·모델·스트림 회귀
    test_internal_integration.py  # 내부 API integration 테스트 (18개)
    test_local_context*.py        # 경로·인증·런타임·loopback 회귀
    test_session*.py              # 세션·checkpoint·복구 회귀
    notion-desktop-adapter.test.mjs # 합성 UI 회귀
    test_*.py                     # 기타 Python 회귀
  docs/
    internal-api-capture.md       # 90+ 내부 API 캡처 문서
    notion-toolkit-guidelines.md  # 운영 가이드
```
