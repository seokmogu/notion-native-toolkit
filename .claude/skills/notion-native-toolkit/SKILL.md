---
name: notion-native-toolkit
description: >
  Notion 통합 툴킷 - 공식 API, ntn 공식 CLI 표면, 내부 API(AI/검색/사용량),
  브라우저 자동화, Markdown 변환을 제공합니다. Notion AI 호출, 모델 조회,
  크레딧 확인, 워크스페이스 검색, 공식 API 캡처/비교, Markdown 페이지 배포에 사용하세요.
allowed-tools: Read, Bash, Grep, Glob
metadata:
  version: "0.2.0"
  category: "domain"
  status: "active"
  updated: "2026-06-24"
  tags: "notion, ai, search, mcp, internal-api, ntn, official-api"
triggers:
  keywords: ["notion ai", "notion 검색", "notion search", "notion 모델", "notion 크레딧", "notion usage", "notion-native", "notion api", "ntn", "notion 배포"]
---

# notion-native-toolkit

Notion 공식 API + 내부 API(v3) 통합 Python 툴킷.

## 설치

아래 중 한 가지 방법으로 설치합니다.

```bash
# (A) 패키지 설치 (권장) — notion-native / notion-mcp CLI가 PATH에 등록됩니다
uv tool install notion-native-toolkit
# 또는: pipx install notion-native-toolkit / pip install notion-native-toolkit

# (B) 소스 체크아웃에서 실행 — 설치 없이 바로 쓸 때
git clone https://github.com/seokmogu/notion-native-toolkit.git
export NNT_DIR="$PWD/notion-native-toolkit"   # 체크아웃 경로
```

아래 예제는 `uv run --directory "$NNT_DIR" ...` 형태를 사용합니다.
`NNT_DIR`을 본인이 설치/체크아웃한 notion-native-toolkit 경로로 설정하거나,
패키지 설치(A) 후에는 `uv run --directory "$NNT_DIR"` 부분을 빼고 `python -c "..."`만 실행해도 됩니다.

## 환경 설정

내부 API를 쓰려면 워크스페이스 ID와 인증 토큰이 필요합니다.
`.envrc`, `.env`, 또는 쉘에서 본인 워크스페이스 값으로 설정하세요.

```bash
# 필수 — 본인 Notion 워크스페이스 ID
# Notion 데스크톱/웹에서 Settings → 워크스페이스 또는 URL에서 확인
export NOTION_SPACE_ID='<your-space-id>'      # 예: xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx

# 인증 — 아래 중 하나 (우선순위 순)
# 1) NOTION_TOKEN_V2 환경변수로 직접 지정
export NOTION_TOKEN_V2='<your-token_v2-cookie>'
export NOTION_USER_ID='<your-notion-user-id>'   # 선택

# 2) (미설정 시) ~/.chrome-automation-profile/cookies.json 에서 token_v2 자동 로드
#    Playwright 쿠키 동기화를 쓰면 별도 설정 불필요

# 3) NOTION_COOKIES_PATH 로 쿠키 파일 경로 커스텀
export NOTION_COOKIES_PATH='<path-to-cookies.json>'
```

> 실제 토큰/스페이스 ID는 코드나 문서에 하드코딩하지 말고 환경변수 또는 macOS Keychain으로 관리하세요.

## Notion AI 호출

사용법: `/notion-native-toolkit <프롬프트>`

```bash
uv run --directory "$NNT_DIR" python -c "
import json, os
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
user_id = next((c['value'] for c in cookies if c['name'] == 'notion_user_id' and 'notion.so' in c.get('domain','')), None)
space_id = os.environ['NOTION_SPACE_ID']

with NotionInternalClient(token_v2=token, space_id=space_id, user_id=user_id) as cli:
    for chunk in cli.run_ai('$ARGUMENTS'):
        for v in chunk.get('v', []):
            if v.get('o') in ('a','x') and '/value/' in v.get('p','') and 'content' in v.get('p',''):
                if isinstance(v.get('v'), str): print(v['v'], end='')
            elif v.get('o') == 'a' and isinstance(v.get('v'), dict) and v['v'].get('type') == 'agent-inference':
                for p in v['v'].get('value', []):
                    if isinstance(p, dict) and 'content' in p: print(p['content'], end='')
    print()
"
```

## AI 모델 목록

`/notion-native-toolkit models` 또는 자연어로 "notion ai 모델 목록" 요청

```bash
uv run --directory "$NNT_DIR" python -c "
import json, os
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
space_id = os.environ['NOTION_SPACE_ID']

with NotionInternalClient(token_v2=token, space_id=space_id) as cli:
    models = cli.get_available_models()
    for m in (models or {}).get('models', []):
        print(f\"{m.get('modelMessage','?'):20s} [{m.get('modelFamily','?'):10s}] code={m.get('model','?')}\")
"
```

## AI 크레딧 사용량

```bash
uv run --directory "$NNT_DIR" python -c "
import json, os
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
space_id = os.environ['NOTION_SPACE_ID']

with NotionInternalClient(token_v2=token, space_id=space_id) as cli:
    print(json.dumps(cli.get_ai_usage(), indent=2, ensure_ascii=False))
"
```

## 워크스페이스 검색

```bash
uv run --directory "$NNT_DIR" python -c "
import json, os
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
space_id = os.environ['NOTION_SPACE_ID']

with NotionInternalClient(token_v2=token, space_id=space_id) as cli:
    result = cli.search('$ARGUMENTS', limit=10)
    for r in (result or {}).get('results', []):
        print(f\"- {r.get('highlight',{}).get('text', r.get('id','?'))} (id: {r.get('id','?')})\")
"
```

## 기존 CLI 기능

```bash
notion-native profile init
notion-native profile add my-workspace --workspace-url https://www.notion.so/my-workspace
notion-native profile set-token my-workspace --value "ntn_xxx" --keychain
notion-native page create-from-markdown --profile my-workspace --title "제목" --parent-page-id PAGE_ID --file doc.md

# 권장: 사용자가 일반 Chrome에서 Notion에 로그인한 뒤 세션 쿠키를 toolkit state로 동기화
notion-native browser sync-chrome-cookies \
  --profile my-workspace \
  --validate-internal

# 보조: 자동화 브라우저 로그인 시도
notion-native browser login --profile my-workspace --headed

# 권장: 실제 Chrome CDP 세션으로 Notion Magic Link/6자리 코드 메일 처리
notion-native browser login \
  --profile my-workspace \
  --gmail-env-file /path/to/.env \
  --gmail-token-file /path/to/gmail_token.json \
  --gmail-user you@worxphere.ai \
  --cdp-url http://127.0.0.1:50061
```

## 공식 API / ntn 연동

`ntn`이 설치되어 있으면 공식 CLI의 API index/docs/spec와 Markdown writer를 래핑할 수 있습니다.
토큰이 있는 프로필은 `NOTION_API_TOKEN`으로 `ntn`에 전달됩니다.

```bash
# 공식 API 표면 캡처 및 drift 확인
notion-native api capture \
  --output-dir docs/notion-api-capture/current \
  --endpoint POST:v1/comments

notion-native api diff \
  --old-dir docs/notion-api-capture/current \
  --new-dir docs/notion-api-capture/current

# 공식 CLI Markdown writer 사용
notion-native page create-from-markdown \
  --profile my-workspace \
  --title "제목" \
  --parent-page-id PAGE_ID \
  --file doc.md \
  --mode cli

# 공식 API raw page/database 호출
notion-native api fetch-page --profile my-workspace --page-id PAGE_ID
notion-native api fetch-database --profile my-workspace --database-id DATABASE_ID
```

Native client는 공식 최신 API가 필요한 page/database create·retrieve·update,
`data_sources`, blocks, comments, views, search/users/custom emoji/page property,
file uploads, page move, Markdown page IO를 요청별 `2026-03-11` 헤더로 호출합니다.
기존 `query_database()`는 호환성 때문에 legacy 세션 버전을 유지합니다.

## 쓰기 안전 게이트

Notion 상태를 바꾸는 CLI 명령은 명시적인 `--yes` 없이는 실행하지 않습니다.
대상 페이지/DB와 payload를 확인한 뒤에만 사용하세요.

```bash
notion-native api update-page \
  --profile my-workspace \
  --page-id PAGE_ID \
  --payload page-update.json \
  --yes

notion-native api move-page \
  --profile my-workspace \
  --page-id PAGE_ID \
  --parent-page-id PARENT_PAGE_ID \
  --yes
```

## 검증

```bash
uv run --with pytest pytest tests -q -m 'not integration'
uv run --with ruff ruff check src tests/test_api_capture.py tests/test_client.py tests/test_deploy.py tests/test_ntn.py tests/test_toolkit.py
uv run python -m compileall -q src tests
```

전체 `pytest tests -q`는 `tests/test_internal_integration.py`가 실제 Notion 내부 API를 읽습니다.
Chrome `token_v2`가 없거나 만료되면 integration 테스트는 skip되어야 합니다.
먼저 `notion-native browser sync-chrome-cookies --profile <profile> --validate-internal`을 실행해
`internal_api_authorized`가 `true`인지 확인하세요.
실제 Notion 쓰기 기능은 별도 승인된 테스트 페이지/DB에서만 확인하세요.
브라우저 로그인은 `--gmail-token-file` 또는 `NOTION_GMAIL_TOKEN_FILE`/`GMAIL_TOKEN_FILE`로
Gmail API `gmail.readonly` authorized-user JSON을 받아 Notion 6자리 인증 코드 또는 Magic Link를 자동 처리할 수 있습니다.
`--gmail-env-file`은 `GMAIL_*`/`NOTION_GMAIL_*` 값만 로드하며, quota project가 필요하면 `GMAIL_QUOTA_PROJECT`도 포함하세요.
일반 Playwright Chromium에서 인증 메일이 오지 않으면 실제 Chrome 원격 디버깅 세션을 띄우고
`browser login --cdp-url http://127.0.0.1:<port>`를 사용하세요.

## 인증 트러블슈팅

| 증상 | 해결 |
|------|------|
| token_v2 없음 | Chrome에서 Notion 수동 로그인 후 `browser sync-chrome-cookies --validate-internal` 실행 |
| 401/403 | token_v2 만료 → 브라우저 재로그인 후 쿠키 재동기화 및 `internal_api_authorized` 확인 |
| NOTION_SPACE_ID 없음 | Notion Settings에서 space ID 복사 후 환경변수 설정 |

## Rules

- 비밀 정보는 환경 변수 또는 macOS Keychain 사용
- 프로젝트별 비즈니스 로직은 해당 프로젝트에 유지
- 공식 API 우선, 브라우저 자동화는 미지원 기능에만 사용
