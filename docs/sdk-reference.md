# SDK 레퍼런스

기존 README의 SDK 설명·예제·메서드 목록을 보존했다. 아래 예제는 승인된 프로필/페이지에만 사용하며, 별도 표시가 없으면 각각 독립 코드 조각이다. 클라이언트 설정은 [인증 안내](authentication.md)를 먼저 따른다.

응답 예시와 캡처 목록은 형식/기능 레퍼런스이며, 모든 외부 endpoint가 현재 워크스페이스에서 검증됐다는 뜻은 아니다. 이번 개편의 검증 범위는 [정합성 점검](readme-implementation-audit-2026-09-07.md)에 구분했다.

[문서 목록](README.md) · [프로젝트 소개](../README.md)

## 이 프로젝트가 필요한 이유

Notion의 공식 표면은 Hosted MCP, enhanced Markdown, 페이지·블록·데이터베이스 API를 제공합니다. 하지만 실제 업무 자동화에 필요한 일부 기능들—AI 실행, 고급 풀텍스트 검색, 게스트 초대, 워크스페이스 관리 등—은 공식 표면만으로 처리되지 않습니다.

이 툴킷은 Notion의 **내부 API(v3)**를 분석하여 SDK로 제공합니다. 과거 캡처 범위는 [내부 API 캡처 기록](internal-api-capture.md)에 있으며, 등록된 integration test는 해당 테스트가 다루는 API 변경을 감지합니다.

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
| **브라우저 세션 동기화 (token_v2)** | - | O |

## 아키텍처

```
NotionToolkit.from_profile("worxphere")
  ├─ .client     → NotionApiClient          공식 API v1 (Bearer 토큰, api.notion.com)
  ├─ .internal   → NotionInternalClient      내부 API v3 (token_v2 쿠키, notion.so/api/v3/)
  ├─ .cli        → NotionCliClient           선택적 외부 ntn 실행 파일 래퍼
  ├─ .browser    → NotionBrowserAutomation   Playwright 브라우저 폴백
  └─ .writer     → NotionWriter              마크다운 → Notion 블록 변환
```

### 인증 방식 차이

| | 공식 API | 내부 API |
|---|---|---|
| 인증 방식 | Bearer 토큰 (OAuth) | token_v2 쿠키 (브라우저 세션) |
| 베이스 URL | `https://api.notion.com/v1/` | `https://www.notion.so/api/v3/` |
| 토큰 발급 | Notion Integration 생성 | 로그인 (이메일/비밀번호) |
| 토큰 만료 | 발급 방식·공급자 정책에 따름 | 세션별로 다름. SDK 자동 갱신 기능 없음 |

## SDK 빠른 시작

### 공식 API 사용

```python
from notion_native_toolkit import NotionToolkit

toolkit = NotionToolkit.from_profile("worxphere")

# 페이지 조회
page = toolkit.client.fetch_page("page-id")
block = toolkit.client.fetch_block("block-id")
children = toolkit.client.fetch_children("block-id")

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
toolkit.client.move_page("page-id", parent_page_id="new-parent-page-id")
toolkit.client.create_comment_markdown(
    "확인했습니다.",
    parent_page_id="page-id",
)
results = toolkit.client.search({"query": "roadmap"})
users = toolkit.client.list_users()
emoji = toolkit.client.list_custom_emojis()
views = toolkit.client.list_views(data_source_id="data-source-id")
meeting_notes = toolkit.client.query_meeting_notes({"query": "weekly"})

# 파일 업로드
upload = toolkit.client.create_file_upload("report.pdf")
toolkit.client.send_file_upload(upload["id"], "report.pdf", file_bytes)
uploads = toolkit.client.list_file_uploads(status="uploaded")
```

CLI의 호환 기본값은 `blocks`입니다. 공식 Markdown 경로를 우선 사용하는 작업에는 `--mode native`를 명시합니다. `blocks`는 지원이 필요한 호환 작업에 사용하며 Markdown 표를 Notion table block으로 변환합니다. 페이지 생성·수정에는 `--yes`가 필요합니다.

Notion 공식 CLI(`ntn`)가 설치되어 있고 공식 Markdown 처리 경로를 그대로 쓰고 싶다면 `--mode cli`를 사용할 수 있습니다. 이 모드는 프로필 API 토큰을 `NOTION_API_TOKEN`으로 넘기며, 프로필 토큰이 없으면 `ntn` 자체 인증 상태와 환경변수에 위임합니다.

공식 API 기본 세션 버전은 legacy `2022-06-28`을 유지합니다. 다만 page/database create·retrieve·update, `data_sources`, Markdown page IO, file uploads처럼 현재 캡처된 신규 endpoint는 스펙 요구에 맞춰 요청별로 `2026-03-11` 헤더를 사용합니다. 전체 client 버전을 고정해야 할 때는 `NOTION_API_VERSION=YYYY-MM-DD` 또는 `NotionApiClient(..., notion_version="YYYY-MM-DD")`로 지정할 수 있습니다.

새 공식 API 표면을 점검할 때는 `NotionToolkit.from_profile("worxphere").cli.api_list()`, `.api_docs("v1/comments", method="POST")`, `.api_spec("v1/comments", method="POST")`처럼 `ntn api ls/docs/spec` 출력을 래퍼로 가져올 수 있습니다.
CLI에서는 `notion-native api capture --output-dir docs/notion-api-capture/current --endpoint POST:v1/comments`로 같은 캡처를 파일화합니다. 자세한 흐름은 `docs/official-api-capture.md`를 따릅니다.

공식 API의 `data_sources` 계열도 지원합니다. 기존 `query_database()`는 호환용으로 유지하고, 새 API는 `fetch_data_source()`, `query_data_source()`, `create_data_source()`, `update_data_source()`, `list_data_source_templates()`를 사용합니다. `ntn` 표면은 `NotionToolkit.from_profile("worxphere").cli.datasources_query(...)`와 `.cli.datasources_resolve(...)`로 래핑합니다.

페이지와 데이터베이스 create/retrieve/update는 공식 API 스펙에 맞춰 raw payload 중심으로 열어 두었습니다. SDK에서는 `create_page(payload)`, `update_page(page_id, payload)`, `fetch_database(database_id)`, `create_database(payload)`, `update_database(database_id, payload)`를 사용하고, CLI의 생성/수정 명령은 실제 Notion 상태를 바꾸므로 `--yes` 확인을 요구합니다.

파일 업로드 API는 `create_file_upload()`, `send_file_upload()`, `list_file_uploads()`, `fetch_file_upload()`, `complete_file_upload()`를 지원합니다. `complete_file_upload()`는 multipart 업로드 완료용이며, CLI에서는 `notion-native api complete-file-upload --profile worxphere --upload-id <id> --yes`처럼 명시 확인을 요구합니다.

페이지 이동 API는 `move_page(page_id, parent_page_id=...)` 또는 `move_page(page_id, parent_data_source_id=...)`로 사용합니다. CLI에서는 실제 Notion 상태를 바꾸는 동작이므로 `notion-native api move-page --profile worxphere --page-id <id> --parent-page-id <parent-id> --yes`처럼 명시 확인을 요구합니다.

댓글 API는 `list_comments(block_id)`, `fetch_comment(comment_id)`, `create_comment_markdown(...)`, `update_comment_markdown(...)`, `delete_comment(...)`를 지원합니다. 댓글 생성/수정/삭제 CLI는 실제 Notion 상태를 바꾸므로 `--yes` 확인을 요구합니다.

읽기 중심 공식 API도 확장했습니다. `search(payload)`, `list_users()`, `fetch_user()`, `fetch_bot_user()`, `list_custom_emojis()`, `fetch_page_property()`를 사용할 수 있고, CLI에서는 `notion-native api search/list-users/fetch-user/fetch-bot-user/list-custom-emojis/fetch-page-property`로 노출됩니다.

Views API는 raw payload 중심으로 지원합니다. `list_views()`, `create_view()`, `fetch_view()`, `update_view()`, `delete_view()`, `create_view_query()`, `fetch_view_query_results()`, `delete_view_query()`를 사용할 수 있으며, 생성/수정/삭제 CLI는 `--yes` 확인을 요구합니다.

Blocks API는 현재 공식 버전에 맞춰 `fetch_block()`, `fetch_children()`, `append_children()`, `update_block()`, `delete_block()`를 제공합니다. `query_meeting_notes(payload)`는 공식 meeting notes query endpoint를 raw payload로 호출합니다.

`ntn`의 운영성 명령도 일부 흡수했습니다. 프로필 토큰을 전달해 인증 상태를 확인하려면 `notion-native cli whoami --profile worxphere`, 파일 업로드 상태는 `notion-native cli files-get --profile worxphere --upload-id <id>` 또는 `notion-native cli files-list --profile worxphere`를 사용합니다. 페이지 휴지통 이동은 쓰기 동작이므로 `notion-native cli page-trash --profile worxphere --page-id <id> --yes`처럼 명시 확인을 요구합니다.

기존 페이지를 갱신하면서 Notion 페이지 제목도 함께 맞춰야 할 때는 `page update-from-markdown --title "문서 제목"`을 사용합니다.
파일의 첫 H1이 지정한 제목과 같으면 본문에서 자동으로 제거되어 Notion 페이지 제목과 본문 H1이 중복되지 않습니다.

### 내부 API 사용

```python
from notion_native_toolkit.internal import NotionInternalClient

# 방법 A: Chrome에서 수동 로그인한 세션을 동기화한 뒤 toolkit에서 사용
# notion-native browser sync-chrome-cookies --profile worxphere --validate-internal
toolkit = NotionToolkit.from_profile("worxphere")
client = toolkit.require_internal()

# 방법 B: token_v2를 직접 알고 있을 때 클라이언트 생성
client = NotionInternalClient(
    token_v2="token_v2_cookie_value",
    space_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
    user_id="xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx",
)
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
# → models["models"]: [{"model": "<internal-code>", "modelMessage": "<display-name>", ...}, ...]

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
    # 각 chunk는 파싱된 NDJSON 이벤트 dict이며 토큰 문자열이 아니다.

# 최종 텍스트가 필요한 MCP 클라이언트는 notion_ai_ask를 사용한다.

# 모델과 추론 레벨을 직접 선택
model_code = next(
    model["model"]
    for model in models["models"]
    if model.get("modelMessage") == "GPT-5.6 Sol"
)
for chunk in client.run_ai(
    "이 페이지를 요약해줘",
    model=model_code,              # get_available_models()의 model 코드
    reasoning_effort="high",     # none, minimal, low, medium, high, xhigh, max
):
    print(chunk)
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
# 지원 속성:
#   - title(simple text)
#   - selects(고정 옵션)
#   - source_refs(트리거 행 text/email 복사)
#   - formula_refs(트리거 행 People 복사)
#   - trigger_page_refs(트리거 페이지 자체를 Relation으로 연결)
# 지원 트리거:
#   - "pages_added" (기본)
#   - "page_props_any" (모든 속성 편집)
#   - "page_props_filtered" + prop_filters (특정 값으로 편집될 때만)
add_page_auto_id = client.create_database_add_page_automation(
    source_database_id="33f7d832-...",  # 트리거 DB
    target_database_id="33f7d832-...",  # 새 페이지가 만들어질 DB
    title_text="신규 신청 접수",
    selects={"hcOM": "신청중"},          # Select 고정값
    source_refs={                        # text/email 소스 복사
        "mU@q": ("]aja", "소속"),
        "_e:N": ("=L~s", "계정 이메일"),
    },
    formula_refs={                       # People 소스 복사
        "u|hV": ("<source_coll_id>", "{dV<", "대상자"),
    },
    trigger_page_refs=["Z_Ma"],          # 트리거 페이지를 Relation으로
    name="신청→관리 자동 연동",
    trigger="pages_added",
)

# 조건부 트리거 예: "현재 상태"가 "사용중"으로 변경될 때만 발화
cond_auto_id = client.create_database_add_page_automation(
    source_database_id="...", target_database_id="...",
    title_text="배정 이벤트",
    selects={"MM^g": "배정"},
    trigger="page_props_filtered",
    prop_filters=[{
        "property": "hcOM",
        "filter": {"operator": "enum_is", "value": [{"type":"exact", "value":"사용중"}]},
    }],
    name="상태 변경 → 이력 자동 기록",
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
| `run_ai(prompt, block_id, model, reasoning_effort)` | AI 실행 (ndjson 스트리밍), 모델·추론 레벨 선택 가능 |
| `get_available_models()` | 사용 가능한 AI 모델 |
| `get_ai_usage()` | AI 크레딧 사용량/한도 |
| `get_custom_agents()` | 커스텀 AI 에이전트 |
| `get_ai_connectors()` | AI 커넥터 (Slack, Calendar 등) |
| `get_user_prompts()` | 저장된 프롬프트 |

현재 조회된 모델 코드와 선택 지침은
[`docs/notion-ai-model-guide.md`](notion-ai-model-guide.md)에 정리되어
있습니다. 모델 목록은 동적으로 바뀔 수 있으므로 실제 호출 전에는
`get_available_models()`를 다시 조회하세요.

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

## 참고 사항

- 프로젝트별 비즈니스 로직은 해당 프로젝트에, Notion I/O는 이 툴킷에 유지하세요.
- 비밀 정보는 절대 코드에 커밋하지 마세요. 환경 변수 또는 Keychain을 사용하세요.
- 내부 API 엔드포인트는 비공식이며 사전 고지 없이 변경될 수 있습니다. Integration 테스트가 변경을 감지합니다.
- 브라우저 셀렉터는 Notion UI 변경 시 업데이트가 필요할 수 있습니다.
- 전체 내부 API 엔드포인트 문서: `docs/internal-api-capture.md`
