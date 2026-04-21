# notion-native-toolkit

Notion 공식 API와 내부 API를 하나의 Python SDK로 통합한 툴킷입니다.

## 이 프로젝트가 필요한 이유

Notion의 공식 API(v1)는 페이지, 블록, 데이터베이스 등 기본 CRUD만 제공합니다. 하지만 실제 업무 자동화에 필요한 기능들 - AI 실행, 풀텍스트 검색, 게스트 초대, 워크스페이스 관리 등은 공식 API에 없습니다.

이 툴킷은 Notion의 **내부 API(v3)**를 분석하여 SDK로 제공합니다. 90+ 내부 엔드포인트를 캡처/검증했으며, integration test로 API 변경을 감지합니다.

### 공식 API vs 내부 API 비교

| 기능 | 공식 API (v1) | 내부 API (v3) |
|------|:---:|:---:|
| 페이지/블록 CRUD | O | O |
| 데이터베이스 쿼리 | O | O |
| 마크다운 읽기/쓰기 | O | - |
| 댓글 | O | - |
| 파일 업로드 | O | - |
| **풀텍스트 검색 (필터/정렬/부스팅)** | - | O |
| **AI 실행 (스트리밍)** | - | O |
| **AI 모델/크레딧/에이전트 관리** | - | O |
| **사용자 검색 (이름/이메일)** | - | O |
| **팀/권한 그룹 관리** | - | O |
| **게스트 초대 플로우** | - | O |
| **워크스페이스 사용량/분석** | - | O |
| **트랜잭션 기반 쓰기 (행 생성 등)** | - | O |
| **페이지 백링크 조회** | - | O |
| **언어 감지** | - | O |
| **Integration/봇 관리** | - | O |
| **자동 로그인 (token_v2 발급)** | - | O |

## 아키텍처

```
NotionToolkit.from_profile("worxphere")
  ├─ .client     → NotionApiClient          공식 API v1 (Bearer 토큰, api.notion.com)
  ├─ .internal   → NotionInternalClient      내부 API v3 (token_v2 쿠키, notion.so/api/v3/)
  ├─ .browser    → NotionBrowserAutomation   Playwright 브라우저 폴백
  └─ .writer     → NotionWriter              마크다운 → Notion 블록 변환
```

### 인증 방식 차이

| | 공식 API | 내부 API |
|---|---|---|
| 인증 방식 | Bearer 토큰 (OAuth) | token_v2 쿠키 (브라우저 세션) |
| 베이스 URL | `https://api.notion.com/v1/` | `https://www.notion.so/api/v3/` |
| 토큰 발급 | Notion Integration 생성 | 로그인 (이메일/비밀번호) |
| 토큰 만료 | 무제한 (수동 폐기) | ~1년 (자동 갱신 가능) |

## 설치

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
playwright install chromium  # 브라우저 자동화 및 로그인에 필요
```

다른 프로젝트에서 사용할 때:

```bash
pip install notion-native-toolkit

# 또는 editable 설치 (개발 시)
pip install -e /path/to/notion-native-toolkit
```

## 빠른 시작

### 1. 프로필 설정

```bash
# 설정 파일 초기화
notion-native profile init

# 워크스페이스 프로필 추가
notion-native profile add worxphere \
  --workspace-url https://www.notion.so/worxphere \
  --parent-page-id 0123456789abcdef0123456789abcdef

# 공식 API 토큰 저장 (macOS Keychain)
notion-native profile set-token worxphere --value "ntn_xxx" --keychain

# 브라우저 로그인 정보 저장
notion-native profile set-browser-login worxphere \
  --email user@example.com \
  --password "password" \
  --keychain
```

### 2. 공식 API 사용

```python
from notion_native_toolkit import NotionToolkit

toolkit = NotionToolkit.from_profile("worxphere")

# 페이지 조회
page = toolkit.client.fetch_page("page-id")

# 데이터베이스 쿼리
rows = toolkit.client.query_database("db-id", {
    "filter": {"property": "Status", "status": {"equals": "Done"}}
})

# 마크다운으로 페이지 생성
toolkit.client.create_page_markdown(
    parent_page_id="parent-id",
    title="새 문서",
    markdown="# 제목\n\n본문 내용입니다.",
)

# 마크다운 읽기
md = toolkit.client.retrieve_markdown("page-id")

# 파일 업로드
upload = toolkit.client.create_file_upload("report.pdf")
toolkit.client.send_file_upload(upload["id"], "report.pdf", file_bytes)
```

### 3. 내부 API 사용

```python
from notion_native_toolkit.internal import NotionInternalClient

# 방법 A: 자동 로그인으로 token_v2 발급
creds = NotionInternalClient.login(
    email="user@example.com",
    password="password",
    space_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
)
client = NotionInternalClient(
    token_v2=creds["token_v2"],
    space_id=creds["space_id"],
    user_id=creds["user_id"],
)

# 방법 B: 프로필에 token_v2 설정 후 toolkit에서 사용
toolkit = NotionToolkit.from_profile("worxphere")
client = toolkit.require_internal()
```

#### 검색

```python
# 풀텍스트 검색 (공식 API의 제목 검색보다 강력)
results = client.search("회의록", limit=20)
# → results["results"]: 매칭된 블록 목록
# → results["total"]: 전체 매칭 수
# → results["recordMap"]: 관련 레코드

# 필터를 사용한 검색
results = client.search("프로젝트", limit=10, filters={
    "isDeletedOnly": False,
    "navigableBlockContentOnly": True,
    "requireEditPermissions": True,
    "ancestors": [],
    "createdBy": [],
    "editedBy": [],
    "inTeams": [],
    "contentStatusFilter": "all_without_archived",
})
```

#### 사용자/멤버 관리

```python
# 이름 또는 이메일로 사용자 검색 (게스트 초대에 활용)
users = client.list_users_search("kim")
# → users["users"]: [{id, name, email, membership_type, ...}]

# 이메일로 사용자 조회 (외부 사용자)
user = client.find_user("guest@external.com")

# 워크스페이스 전체 사용자 목록
all_users = client.get_visible_users()

# 팀 목록
teams = client.get_teams()
# → teams["teams"]: [{id, name, members, ...}]

# 권한 그룹 및 멤버 수
groups = client.get_permission_groups()

# 내부 이메일 도메인 목록
domains = client.get_internal_domains()
# → domains["internalDomains"]: ["company.com", "worxphere.ai"]

# 멤버 이메일 도메인
email_domains = client.get_member_email_domains()
```

#### AI

```python
# 사용 가능한 AI 모델 확인
models = client.get_available_models()
# → models["models"]: ["gpt-4", "claude", ...]

# AI 크레딧 사용량/한도 조회
usage = client.get_ai_usage()
# → usage["usage"], usage["limits"], usage["basicCredits"], usage["premiumCredits"]

# 커스텀 AI 에이전트 목록
agents = client.get_custom_agents()
# → agents["agentIds"]: ["agent-1", "agent-2"]

# AI 커넥터 (Slack, Calendar 등) 조회
connectors = client.get_ai_connectors()
# → connectors["connectedConnectors"], connectors["availableConnectors"]

# 저장된 AI 프롬프트
prompts = client.get_user_prompts()

# AI 실행 (ndjson 스트리밍 응답)
for chunk in client.run_ai("이 페이지를 요약해줘", block_id="page-id"):
    print(chunk)
    # 각 chunk는 AI 응답의 일부 (토큰 단위)
```

#### 콘텐츠

```python
# 페이지 전체 콘텐츠 로드 (내부 chunked loader)
page_data = client.load_page_chunk("page-id")
# → page_data["recordMap"]: 페이지 내 모든 블록 레코드

# 이 페이지를 참조하는 다른 페이지 (백링크)
backlinks = client.get_backlinks("page-id")
# → backlinks["backlinks"]: [{id, ...}]

# 페이지 언어 감지
lang = client.detect_language("page-id")
# → lang["detectedLanguage"]: "ko"
```

#### 쓰기 (트랜잭션)

Notion의 모든 쓰기 작업은 트랜잭션 기반입니다. 두 가지 엔드포인트가 있습니다:

- `save_transactions()` — 구조적 변경 (행 생성, 속성 설정, 부모 변경)
- `save_transactions_fanout()` — 콘텐츠 변경 (텍스트 입력/삭제)

```python
# 데이터베이스에 새 행 추가 (편의 메서드)
row_id = client.create_db_row(
    collection_id="collection-id",
    properties={"title": [["새 항목"]]}
)

# 직접 트랜잭션 실행 (고급)
client.save_transactions([
    {
        "command": "set",
        "pointer": {"table": "block", "id": "block-id", "spaceId": "space-id"},
        "path": ["properties", "title"],
        "args": [["수정된 제목"]],
    }
])
```

#### 워크스페이스

```python
# 블록 사용량 통계
usage = client.get_space_usage()
# → usage["blockUsage"]: 12345

# 연결된 Integration/봇 목록
bots = client.get_bots()

# Integration 검색
integrations = client.search_integrations("slack")
```

#### 데이터베이스 자동화 (DB Automation)

Notion UI의 `⚡ 자동화` 기능을 내부 API로 생성/삭제합니다. 두 종류의 액션을 지원합니다.

```python
# 1) Webhook 자동화 — 트리거 시 HTTP POST
webhook_auto_id = client.create_database_webhook_automation(
    database_id="33f7d832-...",       # source DB (block id)
    webhook_url="https://hooks.slack.com/...",
    name="신규 신청 Slack 알림",
    trigger="pages_added",             # or "page_props_any"
)

# 2) Page-creation 자동화 — 트리거 시 다른 DB에 페이지 추가
#    config.values 중 title(simple text)만 현재 지원.
#    Select/Relation/People 매핑은 UI에서 추가 필요.
add_page_auto_id = client.create_database_add_page_automation(
    source_database_id="33f7d832-...",  # 트리거 DB
    target_database_id="33f7d832-...",  # 새 페이지가 만들어질 DB
    title_text="신규 신청 접수",         # 새 페이지 title 컬럼 고정 텍스트
    name="신청→관리 자동 연동",
    trigger="pages_added",
)

# 목록 조회
for a in client.list_database_automations("33f7d832-..."):
    print(a["id"], a.get("status"), a.get("action_ids"))

# 비활성화 (soft-delete — automation_ids 리스트에서 제거 + alive=false)
client.deactivate_database_automation(
    database_id="33f7d832-...",
    automation_id=webhook_auto_id,
)
```

내부적으로 `collectionSettingsAutomationsActions.createDatabaseAutomation`
payload를 그대로 사용하며, `automation` / `automation_action` / `collection`
테이블에 대한 `saveTransactionsFanout` 트랜잭션으로 생성·갱신합니다.
캡처 기록: `docs/automation-webhook-capture.json`,
`docs/automation-add-page-capture.json`.

## 자동 로그인 (token_v2 발급)

내부 API는 브라우저 세션 쿠키(`token_v2`)로 인증합니다. 이 SDK는 Playwright를 사용해 로그인을 자동화합니다.

### 로그인 플로우

```
1. getLoginOptions(email)
   → loginOptionsToken, challengeProvider: "hcaptcha"

2. hCaptcha 자동 통과 (headed Chrome에서 자동 해결)

3. loginWithEmail(email, password, challengeToken, loginOptionsToken)
   → Set-Cookie: token_v2=... (만료: ~1년)

4. authValidate()
   → 세션 검증 완료
```

### 사용법

```python
from notion_native_toolkit.internal import NotionInternalClient

# 로그인하여 token_v2 발급 (브라우저가 화면 밖에서 자동 실행)
creds = NotionInternalClient.login(
    email="user@example.com",
    password="password",
    space_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
)

# 발급된 자격 증명으로 클라이언트 생성
client = NotionInternalClient(
    token_v2=creds["token_v2"],   # ~1년 유효
    space_id=creds["space_id"],
    user_id=creds["user_id"],
)
```

### 주의사항

- `headed=True`(기본값)이어야 hCaptcha가 자동 통과됩니다.
- 입력 속도가 너무 빠르면 봇으로 판단하여 이메일 인증(`mustReverify`)이 필요할 수 있습니다. SDK는 사람과 유사한 속도로 입력합니다.
- token_v2는 약 1년간 유효합니다. 만료 시 `login()`을 다시 호출하면 됩니다.

## 프로필 설정

툴킷은 `~/.config/notion-native-toolkit/workspaces.json`에 프로필을 저장합니다.

### 설정 파일 구조

```json
{
  "default_profile": "worxphere",
  "profiles": {
    "worxphere": {
      "workspace_url": "https://www.notion.so/worxphere",
      "default_parent_page_id": "0123456789abcdef0123456789abcdef",
      "api_token": {
        "kind": "keychain",
        "service": "notion-native-toolkit",
        "account": "worxphere.api_token"
      },
      "space_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "user_id": "xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
      "token_v2": {
        "kind": "env",
        "variable": "NOTION_TOKEN_V2"
      },
      "browser_email": {
        "kind": "keychain",
        "service": "notion-native-toolkit",
        "account": "worxphere.browser_email"
      },
      "browser_password": {
        "kind": "keychain",
        "service": "notion-native-toolkit",
        "account": "worxphere.browser_password"
      },
      "browser_state_path": "~/.config/notion-native-toolkit/browser-state/worxphere.json"
    }
  }
}
```

### 자격 증명 저장 방식

| 방식 | 설정 | 용도 |
|------|------|------|
| macOS Keychain | `{"kind": "keychain", "service": "...", "account": "..."}` | 가장 안전, 로컬 개발용 |
| 환경 변수 | `{"kind": "env", "variable": "NOTION_TOKEN_V2"}` | CI/CD, 컨테이너 |
| 직접 값 | `{"kind": "value", "value": "ntn_xxx"}` | 테스트 전용 (비권장) |

## CLI 사용법

### 페이지 관리

```bash
# 마크다운에서 페이지 생성
notion-native page create-from-markdown \
  --profile worxphere \
  --title "문서 제목" \
  --parent-page-id 0123456789abcdef \
  --file docs/spec.md

# 페이지를 마크다운으로 변환
notion-native markdown from-page \
  --profile worxphere \
  --page https://www.notion.so/... \
  --output page.md

# 페이지 내용 마크다운으로 업데이트
notion-native page update-from-markdown \
  --profile worxphere \
  --page-id 0123456789abcdef \
  --file docs/spec.md \
  --mode blocks  # blocks 또는 markdown (기본: markdown)
```

### 브라우저 자동화

```bash
# 브라우저로 로그인 (API 미지원 기능용)
notion-native browser login --profile worxphere --headed

# 팀스페이스 목록 조회
notion-native browser list-teamspaces --profile worxphere

# 팀스페이스 생성
notion-native browser create-teamspace --profile worxphere --name "새 팀"
```

### 프로필 관리

```bash
# 프로필 초기화
notion-native profile init

# 프로필 추가
notion-native profile add team-a --workspace-url https://www.notion.so/team-a

# API 토큰 설정 (Keychain)
notion-native profile set-token team-a --value "ntn_xxx" --keychain
```

## 테스트

```bash
# 유닛 테스트 (mock, API 호출 없음, 빠름)
pytest tests/ -q -m "not integration"

# Integration 테스트 (실제 Notion API 호출, 쿠키 필요)
pytest tests/test_internal_integration.py -v

# 전체 테스트
pytest tests/ -v
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

## 내부 API 메서드 전체 목록

### 인증

| 메서드 | 설명 |
|--------|------|
| `NotionInternalClient.login(email, password)` | 브라우저 로그인 후 token_v2 발급 |

### 검색

| 메서드 | 설명 |
|--------|------|
| `search(query, limit, filters)` | 워크스페이스 풀텍스트 검색 |

### 사용자/멤버

| 메서드 | 설명 |
|--------|------|
| `list_users_search(query)` | 이름/이메일로 사용자 검색 |
| `find_user(email)` | 이메일로 외부 사용자 조회 |
| `get_visible_users()` | 워크스페이스 전체 사용자 |
| `get_teams()` | 팀 목록 |
| `get_internal_domains()` | 내부 이메일 도메인 |
| `get_member_email_domains()` | 멤버 이메일 도메인 |
| `get_permission_groups()` | 권한 그룹 및 멤버 수 |

### AI

| 메서드 | 설명 |
|--------|------|
| `run_ai(prompt, block_id)` | AI 실행 (ndjson 스트리밍) |
| `get_available_models()` | 사용 가능한 AI 모델 |
| `get_ai_usage()` | AI 크레딧 사용량/한도 |
| `get_custom_agents()` | 커스텀 AI 에이전트 |
| `get_ai_connectors()` | AI 커넥터 (Slack, Calendar 등) |
| `get_user_prompts()` | 저장된 프롬프트 |

### 콘텐츠

| 메서드 | 설명 |
|--------|------|
| `load_page_chunk(page_id)` | 페이지 전체 콘텐츠 로드 |
| `get_backlinks(block_id)` | 백링크 조회 |
| `detect_language(page_id)` | 페이지 언어 감지 |

### 쓰기 (트랜잭션)

| 메서드 | 설명 |
|--------|------|
| `save_transactions(operations)` | 구조적 쓰기 (행 생성, 속성 설정) |
| `save_transactions_fanout(operations)` | 콘텐츠 쓰기 (텍스트 편집) |
| `create_db_row(collection_id)` | DB 행 생성 (편의 메서드) |

### 워크스페이스

| 메서드 | 설명 |
|--------|------|
| `get_space_usage()` | 블록 사용량 통계 |
| `get_bots()` | Integration/봇 목록 |
| `search_integrations(query)` | Integration 검색 |

## 프로젝트 구조

```
notion-native-toolkit/
  src/notion_native_toolkit/
    __init__.py          # NotionToolkit 내보내기
    toolkit.py           # 프로필 기반 통합 진입점
    client.py            # 공식 API 클라이언트 (v1)
    internal.py          # 내부 API 클라이언트 (v3) + 자동 로그인
    browser.py           # Playwright 브라우저 자동화
    profiles.py          # 워크스페이스 프로필 관리
    credentials.py       # Keychain/환경변수 자격 증명
    cli.py               # CLI 인터페이스
    markdown.py          # 마크다운 ↔ Notion 블록 변환
    writer.py            # Notion 페이지 작성기
    deploy.py            # 디렉토리 → Notion 계층 배포
    mapping.py           # 페이지 매핑 (idempotent 배포)
    resolver.py          # 크로스 링크 해결
    forms.py             # 폼/템플릿 처리
    mcp_server.py        # MCP 서버 (Claude Code 연동)
  tests/
    test_internal.py              # 내부 API 유닛 테스트 (25개)
    test_internal_integration.py  # 내부 API integration 테스트 (18개)
    test_*.py                     # 기타 유닛 테스트 (81개)
  docs/
    internal-api-capture.md       # 90+ 내부 API 캡처 문서
    notion-toolkit-guidelines.md  # 운영 가이드
```

## MCP 서버 (Claude Code / AI 에이전트 연동)

Notion 내부 API를 [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) 서버로 제공합니다. Claude Code, Cursor 등 MCP 지원 도구에서 Notion AI, 검색, 사용량 조회를 바로 사용할 수 있습니다.

### 제공 도구

| Tool | 설명 |
|------|------|
| `notion_ai_models` | 워크스페이스에서 사용 가능한 AI 모델 목록 |
| `notion_ai_usage` | AI 크레딧 사용량 및 잔여량 |
| `notion_ai_ask` | Notion AI에 질문하고 응답 받기 (스트리밍) |
| `notion_ai_agents` | 워크스페이스 커스텀 AI 에이전트 목록 |
| `notion_ai_connectors` | AI 연동 목록 (Slack, Calendar 등) |
| `notion_search` | 워크스페이스 풀텍스트 검색 |

### 설정

**1단계: 환경변수 설정**

```bash
# 필수 - 워크스페이스 ID
export NOTION_SPACE_ID='xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'

# 아래 중 하나 선택:

# (A) cookies.json 자동 로드 (Playwright 쿠키 동기화 사용 시 - 권장)
# ~/.chrome-automation-profile/cookies.json 에서 token_v2 자동 추출
# 별도 설정 불필요

# (B) 환경변수 직접 지정
export NOTION_TOKEN_V2='<token_v2 쿠키값>'
export NOTION_USER_ID='<user_id 쿠키값>'   # 선택사항
```

**2단계: MCP 설정 (`.mcp.json` 또는 Claude Code settings)**

```json
{
  "mcpServers": {
    "notion-internal": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/notion-native-toolkit", "python", "-m", "notion_native_toolkit.mcp_server"],
      "env": {
        "NOTION_SPACE_ID": "your-space-id-here"
      }
    }
  }
}
```

또는 패키지 설치 후 CLI로 실행:

```json
{
  "mcpServers": {
    "notion-internal": {
      "command": "notion-mcp",
      "env": {
        "NOTION_SPACE_ID": "your-space-id-here"
      }
    }
  }
}
```

### 인증 우선순위

1. `NOTION_TOKEN_V2` 환경변수 (명시 지정)
2. `~/.chrome-automation-profile/cookies.json` (Playwright 동기화)
3. `NOTION_COOKIES_PATH` 환경변수로 쿠키 파일 경로 커스텀 가능

### 인증 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `Notion 인증을 찾을 수 없습니다` | token_v2 없음 | 아래 "token_v2 획득 방법" 참조 |
| `NOTION_SPACE_ID가 설정되지 않았습니다` | 환경변수 누락 | `export NOTION_SPACE_ID='...'` 설정 |
| `HTTP 401` / `HTTP 403` | token_v2 만료 (약 1년 유효) | 브라우저에서 Notion 재로그인 후 쿠키 재동기화 |
| `HTTP 429` | Rate limit | 자동 재시도됨 (최대 3회). 빈번하면 `rate_limit` 값 증가 |
| `Search failed` / `None` 응답 | space_id 불일치 | 올바른 워크스페이스 ID인지 확인 |
| `Stream HTTP 4xx on runInferenceTranscript` | AI 크레딧 소진 또는 플랜 미지원 | `notion_ai_usage` 도구로 잔여 크레딧 확인 |

**token_v2 획득 방법:**

```bash
# 방법 1: 자동 로그인 (권장)
notion-native login

# 방법 2: Chrome DevTools
# 1) Chrome에서 notion.so 접속
# 2) F12 → Application → Cookies → notion.so
# 3) token_v2 값 복사
# 4) export NOTION_TOKEN_V2='복사한값'

# 방법 3: Playwright 쿠키 동기화 스크립트 사용
# cookies.json이 자동 갱신되면 별도 작업 불필요
```

**space_id 확인 방법:**

```bash
# 방법 1: Notion Settings → ... (워크스페이스 이름 옆) → Copy space ID
# 방법 2: Chrome DevTools Network 탭에서 아무 API 호출의 spaceId 필드 확인
# 방법 3: notion-native 프로필에 이미 저장된 경우
cat ~/.config/notion-native-toolkit/workspaces.json | grep space_id
```

## Claude Code 스킬 사용법

MCP 서버 외에, Claude Code에서 슬래시 커맨드로 직접 호출할 수도 있습니다.

### 설치

`.claude/skills/notion-native-toolkit/SKILL.md`가 프로젝트에 포함되어 있으면 자동 인식됩니다.

### 사용 예시

```
# Notion AI에 질문
/notion-native-toolkit <space_id> 한국의 수도는?

# "Gemini 모델로 요약해줘" 같은 자연어도 가능 — Claude가 키워드 트리거로 자동 호출
"notion ai로 이 문서 요약해줘"
```

### MCP vs 스킬 선택 가이드

| 상황 | 추천 |
|------|------|
| Claude Code에서 빠르게 호출 | `/notion-native-toolkit` 스킬 |
| Cursor, Windsurf 등 다른 도구 사용 | MCP 서버 |
| 에이전트가 자동으로 Notion 도구 호출 | MCP 서버 (tool discovery) |
| space_id 고정 + 반복 작업 | MCP 서버 (env에 설정해두면 편함) |

## 참고 사항

- 프로젝트별 비즈니스 로직은 해당 프로젝트에, Notion I/O는 이 툴킷에 유지하세요.
- 비밀 정보는 절대 코드에 커밋하지 마세요. 환경 변수 또는 Keychain을 사용하세요.
- 내부 API 엔드포인트는 비공식이며 사전 고지 없이 변경될 수 있습니다. Integration 테스트가 변경을 감지합니다.
- 브라우저 셀렉터는 Notion UI 변경 시 업데이트가 필요할 수 있습니다.
- 전체 내부 API 엔드포인트 문서: `docs/internal-api-capture.md`
