# 개인 로컬 컨텍스트 MCP 연결 검증 — 2026-09-07

공개 저장소용 요약이다. 실제 서비스 주소, Cloudflare 계정·정책·터널 ID, 개인 이메일, Notion 내부 채팅 URL, 프로세스 ID와 인증자료는 포함하지 않는다. 정리 전 상세 기록은 Git에서 제외되는 로컬 `.private-evidence-*` 자료로 보존했다. 이 문서만으로 다른 계정의 연결 설정이 완료되는 것은 아니다.

## 최종 상태

사용자가 승인한 `/Users/seokmogu/project` 및 제한된 `/Users/seokmogu/.codex` 지침을 개인 Notion AI 연결에서 읽었다. `scope.mode=approved-projects`, 실제 루트, 읽기 전용 표시와 소스 해시를 직접 대조했다.

- 연결 표시명: `Local Mac Context (Private)`.
- 읽기 도구 8개 활성. Portal 관리 도구 3개는 해당 개인 연결에서 비활성.
- 파일 쓰기, shell 실행, Git 변경, Codex 호출 도구는 없다.
- 임시 foreground 실행이다. 재부팅 자동 시작은 미구성.
- 전체 병렬 오케스트레이션 및 모든 개인 접근 보안 검증이 완료된 것은 아니다.

## 구성과 승인 경계

| 구성 | 확인한 설정 |
|---|---|
| 전용 Tunnel | 원본 호스트 → `http://127.0.0.1:8001`; 나머지 요청은 404 |
| 원본 Access | 전용 Service Token 한 개만 허용하는 Service Auth |
| 브로커 | 별도 무작위 bearer 검증, loopback 바인딩, 정확한 Host 허용 |
| 개인 MCP Portal | 개인 이메일 정확 일치 Allow 정책 하나, upstream 읽기 서버 하나 |
| OAuth | Managed OAuth, S256, 등록 endpoint 및 실제 Notion 인증 완료 |
| callback | Notion UI에서 확인한 `https://app.notion.com/workflows/mcp/oauth/callback` 하나만 허용 |
| 추가 허용 | URI wildcard, 임의 localhost/loopback client 및 Code Mode off |

사용자가 전용 credential을 생성하고 연결·실제 루트 전환을 승인했다. 기존 Cloudflare 서비스/터널은 변경하지 않았다. Notion 개인 연결을 사용했으며 공유 Custom Agent를 만들거나 공유 권한을 변경하지 않았다.

인증값은 채팅·Git·로그·프로세스 argv에 넣지 않았다. 사용자 UI의 credential을 임시 RSA-OAEP/SHA-256 암호문으로 전달하고, 로컬 0600 키로 메모리에서 복호화했다. 전용 token 파일은 0700 runtime 안의 0600 파일이며 broker bearer는 환경으로 전달했다.

## 검증 순서와 결과

### 1. 합성 루트와 인증

먼저 private fixture만 제공했다. UI에 축약 표시된 터널 token 때문에 첫 실행이 종료되어, 실제 Copy 값의 형식과 대상 터널 일치를 확인하고 재시작했다. 축약/손상 token을 시작 전에 거부하는 회귀 테스트를 추가했다.

| HTTPS 요청 | 결과 |
|---|---|
| 원본 Service Auth 없이 broker bearer만 제공 | 403 |
| 원본 Service Auth 정상, broker bearer 없음 | 401 |
| 원본 Service Auth 정상, broker bearer 오류 | 401 |
| 두 인증 정상, initialize | 200 / `local-context-broker` |
| 두 인증 정상, 합성 파일 읽기 | 본문 및 redacted SHA-256 로컬 일치 |
| 개인 Portal 무인증 | 401 / OAuth 메타데이터 안내 |

Python 기본 CA 경로는 issuer 검증에 실패했다. TLS 검증을 끄지 않고 macOS 신뢰 저장소를 사용하는 시스템 curl로 확인했다. 인증 헤더는 subprocess 메모리 입력으로 전달했다.

### 2. Notion 개인 연결

Notion Custom MCP UI에서 정확한 callback을 확인하고 개인 OAuth를 완료했다. 인앱에서 OAuth 팝업이 나타나지 않아 UI가 생성한 실제 authorization URL의 issuer/callback/resource/S256을 검증한 뒤 인앱 탭으로 동일 흐름을 이어갔다. 첫 시도는 Notion 대기 제한을 넘겼고, 새 요청으로 인증 완료·설치 목록을 확인했다. 임시 네트워크 관측은 해제했다.

Notion 읽기 8개 활성과 Portal 관리 3개 비활성을 재조회했다. 네이티브 앱 입력 제어는 잠금/창 불일치/붙여넣기 실패로 완료되지 않았다. 사용자가 브라우저 모델 실행도 승인한 후 Codex가 인앱 채팅에 직접 입력·전송했다.

12:42~12:44 KST, `GPT-5.6 Luna / Low` UI 선택에서 합성 파일 읽기를 완료했다. 프롬프트에 기대 marker/digest를 넣지 않았으며 실제 도구 인수·원본 응답·완료 UI를 확인했다. 반환된 path/content/sha256/digest_basis 네 항목 모두 로컬과 일치했다.

### 3. 실제 루트 전환과 경로 혼동 수정

테스트 루트를 일반 project root로만 소개하던 응답 때문에 Notion이 fixture를 실제 `/project`로 설명했다. 사용자가 실제 루트 연결과 표시 보완을 요청했다.

- `ContextScope.scope_mode`와 `scope_identity()` 추가. manifest와 모든 MCP 성공 응답에 모드·실제 루트·읽기 전용·상대 경로 규칙 포함.
- `approved-projects`는 고정된 두 루트에만 허용한다. 임의 루트는 `custom`이며 fixture가 실제 기본 루트를 가리키면 거부한다.
- 기존 `_call_scope`와 응답 크기 검사, 파일·credential·링크 차단을 재사용했다. 절대 경로 입력을 자동 허용하지 않았다.
- Notion `Sonnet 5 / High`의 설계/코드 초안을 실제 함수 계약에 맞춰 Codex가 통합하고 테스트했다.
- 기존 실행기/자식 종료를 확인한 뒤 같은 전용 설정에 `--real-context`를 추가해 시작했다. 실행 환경과 원격 manifest에서 두 실제 루트 및 모드를 다시 확인했다.
- Portal/원본 인증 설정은 유지했다. 개인 정책의 정확한 이메일 조건을 재조회했고, 위 401/403 거부도 전환 후 다시 확인했다.
- `../outside`, 프로젝트 `.env`, `.codex/config.toml` 요청은 scope error로 거부됐다.

13:10 KST 이후, 기존 Notion 채팅에서 `GPT-5.6 Luna / Low`를 선택하고 다음 네 도구를 실제 호출했다.

1. `get_scope_manifest`: 실제 루트 두 개, `approved-projects`, 읽기 전용, 프로젝트 후보 110개, 스킬 18개 및 첫 10개 후보 ID가 로컬과 일치.
2. `read_project_excerpt`: `notion-native-toolkit/pyproject.toml` 1~12행. 전체 35행 중 발췌이므로 `truncated=true`.
3. `read_global_agent_guidance`: 고정 전역 `AGENTS.md`.
4. `read_skill`: 허용된 `notion-native-toolkit/SKILL.md`.

소스 세 개의 반환 SHA-256을 로컬 ContextScope 결과와 대조해 assertion이 통과했다. digest는 마스킹된 전체 UTF-8 파일 기준이다. Notion이 이전 fixture 답변을 명시적으로 정정했다. UI 공백 정규화 때문에 코드 원문 바이트 단위 무손실 회수까지 입증한 것은 아니다.

모델/effort는 UI 선택과 라이브 목록 매핑 증거다. 해당 inference request의 outgoing config는 별도 캡처하지 않았다.

## 로컬 검증과 남은 항목

- Python: **324 passed, 18 integration deselected**. 커밋 준비 차수에서 재실행했다.
- Node 어댑터: **20 passed**, 합성 UI 입력.
- 신규 모듈 및 관련 MCP/테스트 Ruff 통과. 변경된 기존 internal.py에는 사전 존재 lint 위반이 남아 있다.
- 신규 Python 모듈 basedpyright 오류 등급 검사, lock check, diff check 통과.
- 독립 사전 검토에서 새 커밋을 막는 finding은 없었다. 정적 검토이지 전체 보안 검증은 아니다.

타 계정 로그인, token 폐기 후 거부, 실제 롤백 재실행, 재부팅 자동 시작, 병렬 UI 자동루프 및 무손실 코드 회수는 미검증/미구현이다. 경로 차단과 마스킹은 모든 개인정보·업무 기밀을 분류하는 방어가 아니다.

롤백은 전용 실행기를 종료한 뒤 같은 설정에서 `--real-context` 없이 fixture로 시작한다. credential 변경이나 기존 다른 서비스 수정은 필요하지 않다. 상세 사용법은 [브로커 안내](local-context-broker.md), 전체 잔여 목표는 [남은 작업](remaining-work-plan.md)을 따른다.
