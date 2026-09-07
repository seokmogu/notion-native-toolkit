# notion-native-toolkit

Notion 공식 API와 내부 API를 하나의 Python SDK로 통합한 툴킷입니다.

## Notion AI 오케스트레이션

Codex는 작업 분해·로컬 적용·명령 실행·Git·검증을, Notion AI는 분석과 코드 제안을 맡습니다. 두 MCP는 호출 방향과 권한이 다릅니다.

| 구성 | 호출 방향 / 역할 | 상태 |
|---|---|---|
| `notion-mcp` | Codex 등 MCP 클라이언트 → Notion 내부 API. 모델 목록·AI 호출 등 | 선택적 비공식 기능. 공식 표면에 없는 승인된 용도에만 사용 |
| `local-context-mcp` | Notion AI → 맥북의 허용된 소스·지침 | 읽기 전용. 파일 생성·수정·삭제, 명령 실행, Codex 호출 도구 없음 |
| `local_context_runtime` | 전용 로컬 브로커와 cloudflared 시작·종료 | 기본 합성 fixture. 실제 고정 루트는 `--real-context` 필요 |
| `SessionPool` / `notion-desktop-session` | 독립 세션 예약, JSON 전달, private checkpoint·복구 | 로컬 계약 구현. 실제 다중 탭 자동 실행기는 미완료 |

`ai_models.py`는 최신 목록에서 활성 모델·지원 추론 레벨을 검증합니다. 잘못된 선택은 자동 대체하지 않습니다. AI 스트림의 HTTP/시간 초과/빈 응답/손상된 NDJSON을 오류로 처리하고, 지원되는 텍스트가 없을 때 원문 이벤트를 답변으로 반환하지 않습니다. 메타데이터 기반 선택은 모델별 분야 성능 벤치마크를 대신하지 않습니다.

### Notion에서 맥북 파일 읽기

개인 연결 `Local Mac Context (Private)`을 설정하고 맥북의 브로커·터널을 실행한 상태에서 Notion AI 채팅에 요청합니다.

> Local Mac Context (Private)의 `local-context_get_scope_manifest`를 실제 호출해서 현재 모드, 실제 프로젝트 루트와 프로젝트 후보 목록을 확인해줘. 이전 대화 내용으로 추측하지 마.

파일을 읽을 때는:

> 같은 연결의 `local-context_read_project_excerpt`로 `path="notion-native-toolkit/README.md"`, `start_line=1`, `end_line=100`을 읽어줘.

manifest 및 모든 MCP 성공 응답의 `scope`에서 모드와 실제 루트를 확인할 수 있습니다. 실제 모드는 `approved-projects`, 테스트는 `fixture`, 임의 주입 범위는 `custom`입니다. 파일 경로는 `project_root` 기준 **상대 경로**이며 `/project`는 입력 별칭이 아닙니다. `search_project`는 고정 문자열 검색이지 전체 파일 목록이 아닙니다.

현재 실제 모드의 고정 루트는 `/Users/seokmogu/project`입니다. `.codex`는 전역 `AGENTS.md`와 고정 allowlist의 `SKILL.md`만 제공합니다. 스킬의 도구·실행 권한·참고자료 전체가 Notion에 복제되는 것은 아닙니다.

### 접근 제한과 실행 조건

- 개인 OAuth → 전용 Cloudflare Service Auth → 별도 브로커 bearer를 사용하며 로컬 바인딩은 `127.0.0.1`입니다. 인증 설정이 없으면 HTTP 서버는 시작하지 않습니다.
- 숨김·credential·data/logs·dependency 경로와 링크/범위 이탈을 차단하고 읽기·검색·응답 크기를 제한합니다. `truncated`를 전체 결과로 해석하지 마세요.
- 마스킹은 보조 방어입니다. 허용된 소스 내부의 모든 개인정보·업무 기밀을 자동 분류하거나 차단하지는 않습니다.
- 토큰·쿠키·키·세션 checkpoint·실제 운영 연결 식별정보는 Git에 넣지 않습니다. `.notion-session-*`, `.notion-context-runtime-*`, `.private-evidence-*`는 로컬 비공개 자료입니다.
- 현재 런타임은 foreground 실행입니다. 맥북 재부팅 후 자동 시작은 미설정이며, 이 MCP가 Notion에서 Codex를 깨우거나 작업시키지는 않습니다.

### 구현과 검증 상태 — 2026-09-07

```sh
uv run --with pytest pytest -q -m 'not integration'
node --test tests/notion-desktop-adapter.test.mjs
uv lock --check --offline
```

| 검증층 | 확인한 결과 | 제외 범위 |
|---|---|---|
| 로컬 Python | 324 passed, 외부 integration 18개 제외 | 외부 서비스 E2E를 대신하지 않음 |
| Node 어댑터 | 합성 UI 회귀 20개 통과 | 실제 병렬 모델 호출 아님 |
| 실제 Notion 브라우저 | manifest·프로젝트 파일·전역 지침·스킬 도구 호출 및 소스 3개 해시 일치 | 코드 원문 무손실 회수·전체 자동 루프는 별도 |
| 접근 방어 | 원본 무인증 403, bearer 미제공/오류·Portal 무인증 401; loopback 테스트에서 잘못된 Host 421 | 타 계정 로그인·토큰 폐기 후 거부는 미검증 |

2~3개 in-flight 예약·불명확 전송 재시도 방지·영속 복구는 구현했습니다. 실제 다중 탭 자동 실행, 분야별 모델 라우팅 벤치마크, Notion 산출→로컬 실행 전체 루프는 아직 미완료입니다.

- [범위·실행·보안 안내](docs/local-context-broker.md)
- [JSON 세션 전달·복구](docs/desktop-session-handoff.md) / [세션 계약](docs/notion-desktop-sessions.md)
- [모델·추론 레벨 선택](docs/notion-ai-model-guide.md)
- [남은 작업](docs/remaining-work-plan.md) / [평가](docs/evaluation-2026-09-07.md) / [원격 연결 검증 기록](docs/cloudflare-setup-evidence-2026-09-07.md)

## 공식 우선 운영 원칙

워크스페이스 기준은 `/Users/seokmogu/project/NOTION_PUBLISHING.md`입니다. 대화형 검색·조회·부분 수정은 Hosted Notion MCP를 우선하고, 이 툴킷은 공식 enhanced Markdown/API 기반 batch·headless 작업과 hierarchy, mapping, child-page 보존, file upload, profile, 증적 기능을 보완합니다. 내부 API와 browser automation은 공식 표면에 없는 기능이 확인된 경우에만 사용합니다.

새로운 one-off Notion uploader를 만들거나 custom block writer를 기본 경로로 사용하지 않습니다. leaf page는 native Markdown을 우선하고, page title과 동일한 첫 H1 및 heading 직후 자동 empty paragraph를 생성하지 않습니다.

## 이 프로젝트가 필요한 이유

Notion의 공식 표면은 Hosted MCP, enhanced Markdown, 페이지·블록·데이터베이스 API를 제공합니다. 하지만 실제 업무 자동화에 필요한 일부 기능들—AI 실행, 고급 풀텍스트 검색, 게스트 초대, 워크스페이스 관리 등—은 공식 표면만으로 처리되지 않습니다.

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
| **브라우저 세션 동기화 (token_v2)** | - | O |

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

아래 SDK·CLI 예시는 해당 워크스페이스가 허용하는 인증과 승인된 쓰기 범위에서만 사용합니다. **Worxphere는 PAT를 허용하지 않으므로 `ntn login`/PAT로 우회하지 않고, 지원되는 작업은 인증된 Hosted Notion MCP를 사용합니다.** 로컬 컨텍스트 읽기 연결에는 이 SDK 프로필 초기화가 필요하지 않습니다.

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

CLI에서 Markdown을 Notion 페이지로 생성하거나 갱신할 때는 기본값으로 `blocks` 모드를 사용합니다. 이 모드는 Markdown 표를 Notion table block으로 변환하므로 표 구분선(`|---|`)이 본문 행으로 남는 문제를 피할 수 있습니다. Notion의 native Markdown endpoint가 꼭 필요할 때만 `--mode native`를 명시합니다.

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

### 3. 내부 API 사용

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

## 브라우저 세션 인증 (token_v2)

내부 API는 브라우저 세션 쿠키(`token_v2`)로 인증합니다. 현재 검증된 운영 경로는 실제 Chrome 원격 디버깅 세션에 붙어서 Notion Magic Link 메일을 열고, 그 세션을 Playwright storage state로 저장하는 방식입니다. 저장된 `.app.notion.com` 세션 토큰은 내부 API 인증에 사용할 수 있습니다.

### 권장 사용법

```bash
# 1) 원격 디버깅이 켜진 실제 Chrome에서 Gmail Magic Link 로그인
notion-native browser login \
  --profile worxphere \
  --gmail-env-file /path/to/.env \
  --cdp-url http://127.0.0.1:50061

# 2) 일반 Chrome 프로필 쿠키도 함께 동기화하고 내부 API 인증 확인
notion-native browser sync-chrome-cookies \
  --profile worxphere \
  --chrome-profile "Profile 1" \
  --validate-internal
```

`browser login --cdp-url`은 Gmail의 Notion 6자리 코드와 Magic Link 메일을 모두 처리합니다. `--validate-internal`은 `getVisibleUsers` read-only 내부 API를 호출해 저장된 `token_v2`가 실제로 유효한지 확인합니다. 결과의 `internal_api_authorized`가 `true`여야 내부 API integration 테스트가 실행됩니다.

### 자동 로그인 보조 경로

```python
from notion_native_toolkit.internal import NotionInternalClient

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

- 일반 Playwright Chromium 로그인은 Notion의 이메일 인증/봇 판정 정책에 따라 인증 메일이 발송되지 않을 수 있습니다. 이 경우 실제 Chrome CDP 경로를 사용하세요.
- 쿠키 만료일이 미래여도 Notion 내부 API가 `login_custom_session_expired`를 반환하면 세션은 만료된 것입니다.
- 수동으로 Notion에 다시 로그인한 뒤 `browser sync-chrome-cookies --validate-internal`을 재실행하세요.

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
  --mode blocks  # blocks, native, cli (기본: blocks)

# Notion 공식 CLI 경로로 Markdown 페이지 생성/수정
notion-native page create-from-markdown \
  --profile worxphere \
  --title "문서 제목" \
  --parent-page-id 0123456789abcdef \
  --file docs/spec.md \
  --mode cli

# 공식 ntn API 표면 캡처
notion-native api capture \
  --output-dir docs/notion-api-capture/current \
  --endpoint POST:v1/comments

# 공식 API 캡처 간 차이 확인
notion-native api diff \
  --old-dir docs/notion-api-capture/current \
  --new-dir docs/notion-api-capture/2026-06-23

# 공식 page/database raw API 사용
notion-native api fetch-page \
  --profile worxphere \
  --page-id 0123456789abcdef
notion-native api update-database \
  --profile worxphere \
  --database-id 0123456789abcdef \
  --payload database-update.json \
  --yes

# 공식 data source API 사용
notion-native api query-data-source \
  --profile worxphere \
  --data-source-id 0123456789abcdef

# 공식 file upload API 사용
notion-native api list-file-uploads \
  --profile worxphere \
  --status uploaded

# 공식 page move API 사용
notion-native api move-page \
  --profile worxphere \
  --page-id 0123456789abcdef \
  --parent-page-id fedcba9876543210 \
  --yes

# 공식 comments API 사용
notion-native api list-comments \
  --profile worxphere \
  --block-id 0123456789abcdef

# 공식 search/users/custom emoji/page property API 사용
notion-native api search \
  --profile worxphere \
  --query roadmap
notion-native api fetch-bot-user --profile worxphere
notion-native api list-views \
  --profile worxphere \
  --data-source-id 0123456789abcdef
notion-native api list-block-children \
  --profile worxphere \
  --block-id 0123456789abcdef

# 공식 ntn 인증/파일 업로드 상태 확인
notion-native cli whoami --profile worxphere
notion-native cli files-list --profile worxphere

# 단일 Markdown 파일이나 일반 child page 배포에 공식 CLI Markdown writer 사용
notion-native deploy docs/spec.md \
  --profile worxphere \
  --parent-page-id 0123456789abcdef \
  --backend cli
```

`deploy --backend cli`는 일반 Markdown page create/edit 경로에 `ntn pages create/edit`를 사용합니다. 디렉토리 배포의 컨테이너 페이지와 README landing은 child page 보존 로직 때문에 기존 `blocks` writer를 계속 사용합니다.

### 브라우저 자동화

```bash
# 필요 시 별도 Chrome 원격 디버깅 세션을 먼저 실행
/Applications/Google\ Chrome.app/Contents/MacOS/Google\ Chrome \
  --remote-debugging-port=50061 \
  --user-data-dir "$(mktemp -d)" \
  --no-first-run \
  --no-default-browser-check \
  --new-window about:blank

# 수동 Chrome 로그인 세션을 toolkit browser_state로 동기화
notion-native browser sync-chrome-cookies \
  --profile worxphere \
  --chrome-profile "Profile 1" \
  --validate-internal

# 실제 Chrome CDP 세션으로 로그인. Gmail Magic Link와 6자리 코드를 모두 처리
notion-native browser login \
  --profile worxphere \
  --gmail-env-file /path/to/.env \
  --cdp-url http://127.0.0.1:50061

# 새 Chromium으로 로그인 시도 (Notion이 인증 메일을 발송하지 않을 수 있음)
notion-native browser login --profile worxphere --headed

# Notion 이메일 인증이 필요하면 Gmail readonly token 파일로 자동 처리
notion-native browser login \
  --profile worxphere \
  --gmail-env-file /path/to/.env \
  --gmail-token-file /path/to/gmail_token.json \
  --gmail-user you@worxphere.ai

# 팀스페이스 목록 조회
notion-native browser list-teamspaces --profile worxphere

# 팀스페이스 생성
notion-native browser create-teamspace --profile worxphere --name "새 팀"
```

`--gmail-token-file`은 Gmail API `gmail.readonly` authorized-user JSON입니다.
`NOTION_GMAIL_TOKEN_FILE`/`GMAIL_TOKEN_FILE`과 `NOTION_GMAIL_USER`/`GMAIL_USER`
환경변수도 지원합니다.
`--gmail-env-file`은 `GMAIL_*`/`NOTION_GMAIL_*` 값만 로드합니다.
Gmail API 호출에 quota project가 필요한 환경에서는 `GMAIL_QUOTA_PROJECT`도 같은 env 파일에 둡니다.
`browser sync-chrome-cookies --validate-internal`의 `internal_api_authorized`가
`false`이면 쿠키는 추출됐지만 Notion 내부 API가 세션을 만료 처리한 상태입니다.

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

# Integration 테스트 전 Chrome 세션 동기화 및 내부 API 인증 확인
notion-native browser sync-chrome-cookies --profile worxphere --validate-internal

# Integration 테스트 (실제 Notion 내부 API read 호출, 유효한 token_v2 필요)
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
| `run_ai(prompt, block_id, model, reasoning_effort)` | AI 실행 (ndjson 스트리밍), 모델·추론 레벨 선택 가능 |
| `get_available_models()` | 사용 가능한 AI 모델 |
| `get_ai_usage()` | AI 크레딧 사용량/한도 |
| `get_custom_agents()` | 커스텀 AI 에이전트 |
| `get_ai_connectors()` | AI 커넥터 (Slack, Calendar 등) |
| `get_user_prompts()` | 저장된 프롬프트 |

현재 조회된 모델 코드와 선택 지침은
[`docs/notion-ai-model-guide.md`](docs/notion-ai-model-guide.md)에 정리되어
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
# 프로필 기반 사용 권장
export NOTION_PROFILE='worxphere'

# 프로필에 space_id가 없을 때만 필요
export NOTION_SPACE_ID='xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'

# 아래 중 하나 선택:

# (A) 프로필 browser_state_path 자동 로드 (권장)
notion-native browser sync-chrome-cookies --profile worxphere --validate-internal

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
        "NOTION_PROFILE": "worxphere"
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
        "NOTION_PROFILE": "worxphere"
      }
    }
  }
}
```

### 인증 우선순위

1. `NOTION_TOKEN_V2` 환경변수 (명시 지정)
2. `NOTION_PROFILE` / `NOTION_NATIVE_PROFILE`의 `browser_state_path`
3. `NOTION_BROWSER_STATE_PATH` (Playwright storage state JSON)
4. `~/.chrome-automation-profile/cookies.json` (레거시 Playwright 동기화)
5. `NOTION_COOKIES_PATH` 환경변수로 레거시 쿠키 파일 경로 커스텀 가능

### 인증 트러블슈팅

| 증상 | 원인 | 해결 |
|------|------|------|
| `Notion 인증을 찾을 수 없습니다` | token_v2 없음 | 아래 "token_v2 획득 방법" 참조 |
| `NOTION_SPACE_ID가 설정되지 않았습니다` | 환경변수 누락 | `export NOTION_SPACE_ID='...'` 설정 |
| `HTTP 401` / `HTTP 403` | token_v2 만료 (약 1년 유효) | 브라우저에서 Notion 재로그인 후 쿠키 재동기화 |
| `HTTP 429` | Rate limit | 자동 재시도됨 (최대 3회). 빈번하면 `rate_limit` 값 증가 |
| `Search failed` / `None` 응답 | space_id 불일치 또는 세션 만료 | `sync-chrome-cookies --validate-internal` 결과 확인 |
| `Stream HTTP 4xx on runInferenceTranscript` | AI 크레딧 소진 또는 플랜 미지원 | `notion_ai_usage` 도구로 잔여 크레딧 확인 |

**token_v2 획득 방법:**

```bash
# 방법 1: 수동 Chrome 로그인 세션 동기화 (권장)
notion-native browser sync-chrome-cookies \
  --profile worxphere \
  --validate-internal

# 방법 2: 자동 로그인 보조 경로
notion-native browser login --profile worxphere --headed

# 방법 3: Chrome DevTools
# 1) Chrome에서 notion.so 접속
# 2) F12 → Application → Cookies → notion.so
# 3) token_v2 값 복사
# 4) export NOTION_TOKEN_V2='복사한값'
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

# MCP에서 모델·추론 레벨 지정
notion_ai_ask(
    prompt="복잡한 정책을 분석해줘",
    model="<get_available_models()의 model 코드>",
    reasoning_effort="high",
)

# "Gemini 모델로 요약해줘" 같은 자연어도 가능 — Claude가 키워드 트리거로 자동 호출
"notion ai로 이 문서 요약해줘"
```

### MCP vs 스킬 선택 가이드

| 상황 | 추천 |
|------|------|
| 대화형 Notion 검색·fetch·부분 수정 | Hosted Notion MCP (`https://mcp.notion.com/mcp`) |
| Markdown batch/headless create·update | `notion-native` official Markdown/native mode |
| hierarchy·mapping·child/file 보완 | `/notion-native-toolkit` 또는 Python package |
| Notion AI/usage 등 공식 표면에 없는 명시 기능 | opt-in `notion-internal` MCP |

이 저장소의 `notion-internal` MCP는 Hosted Notion MCP의 대체재가 아닙니다. 전역 또는 일반 프로젝트 설정에 기본 등록하지 않습니다.

## 참고 사항

- 프로젝트별 비즈니스 로직은 해당 프로젝트에, Notion I/O는 이 툴킷에 유지하세요.
- 비밀 정보는 절대 코드에 커밋하지 마세요. 환경 변수 또는 Keychain을 사용하세요.
- 내부 API 엔드포인트는 비공식이며 사전 고지 없이 변경될 수 있습니다. Integration 테스트가 변경을 감지합니다.
- 브라우저 셀렉터는 Notion UI 변경 시 업데이트가 필요할 수 있습니다.
- 전체 내부 API 엔드포인트 문서: `docs/internal-api-capture.md`
