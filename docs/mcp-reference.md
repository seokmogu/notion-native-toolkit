# MCP 클라이언트 연결

이 문서는 선택적 notion-internal 연결을 설명한다. Notion에서 맥북을 읽는 반대 방향 연결은 [Local Context Broker](local-context-broker.md)를 따른다. 두 서버의 권한을 혼동하지 않는다.

[문서 목록](README.md) · [프로젝트 소개](../README.md)

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
| `HTTP 401` / `HTTP 403` | 세션 만료 또는 접근 거부 | 브라우저에서 Notion 재로그인 후 쿠키 재동기화 |
| `HTTP 429` | Rate limit | 일반 `_post`는 최대 3회 재시도. AI 스트림은 자동 재시도하지 않음. MCP에는 rate_limit 설정 옵션이 없음 |
| `Search failed` / `None` 응답 | space_id 불일치 또는 세션 만료 | `sync-chrome-cookies --validate-internal` 결과 확인 |
| `Notion AI stream request failed with HTTP ...` | 권한/세션/요청/크레딧 등의 가능성; 상태 코드만으로 확정하지 않음 | `notion_ai_usage` 도구로 잔여 크레딧 확인 |

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

이 저장소는 Claude Code 스킬 파일이나 설치기를 배포하지 않습니다. 아래 슬래시 커맨드는 사용자가 별도 스킬을 설치·구성한 환경의 예시이며, 패키지 설치만으로 동작하지 않습니다.

### 설치

현재 저장소에는 `.claude/skills/notion-native-toolkit/SKILL.md`가 없습니다. 클라이언트의 스킬 설치 규칙에 맞춰 별도 구성해야 하며, 배포되는 기능은 위 MCP 진입점입니다.

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
