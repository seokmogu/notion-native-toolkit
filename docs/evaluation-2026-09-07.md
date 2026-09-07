# 프로젝트 평가 및 개선 결과 — 2026-09-07

## 최신 판정 — 커밋 준비 차수

실제 프로젝트/제한된 Codex 지침을 읽는 개인 MCP 연결과 Notion 브라우저 직접 읽기는 완료했다. 모드와 실제 루트가 응답에 포함되며, manifest 및 소스 3개의 해시를 로컬과 대조했다. 커밋 준비에서 Python **324 passed, 18 integration deselected**, Node 합성 UI **20 passed**를 다시 확인했다. 변경된 신규 모듈/관련 MCP/테스트 Ruff와 신규 Python 모듈 typecheck도 통과했다.

실제 병렬 UI 자동루프, 무손실 코드 회수, 분야별 라우팅 벤치마크, 재부팅 자동 시작, 타 계정/폐기 후 거부는 여전히 별도 잔여 항목이다. 아래는 초기 평가와 후속 로컬 구현의 **시점별 이력**이며, 당시 Mac 잠금·Cloudflare 미연결·테스트 수를 현재 상태로 해석하지 않는다. 최신 완료 증거는 [연결 기록](cloudflare-setup-evidence-2026-09-07.md), 다음 순서는 [남은 작업](remaining-work-plan.md)을 따른다.

## 최초 판정 (이력)

**목표 미달. 로컬 구성요소와 방어 테스트는 보완했지만, 개인 인증을 거친 Notion 앱 병렬 작업의 종단 간 실행은 아직 입증되지 않았다.**

목표는 Codex가 로컬 실행·검증을 맡고, 짧은 직접 응답을 제외한 분석·코드 산출을 Notion AI 모델에 위임하는 것이다. Notion AI는 `/Users/seokmogu/project` 및 허용된 Codex 지침을 읽기 전용 MCP로 조회해야 한다. 내부 API 호출 성공, 모델 목록 조회, 로컬 테스트 통과를 이 목표의 완료로 대신하지 않는다.

평가 기준은 [진행 계획](evaluation-plan-2026-09-07.md), 현재 코드, 합성 fixture 테스트, 실제 앱·Cloudflare 조회 및 2026-09-07 모델 메타데이터다. 시작 시 존재하던 미커밋 브로커/테스트를 이어 수정했으며 커밋·푸시·공개 endpoint 생성은 하지 않았다.

## 주요 발견과 조치

| 우선순위 | 발견 | 이번 조치 | 남은 한계 |
|---|---|---|---|
| P0 | 읽기 전용이라는 이유만으로 개인 전용 접근을 보장할 수 없음 | SDK 인증 검증, 무인증/오인증 거부, loopback 바인딩, DNS rebinding 방어, HTTP secret 미설정 시 시작 거부 | static bearer는 소지자 인증일 뿐 개인 OAuth가 아님. Cloudflare/Notion 권한 실검증 필요 |
| P0 | 경로 정규화·링크·특수 파일·민감 파일을 통한 범위 이탈 가능성 | 원문 상대 경로 검사, 구성요소별 descriptor/no-follow, hardlink/특수 파일/mount 경계 및 민감 파일명 거부 | 파일시스템 방어가 모든 소스의 업무 기밀/PII 분류를 대신하지 않음 |
| P0 | 발췌 이전 문맥을 잃는 마스킹, DSN/다중행 credential 누락, 원본 digest의 비밀값 추측 위험 | 전체 파일 마스킹 후 발췌/검색, DSN·다중행 패턴, 해석 불가 credential 할당 거부, redacted-utf8 digest | 마스킹은 보조 방어이며 모든 비밀 표현을 탐지하지는 못함 |
| P1 | 검색·Git·응답 크기 제약 부족 | 동일 안전 reader 기반 고정 문자열 검색, 스캔/시간/출력 상한, 고정 Git 명령·환경·설정 제한, 직렬화 결과 상한 | 큰 범위는 partial; 외부 Git worktree pointer와 submodule 내용은 미지원 |
| P1 | 모델의 존재·활성 여부·지원 추론 레벨을 함께 검증하지 않음 | 실행 직전 inventory 검증, disabled/없는 모델/미지원 effort 거부, malformed/duplicate 메타데이터 검사 | 메타데이터는 실제 품질 벤치마크나 UI 선택 성공 증거가 아님 |
| P1 | 스트림 실패/알 수 없는 응답을 정상 텍스트처럼 반환할 가능성 | HTTP/timeout/빈 스트림/NDJSON 오류 분리, 원문 fallback 제거, 관측된 응답 경로 테스트, 로그·traceback 민감 상세 제거 | 새로운 내부 API 형식과 의미상 응답 완결성은 라이브 검증 필요 |
| P1 | 독립 탭·채팅별 시도와 결과를 연결하는 계약 부재 | SessionPool: 2~3개 in-flight, UI 동작 직렬 예약, 실제 thread 후결합, prompt hash, 불명확 전송 재시도 금지, 중복/오배달 거부. 후속 차수에서 private checkpoint·복구·JSON 전달 CLI 추가 | 실제 앱 어댑터의 자동 연결 및 중단된 실제 UI와의 복구 대조는 미검증 |
| P1 | 클릭 성공을 전송·새 채팅·완료로 오판할 위험 | 주입형 데스크톱 어댑터, 한국어 AX fixture, fresh readback, 초안/기존 생성 보호, one-use 전송, 부분 응답 보수 처리 | 고유 탭/채팅 ID, 모델 메뉴 조작, 코드 원문 무손실 회수와 라이브 다중 탭 실행은 미검증/미구현 |
| P1 | 로컬 AGENTS/스킬 문맥 불일치 | 전역→프로젝트 지침 및 선택 스킬을 버전 지문과 묶는 `build_task_context` 추가 | SKILL.md entrypoint만 제공. host 지침·대화·도구 권한·참고자료는 자동 복제하지 않음 |

독립 작업은 HTTP 인증, 모델/스트림 계약, 세션 관리, 파일 접근 적대적 검토, UI 어댑터로 나눴고 리드가 통합 검증했다. `reuse-first-engineering` 지침에 따라 기존 MCP SDK 인증과 기존 클라이언트를 확장했으며 새로운 인증 프레임워크를 추가하지 않았다. `notion-native-toolkit` 지침 및 사용자의 앱 경로 지정에 따라 데스크톱 검증을 내부 API 추론으로 대체하지 않았다.

## 변경 위치

- 파일 접근: `src/notion_native_toolkit/context_files.py`, `local_context.py`
- 읽기 전용 MCP/인증: `src/notion_native_toolkit/local_context_mcp.py`, `pyproject.toml`, `uv.lock`
- 모델/스트림: `src/notion_native_toolkit/ai_models.py`, `internal.py`, `mcp_server.py`
- 세션/앱 어댑터: `src/notion_native_toolkit/session_pool.py`, `session_store.py`, `desktop_session_cli.py`, `scripts/notion-desktop-adapter.mjs`
- 회귀 검증: `tests/test_local_context*.py`, `test_ai_models.py`, `test_internal.py`, `test_mcp_server.py`, `test_session_pool.py`, `notion-desktop-adapter.test.mjs`
- 운영 설명: [브로커](local-context-broker.md), [세션 계약](notion-desktop-sessions.md), [모델 snapshot](model-inventory-2026-09-07.txt), README 및 모델 가이드

## 초기 검증 증거 (이력)

| 검증층 | 수행/결과 | 의미와 제외 범위 |
|---|---|---|
| Python 회귀 | `uv run --with pytest pytest -q -m 'not integration'`: **296 passed, 18 deselected** | 최초 개선 270개→복구/전달 개선 후 296개. live Notion API integration 18개는 의도적으로 제외 |
| 데스크톱 어댑터 fixture | `node --test tests/notion-desktop-adapter.test.mjs`: **20 passed** | 합성/익명화 AX 입력이며 실제 추론 호출 아님 |
| 실제 loopback HTTP | 위 suite의 `test_authenticated_loopback_roundtrip` 통과 | 임시 합성 루트/메모리 credential만 사용. 401, 421, initialize, 도구 8개 등록, 문맥/검색/읽기, traversal 거부 확인 |
| 실제 로컬 지침 묶음 | 현재 프로젝트 경로 + `notion-native-toolkit` 스킬의 `build_task_context` 성공 | schema 1, 직렬화 43,510 bytes. 본문 없이 성공/크기/digest만 확인했으며 Notion에 전송하지 않음 |
| 정적 검사 | 신규 5개 Python 모듈 `basedpyright --level error`: 오류 없음 | 경고 등급을 포함한 저장소 전체 strict-clean 주장 아님 |
| Lint | 신규 모듈 및 관련 MCP/테스트 Ruff 통과 | 변경된 `internal.py` 전체 검사에는 기존 위반 6개 잔존. HEAD에서도 동일 위반 확인; HEAD 전체 9개→현재 6개 |
| 기타 | `uv lock --check --offline`, compileall, `git diff --check` 통과 | 배포/운영 상태 증거 아님 |
| 현재 모델 목록 | 등록된 `notion_ai_models` 읽기 호출 성공: 33개, disabled 1개 | 새 GPT-6 Astra 포함. 목록 조회이지 모델별 응답/성능 벤치마크 아님 |
| Notion 앱 | 최초 한국어 AX 및 새 탭/새 채팅 동작 일부 관측. 후속 재조회 2회는 **Mac locked** | 최초에는 대상 창 변경/screenshot 부재로 중단, 현재는 잠금 해제 필요. 작업 prompt 전송 없음 |
| Cloudflare/원격 E2E | 미수행 | 마지막 관측은 인앱 브라우저 로그인 화면. 현재 Mac 잠금으로 추가 조회 불가. 새 tunnel/Access/portal/credential 변경 없음 |

직렬화된 응답은 100,000 bytes, 본문/지침 묶음은 65,536 bytes 상한이다. 소스 파일은 최대 1 MB, 발췌 200줄, 검색 20건 및 5초/5,000 entry/8 MB 스캔 상한을 적용한다. 반환 `truncated`와 거부 오류를 정상적인 전체 결과로 해석하면 안 된다.

## 초기 잔여 순서 (이력)

1. **앱 실행 표면 확보**: 사용자 작업과 충돌하지 않는 Notion 창에서 fresh AX/화면을 확보한다. 실제 모델/추론 메뉴와 채팅 URL/ID, 고유 탭 식별을 확인한 뒤 주입형 어댑터와 pool을 연결한다. 확인되지 않은 메뉴 위치나 thread ID를 발명하지 않는다.
2. **개인 연결 검증**: Cloudflare 로그인 후 기존 변경 승인 범위를 재확인한다. 개인 한정 정책과 origin 차단을 먼저 확인하고 공개 경로를 열어야 한다. 일반 Notion Agent의 개인 MCP 연결을 우선 확인하며, Custom Agent를 사용한다면 공유 범위를 별도로 확인한다.
3. **원격 합성 문맥 읽기**: Notion에서 manifest→task context→새 fixture 발췌를 읽고 반환 digest를 비교한다. 무인증/오인증/다른 사용자/직접 origin 및 연결 해제 후 거부를 검증한다.
4. **동일 prompt 병렬 벤치마크**: 선택 모델별 독립 탭/채팅, 동일 prompt/context hash, 실제 model/effort readback, 시작·완료 시각, 전체 응답, 로컬 테스트 결과를 기록한다. 속도/지능/비용 메타데이터만으로 코딩·분석 특화 성능을 단정하지 않는다.
5. **운영 루프 완성**: 벤치마크 증거 기반 작업별 라우팅, 코드 원문 무손실 회수를 구현한다. 로컬 체크포인트 복구는 구현했으며 실제 중단된 앱 상태와의 대조가 남았다. Notion 응답은 검토 가능한 데이터이며 Codex가 별도 검증 후 로컬 변경/테스트를 실행한다. 현재는 모든 비단문 요청을 강제로 Notion으로 보내는 실행기가 없다.

## 후속 차수: 영속화 및 프로세스 간 전달

Mac 잠금으로 앱 작업을 재개하지 못해, 안전한 로컬 구현 범위에서 기존 SessionPool을 확장했다. 별도 scheduler나 UI 제어 라이브러리를 도입하지 않고 기존 상태 기계, 모델 검증, no-follow reader 및 표준 JSON/파일 잠금을 재사용했다.

- `to_state/from_state`: 엄격한 스키마·참조·hash 검증. 기본 복구는 pause 및 prepared→uncertain이며 탭 점유를 보존한다.
- `session_store`: 명시한 숨김 프로젝트 디렉터리, 0700/0600, no-follow, 비차단 프로세스 잠금, 덮어쓰지 않는 checkpoint와 revision 검사.
- `notion-desktop-session`: 작업 queue→commit 후 action 전달→관측 입력→완료 결과 보관/조회까지 별도 프로세스 사이에서 동작한다. 모델 메타데이터 재검증과 부분/불안정 응답 거부를 포함한다.
- 독립 검토 재현 2건 수정: 전송 기록 전 crash 상태에서 취소로 탭을 해제하던 경로 차단; 결과의 datetime을 ISO로 변환하여 실제 stdout JSON 파싱 확인.
- 새 복구/저장/CLI 테스트 26개, 기존 세션 테스트 포함 집중 35개 통과. CLI `--help`, Ruff, 신규 세션 3모듈 basedpyright 오류 없음, compileall, lock check, diff check 통과.
- 실제 모델 추론/Cloudflare 호출은 없었다. 로컬 JSON의 `source`, `complete`, `stable` 및 inventory 시간은 신뢰된 UI 호스트의 관측 선언이며, 그 선언 자체가 실제 화면 증거를 대신하지 않는다.

정확한 명령·입력·복구 절차와 남은 UI 제약은 [실행 전달·복구 안내](desktop-session-handoff.md)에 기록한다.

공식 안내상 일반 Notion Agent의 MCP 연결은 개인별이며, Custom Agent 연결과 별개다. 따라서 처음부터 공유 Custom Agent를 개인 연결의 대체로 만들면 안 된다. [Notion Agent 연결](https://www.notion.com/help/connect-mcp-servers-to-your-notion-agent)

공유 Custom Agent의 대화/실행 사용자는 연결자가 인증한 권한으로 도구를 사용할 수 있다. Cloudflare의 개인 OAuth만으로 agent를 통한 간접 공유까지 막았다고 주장할 수 없다. [Custom Agent 권한](https://www.notion.com/help/mcp-connections-for-custom-agents)

Cloudflare MCP Portal의 upstream bearer와 Managed OAuth 기능은 확인했지만, 현재 계정의 설정·Notion 클라이언트 호환성·직접 origin 차단은 별도 E2E 항목이다. [Portal](https://developers.cloudflare.com/cloudflare-one/access-controls/ai-controls/mcp-portals/), [Managed OAuth](https://developers.cloudflare.com/cloudflare-one/access-controls/applications/http-apps/managed-oauth/)

## 당시 중단/재개 조건 (이력)

로컬에서 안전하게 검증 가능한 이번 개선 묶음은 완료했다. 전체 오케스트레이션 목표는 완료 표시하지 않는다. 다음 실행은 **Mac 잠금 해제** 후 Cloudflare 재로그인 및 안전하게 제어 가능한 Notion 앱 표면을 확보해 이어간다. 기존 서비스와 사용자 초안을 변경하거나, 인증 확인 전에 project 루트를 외부에 노출하는 우회는 하지 않는다.
