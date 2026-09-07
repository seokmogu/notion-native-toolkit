# README·구현 정합성 점검 — 2026-09-07

## 이번 목표

README를 처음 방문자용 200줄 이하 안내로 만들고, 기존 기술 레퍼런스를 보존하면서 실제 명령·기본값·권한·데이터 형식과 맞춘다. 사용자 지시로 **GPT와 로컬 서브에이전트만** 작업했다. 앞서 요청한 Notion 초안은 사용하지 않았다.

기존 앱 Goal의 문구 수정 API가 없어 전체 목표를 완료로 바꾸지 않았다. 이번 목표는 [실행 계획](remaining-work-plan.md)에 기록했다. 원격 서비스·인증·Notion 데이터 변경 및 커밋·푸시는 범위 밖이다.

## README 분리

기준 커밋 `7b46289`의 README 1,016줄을 108줄로 재구성했다. 제목·코드 예제만 지워 줄인 것이 아니라 기존 15개 최상위 섹션을 아래 문서로 옮겼다. 구현과 충돌하던 설명은 수정했으며 원본은 Git 이력으로 추적할 수 있다.

| 기존 섹션 | 이동 위치 |
|---|---|
| Notion AI 오케스트레이션 | [orchestration.md](orchestration.md) |
| 공식 우선 운영 원칙 | [authentication.md](authentication.md) |
| 이 프로젝트가 필요한 이유 | [sdk-reference.md](sdk-reference.md) |
| 아키텍처 | [sdk-reference.md](sdk-reference.md) |
| 설치 | [development.md](development.md) |
| 빠른 시작 | [sdk-reference.md](sdk-reference.md) + [authentication.md](authentication.md) |
| 브라우저 세션 인증 (token_v2) | [authentication.md](authentication.md) |
| 프로필 설정 | [authentication.md](authentication.md) |
| CLI 사용법 | [cli-reference.md](cli-reference.md) |
| 테스트 | [development.md](development.md) |
| 내부 API 메서드 전체 목록 | [sdk-reference.md](sdk-reference.md) |
| 프로젝트 구조 | [development.md](development.md) |
| MCP 서버 (Claude Code / AI 에이전트 연동) | [mcp-reference.md](mcp-reference.md) |
| Claude Code 스킬 사용법 | [mcp-reference.md](mcp-reference.md) |
| 참고 사항 | [sdk-reference.md](sdk-reference.md) |

[문서 목차](README.md)에서 목적별로 접근할 수 있다. 루트 README에는 소개·설치·오프라인 예제·두 MCP의 차이·핵심 제한·문서·기여·라이선스만 남겼다.

## 발견과 수정

| 구분 | 확인한 불일치 | 조치 |
|---|---|---|
| 구현 | 오류 안내에 실제 parser에 없는 `profile set-internal` 명령 노출 | `toolkit.require_internal`을 실제 프로필 필드와 존재하는 도움말로 수정; credential argv 안내 제거 |
| 구현 | Markdown 페이지 생성/수정은 문서의 `--yes` 확인 약속과 달리 바로 실행 가능 | 기존 API 명령 패턴을 재사용해 두 명령에 `--yes`와 최초 단계 guard 추가 |
| 구현/안내 | runtime 도움말이 실제 루트 지원을 설명하지 않음 | fixture 기본값과 `--real-context` 목적을 명시 |
| 문서 | CLI 기본 `blocks`와 정책상 권장 `native`가 혼동됨 | 호환 기본값은 유지하고 공식 Markdown 사용 시 `--mode native` 명시 안내 |
| 문서 | 기본 설치에는 pytest가 없는데 bare pytest 명령 안내 | `uv run --with pytest pytest`로 수정 |
| 문서 | 모델 목록을 문자열 배열, run_ai 결과를 토큰으로 설명 | 모델 object 목록과 NDJSON 이벤트 dict로 수정; 최종 텍스트 MCP 경로 구분 |
| 문서 | 세션 1년 유효·자동 갱신 주장 | 세션별 유효기간, 명시적 재로그인/재동기화로 정정 |
| 문서 | MCP rate_limit 조절·스트림 자동 재시도 오해 | 일반 _post의 최대 3회 재시도와 비재시도 스트림을 구분; 미제공 설정 안내 제거 |
| 문서 | 기본 쿠키 동기화와 다른 호스트 지원 단정 | 기본 notion.so 필터와 실제 인증 검증 필요성 명시 |
| 문서 | PyPI 배포 확인 없는 설치와 미포함 스킬 사용 오해 | 소스 설치로 통일; 별도 스킬 구성과 배포되는 MCP를 구분 |
| 문서 | credential 예제의 env 참조가 `variable`, 직접 값 kind가 `value`여서 실제 스키마와 다름 | 실제 `value`(환경변수 이름) 및 `kind=plain`으로 수정; 프로필 JSON round-trip 회귀 추가 |

범위를 넓혀 OAuth·라이브 UI·전체 오케스트레이터를 변경하지 않았다. 추가 인증 기능, 기본 writer 전환, 개인 루트 일반화는 이 문서 수정의 근거만으로 구현하지 않는다.

## 호환성 안내

`notion-native page create-from-markdown`과 `page update-from-markdown`은 이제 `--yes` 없이는 프로필·파일·네트워크 접근 전에 거부된다. 기존 호출 스크립트는 대상·내용을 승인한 후 플래그를 추가해야 한다. `native/blocks/cli` 세 모드의 승인 후 분기와 기존 `blocks` 기본값·child 보존은 유지했다.

로컬 컨텍스트 MCP에는 여전히 파일 쓰기/명령 실행 도구가 없다. 이 CLI 쓰기 확인은 Notion 페이지용 SDK/CLI 경로의 보완이다. `--yes`는 정책상 대상별 승인이나 원격 권한을 자동 확인해 주지는 않는다.

## 검증

문서 링크·Python 예제 문법, README 길이와 네트워크를 차단한 오프라인 예제 실행, CLI 예제의 실제 parser 검증, 프로필 JSON round-trip, 확인 전 부작용 거부 및 승인 후 세 모드 분기를 회귀 테스트에 추가했다.

- 전체 Python: **352 passed, 18 external integration deselected**.
- 문서 계약: **13 passed** (전체 suite에 포함).
- Node 어댑터: **20 passed**, 합성 UI 입력.
- 세 변경 소스와 두 신규 테스트의 basedpyright 오류 등급 검사: **0 errors, 0 warnings**. pytest를 포함한 임시 검증 환경의 Python 경로를 명시했다.
- 변경 toolkit/runtime 및 관련 테스트 Ruff 통과. CLI의 기존 TRY004 두 건은 HEAD에도 있는 오류 타입 스타일 지적으로, 예외 호환성을 바꾸지 않고 남겼다. 기존 import 정렬 위반은 정리했다.
- 페이지 생성/수정과 runtime의 실제 `--help`, lock check, `git diff --check` 통과. 이전 README의 외부 Markdown 링크 대상도 보존했다.

완료 조건인 짧은 README·레퍼런스 보존·확인된 불일치 수정·로컬 검증을 충족했다. GPT-only 지시 이후 Notion 추론 요청을 보내지 않았고, 그 전에 요청했던 초안도 사용하지 않았다. 이번 수정의 검증은 로컬에서만 수행했으며 로그인/게시, 터널 재시작, credential 변경, 커밋·푸시는 하지 않았다. 전체 병렬 오케스트레이션 목표는 별도 미완료다.
