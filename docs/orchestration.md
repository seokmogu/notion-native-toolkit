# Notion AI 오케스트레이션

기능 방향과 당일 검증을 모은 상세 문서다. 전체 자동 실행기를 제공한다고 해석하지 않는다.

[문서 목록](README.md) · [프로젝트 소개](../README.md)

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

- [범위·실행·보안 안내](local-context-broker.md)
- [JSON 세션 전달·복구](desktop-session-handoff.md) / [세션 계약](notion-desktop-sessions.md)
- [모델·추론 레벨 선택](notion-ai-model-guide.md)
- [남은 작업](remaining-work-plan.md) / [평가](evaluation-2026-09-07.md) / [원격 연결 검증 기록](cloudflare-setup-evidence-2026-09-07.md)
