# 인증과 프로필

로컬 컨텍스트 MCP의 개인 OAuth와 SDK의 API/브라우저 인증은 별개다. 인증자료를 argv·코드·로그·Git에 넣지 않는다. 기존 로그인과 승인된 프로필을 우선 재사용한다.

**Worxphere는 PAT를 허용하지 않는다.** 지원되는 조회/쓰기는 인증된 Hosted Notion MCP를 사용하며 CLI/PAT로 우회하지 않는다. 아래 SDK 예시는 해당 인증 경로를 허용하는 환경에서만 적용한다.

### 명시적으로 요청한 Notion AI

모델 목록·모델 지정 추론은 `notion_ai_models`와 `notion_ai_ask`가 제공하는 내부 MCP 기능이다. Hosted MCP의 지원 여부와 별도로 확인한다. 사용자가 Notion AI를 요청하거나 Notion 교차검토를 기본으로 선언한 워크플로를 명시적으로 호출했고, 워크스페이스 정책이 해당 기능을 허용하면 기존 내부 MCP와 인증된 프로필·브라우저 세션을 재사용한다. 같은 범위의 사용 허용을 다시 묻지 않는다.

이 범위는 AI 입력·응답에 한정된다. 새 로그인, credential 추출·복사·변경, CLI/PAT 전환, 페이지 게시나 허용 범위 밖 자료 전송을 포함하지 않는다. 아래 로그인·쿠키 동기화 예시는 AI 호출 요청만으로 실행하지 않는다. 추가 workspace/admin 금지 규칙은 그대로 적용한다.

인증·모델 접근이 실제로 실패하면 해당 호출만 미완료로 기록한다. 독립적으로 허용된 로컬 구현·검증은 계속하고 필수 외부 검토를 통과했다고 표시하지 않는다. 툴킷 자체의 점검·수정은 AI 호출 없이 로컬에서 수행할 수 있다.

[문서 목록](README.md) · [프로젝트 소개](../README.md)

## 공식 우선 운영 원칙

워크스페이스 기준은 `/Users/seokmogu/project/NOTION_PUBLISHING.md`입니다. 대화형 검색·조회·부분 수정은 Hosted Notion MCP를 우선하고, 이 툴킷은 공식 enhanced Markdown/API 기반 batch·headless 작업과 hierarchy, mapping, child-page 보존, file upload, profile, 증적 기능을 보완합니다. 내부 API와 browser automation은 공식 표면에 없는 기능이 확인된 경우에만 사용합니다.

새로운 one-off Notion uploader를 만들거나 custom block writer를 기본 경로로 사용하지 않습니다. leaf page는 native Markdown을 우선하고, page title과 동일한 첫 H1 및 heading 직후 자동 empty paragraph를 생성하지 않습니다.

## 프로필 초기화

```bash
# 설정 파일 초기화
notion-native profile init

# 워크스페이스 프로필 추가
notion-native profile add demo \
  --workspace-url https://www.notion.so/example \
  --parent-page-id 0123456789abcdef0123456789abcdef

# 허용된 환경에서 이미 안전하게 주입한 환경변수 참조를 등록
notion-native profile set-token demo --env NOTION_API_TOKEN

# 로그인 보조가 승인된 경우에만 환경변수 참조를 등록
notion-native profile set-browser-login demo \
  --email-env NOTION_LOGIN_EMAIL \
  --password-env NOTION_LOGIN_PASSWORD
```


## 브라우저 세션 인증 (token_v2)

내부 API는 브라우저 세션 쿠키(`token_v2`)로 인증합니다. 현재 검증된 운영 경로는 실제 Chrome 원격 디버깅 세션에 붙어서 Notion Magic Link 메일을 열고, 그 세션을 Playwright storage state로 저장하는 방식입니다. Chrome 쿠키 동기화의 기본 필터는 `notion.so`이며 다른 호스트의 쿠키가 자동으로 동기화된다고 가정하지 않습니다. 실제 인증 여부는 승인된 검증 요청으로 별도 확인합니다.

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
import os

from notion_native_toolkit.internal import NotionInternalClient

creds = NotionInternalClient.login(
    email=os.environ["NOTION_LOGIN_EMAIL"],
    password=os.environ["NOTION_LOGIN_PASSWORD"],
    space_id=os.environ["NOTION_SPACE_ID"],
)

# 발급된 자격 증명으로 클라이언트 생성
client = NotionInternalClient(
    token_v2=creds["token_v2"],   # 세션 유효기간은 고정 보장하지 않음
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
        "value": "NOTION_TOKEN_V2"
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
| macOS Keychain | `{"kind": "keychain", "service": "...", "account": "..."}` | OS 접근 통제를 사용하는 로컬 저장소 |
| 환경 변수 | `{"kind": "env", "value": "NOTION_TOKEN_V2"}` | value는 비밀값이 아닌 환경변수 이름 |
| 직접 값 | `{"kind": "plain", "value": "<synthetic-test-only>"}` | 테스트 전용. 실제 인증값을 파일에 저장하지 않음 |
