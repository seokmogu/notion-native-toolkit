# Local Context Broker

`local-context-mcp`는 기존 `notion-internal`과 반대 방향의 도구다. Notion AI가 승인된 로컬 프로젝트 소스와 지침을 읽는 데 사용한다. Notion 세션 쿠키·프로필 로딩 코드는 사용하지 않는다.

## 범위와 한계

- 기본 프로젝트 루트: `/Users/seokmogu/project`. 최상위 디렉터리 목록을 확인하고 필요한 경로를 상대 경로로 요청한다. 중첩 저장소도 해당 경로를 직접 지정할 수 있다.
- Codex: `/Users/seokmogu/.codex/AGENTS.md`와 코드에 열거된 사용자 스킬의 `SKILL.md`만 제공한다. 새로운 스킬과 plugin cache, 스킬 참고자료·실행 스크립트는 자동 추가하지 않는다.
- 지침은 대상 경로의 상위→하위 순서로 반환한다. 다른 프로젝트 지침은 섞지 않는다. 문서의 링크는 자동으로 따라가지 않는다.
- 숨김 파일·디렉터리, credential 이름, 런타임·로그·data·artifacts·dependency 디렉터리, 지원하지 않는 파일 형식은 제외한다. 따라서 루트 아래 모든 파일이 노출되는 것은 아니다.
- 경로 각 구성요소에 no-follow 파일 열기를 적용하고, 일반 파일만 읽는다. 심볼릭 링크·hardlink·특수 파일·mount 경계를 거부한다.
- 검색도 발췌와 같은 파일 읽기 검사를 사용한다. 검색 범위가 너무 크면 `truncated: true`를 보고하므로 결과 없음과 전체 검색 완료를 혼동하면 안 된다.
- 반환 데이터의 경로·줄 번호·SHA-256으로 출처를 확인한다. SHA는 원본 비밀값 추측에 사용되지 않도록 마스킹된 전체 내용 기준이며 `digest_basis=redacted-utf8`로 표시한다. instruction entrypoint를 읽는 것만으로 그 스킬의 로컬 도구·권한·종속성이 생기지는 않는다.
- 먼저 `get_scope_manifest`를 호출한다. manifest 및 모든 MCP 성공 응답의 `scope`는 `mode`, 실제 설정된 `project_root`, `codex_instruction_root`, `read_only`, 상대 경로 규칙을 제공한다. `fixture`/`custom`을 실제 승인 루트로 해석하지 않는다. `approved-projects` 표시는 고정된 실제 두 루트에서만 허용한다.
- `/project`는 도구 입력 별칭이 아니다. 루트 탐색은 manifest, 루트 아래 검색은 `path="."`, 파일 읽기는 `path="notion-native-toolkit/pyproject.toml"`처럼 상대 경로를 사용한다. `search_project`는 문자열 검색이며 전체 디렉터리 목록 도구가 아니다.

비밀키 블록과 알려진 토큰·credential assignment 패턴을 전체 문서에서 마스킹한 뒤 발췌·검색한다. 이 처리는 보조 방어다. 소스 안의 모든 개인정보·업무 기밀을 판별하지는 못하므로, 이 루트에 외부 공유할 수 없는 원문을 두고 완전 차단을 보장한다고 해서는 안 된다.

## 도구

| 도구 | 용도 |
|---|---|
| `get_scope_manifest` | 현재 모드·실제 루트·프로젝트 후보·스킬 ID·제한 조회. 항상 먼저 호출 |
| `build_task_context(path, skill_ids)` | 전역·프로젝트 지침과 최대 5개 스킬을 동일 버전 지문이 있는 묶음으로 조회 |
| `read_agent_guidance(path)` | 대상 경로의 AGENTS 체인 |
| `read_global_agent_guidance()` | 고정된 전역 AGENTS |
| `read_skill(skill_id)` | 허용된 스킬 entrypoint |
| `search_project(query, path)` | 고정 문자열 검색 |
| `read_project_excerpt(path, start_line, end_line)` | 제한된 소스 발췌 |
| `git_status(project)` | 고정 상태 조회. includes/filters/external Git pointer는 거부 |

파일 수정·shell 실행·Git 변경 도구는 없다. Git 상태에서 민감 경로는 숨기되 `hidden_changes`를 보고하여 clean으로 오판하지 않게 한다. submodule 내용과 외부 worktree metadata는 현재 지원하지 않는다.

## 로컬 실행

```sh
uv run local-context-mcp
```

HTTP transport는 `LOCAL_CONTEXT_TRANSPORT=streamable-http`, `LOCAL_CONTEXT_PORT`(기본 8001)와 안전하게 주입한 `LOCAL_CONTEXT_BEARER_SECRET`이 필요하다. secret은 최소 32자의 ASCII 비공백 문자열로 설정하며 실제로는 충분한 엔트로피의 무작위 값이어야 한다. 값은 명령 인자, 문서, Git, 채팅에 넣지 않는다.

```sh
# secret은 이 명령 전에 승인된 credential 저장소에서 환경변수로 주입한다.
LOCAL_CONTEXT_TRANSPORT=streamable-http uv run local-context-mcp
```

바인딩은 `127.0.0.1`이다. 추가 Host를 허용해야 할 경우 서버 운영자가 `LOCAL_CONTEXT_ALLOWED_HOST`에 정확한 호스트 한 개를 설정한다. DNS rebinding 보호는 유지한다.

### 전용 Cloudflare 런타임

기존 `python -m notion_native_toolkit.local_context_runtime` 실행기의 기본은 합성 fixture다. 실제 사용자 승인 루트로 실행할 때는 **`--real-context`가 필수**다. 기존 private encrypted credential 전달 옵션과 전용 host/port를 그대로 사용한다. 이 플래그는 루트를 고정된 `/Users/seokmogu/project` 및 `/Users/seokmogu/.codex`로 바꿀 뿐, 숨김/인증자료 차단과 스킬 allowlist를 완화하지 않는다.

2026-09-07 13:10 KST부터 실제 루트 모드로 실행 중이다. 임시 foreground 실행이며 재부팅 자동 시작은 아직 구성하지 않았다. 롤백할 때는 해당 실행기와 자식의 종료를 확인한 뒤 같은 실행 옵션에서 `--real-context`만 빼서 fixture 모드로 시작한다. 기존 Cloudflare 포털/인증/다른 서비스는 수정할 필요가 없다.

## 개인 원격 연결 상태

HTTP bearer는 secret 소지자를 인증한다. 이것만으로 개인 계정 소유자임을 보증하지는 않는다. OAuth issuer의 `.invalid` 주소는 외부 OAuth를 제공하지 않는다는 표시이며, 이 서버를 Notion의 OAuth 서버로 등록하면 안 된다. Cloudflare Portal을 사용할 경우 upstream bearer 인증 대상이다.

원격 연결의 완료 조건은 다음과 같다.

1. 개인 계정만 허용하는 Portal Access 정책과 origin 접근 제한.
2. Portal을 통한 로그인·MCP 호출 성공 및 Notion 연결의 개인 소유·공유 범위 확인.
3. 비로그인·잘못된 token·다른 사용자·직접 origin URL 접근 거부.
4. Notion에서 새 합성 fixture를 읽고 로컬 SHA와 일치하는지 확인.
5. 연결 해제·token 폐기 후 재호출 거부 및 rollback 확인.

2026-09-07 사용자 승인 후 터널, 원본 Service Auth 앱/정책, MCP 서버 및 개인 Portal을 생성·재조회했다. 원본 인증 미제공은 403, broker bearer 미제공/오류는 401, Portal 무인증 요청은 401이다. 실제 루트 전환 후에도 같은 거부 결과를 다시 확인했다. Notion 개인 OAuth 및 `Local Mac Context (Private)` 설치, 읽기 8개 활성·Portal 관리 3개 비활성을 확인했다. **Notion AI의 합성 파일 읽기 및 실제 project 파일·전역 지침·스킬 읽기 E2E까지 완료**했다. 프로젝트 후보 110개/스킬 18개와 소스 3개의 digest가 로컬과 일치했다. 다른 사용자 로그인과 token 폐기 후 거부는 미검증이며, 이를 전체 보안 검증 완료로 표시하지 않는다. [설정 진행 증거](cloudflare-setup-evidence-2026-09-07.md)를 참조한다. 기존 서비스는 변경하지 않았다.

등록 폼은 브로커의 Authorization bearer와 Cloudflare Service Auth 헤더를 함께 보내는 사용자 지정 헤더 방식을 제공하며 실제로 8개 도구를 발견했다. 원본 `.invalid` issuer를 OAuth upstream으로 사용하지 않는다. Portal의 실제 OAuth 메타데이터에서 registration endpoint와 S256을 확인했고, Notion UI가 제공한 `https://app.notion.com/workflows/mcp/oauth/callback` 하나만 허용해 개인 OAuth 연결을 완료했다.

## 연결 표면과 개인 권한 확인

일반 Notion Agent의 MCP는 개인별 연결이며, Business/Enterprise 및 관리자 허용 조건이 있다. 일반 채팅의 `All sources → MCP servers`와 `Settings → Connections → Discover → Add Custom MCP`를 먼저 확인한다. 이는 공식 Notion MCP 서버에 Codex를 연결하는 반대 방향 설정과 다르다. [Notion 공식 안내](https://www.notion.com/help/connect-mcp-servers-to-your-notion-agent)

Custom Agent 연결은 별개다. 공유된 Custom Agent의 대화·실행 권한을 가진 사람이 연결자의 credential로 도구를 사용할 수 있으므로, "내가 OAuth에 로그인했다"는 이유만으로 개인 전용이라고 판단하면 안 된다. 이 경로를 선택할 때는 agent를 개인 전용으로 유지하고 멤버·그룹·workspace·링크 공유를 실제로 확인해야 한다. 이 작업에서는 Custom Agent 생성이나 공유 변경을 수행하지 않았다. [Notion Custom Agent 권한 안내](https://www.notion.com/help/mcp-connections-for-custom-agents)

Cloudflare의 MCP Portal은 upstream bearer를 주입할 수 있고 Managed OAuth로 클라이언트를 인증할 수 있다. 기능 존재는 이 계정의 설정 완료나 Notion과의 호환 검증을 뜻하지 않는다. [Portal 공식 안내](https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/), [Managed OAuth 공식 안내](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/)
