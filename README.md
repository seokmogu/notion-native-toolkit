# notion-native-toolkit

Notion API·Markdown 자동화, 선택적 Notion AI 호출, 읽기 전용 로컬 컨텍스트 연결을 위한 Python 툴킷입니다.

[빠른 시작](#빠른-시작) · [문서](docs/README.md) · [MCP 연결](docs/mcp-reference.md) · [개발 안내](docs/development.md)

## 무엇을 할 수 있나요?

- **Notion 자동화** — 공식 API와 Markdown을 Python SDK·CLI로 사용합니다.
- **Notion AI 활용** — 현재 모델 목록과 지원 추론 레벨을 확인해 AI를 호출합니다. 이 기능은 비공식 내부 API를 사용하는 선택적 기능입니다.
- **로컬 문맥 제공** — Notion AI가 허용된 프로젝트 소스와 지침을 개인 인증 MCP로 읽게 합니다.

Notion AI가 분석·코드를 제안하고 Codex가 로컬 적용·명령·Git·검증을 맡는 흐름을 지원합니다.
완성된 자율 실행기나 Notion에서 Codex를 원격 실행하는 도구는 아닙니다.

## 설치

Python 3.11 이상과 [uv](https://docs.astral.sh/uv/)가 필요합니다.
현재 안내는 저장소 소스 설치를 기준으로 합니다.

```sh
git clone https://github.com/seokmogu/notion-native-toolkit.git
cd notion-native-toolkit
uv sync
uv run notion-native --help
```

브라우저 자동화가 필요할 때만 Chromium을 추가 설치합니다. [인증·브라우저 설정](docs/authentication.md)을 참고하세요.
로컬 컨텍스트·세션 실행기는 macOS/POSIX 환경을 전제로 하며, 원격 연결에는 별도 Cloudflare 설정과 `cloudflared`가 필요합니다.

## 빠른 시작

인증이나 네트워크 없이 Markdown 변환부터 확인할 수 있습니다.
저장소 루트에서 `uv run python`으로 실행하세요.

```python
from notion_native_toolkit.markdown import markdown_to_notion_blocks

blocks, pending_links = markdown_to_notion_blocks(
    "## Hello\n\n- Notion toolkit"
)
print([block["type"] for block in blocks])
# ['heading_2', 'bulleted_list_item']
```

실제 Notion API를 사용하려면 승인된 프로필을 구성해야 합니다.
[SDK 예제](docs/sdk-reference.md)와 [CLI 명령](docs/cli-reference.md)에서 이어갈 수 있습니다.

## 두 MCP는 방향과 권한이 다릅니다

| 진입점 | 호출 방향 | 용도 |
|---|---|---|
| `notion-mcp` | MCP 클라이언트 → Notion 내부 API | AI 모델·추론, 검색, 사용량 조회 |
| `local-context-mcp` | Notion AI → 로컬 파일 | 허용된 소스·지침의 읽기 전용 조회 |
| `notion-desktop-session` | 로컬 UI 호스트 ↔ 세션 저장소 | JSON 작업 전달·상태·결과·복구. 자체 모델/UI 실행 없음 |

`local-context-mcp`에는 파일 생성·수정·삭제, shell 실행, Codex 호출 도구가 없습니다.
반면 SDK·일반 CLI에는 Notion 페이지 쓰기 기능이 있으므로 프로젝트 전체가 읽기 전용인 것은 아닙니다.

개인 연결 `Local Mac Context (Private)`을 설정한 뒤 Notion AI에 다음과 같이 요청할 수 있습니다.

> Local Mac Context (Private)의 `local-context_get_scope_manifest`를 실제 호출해 현재 모드와 루트를 확인해줘. 그다음 `local-context_read_project_excerpt`로 `notion-native-toolkit/README.md`의 1~100행을 읽어줘.

먼저 manifest의 실제 `scope`를 확인하고, 파일은 반환된 프로젝트 루트 기준 상대 경로로 지정합니다.
`/project`는 도구 입력 별칭이 아닙니다.
전용 실행기의 기본은 테스트용 `fixture`이며 실제 고정 루트에는 `--real-context`가 필요합니다.
설치만으로 개인 OAuth·터널·로컬 루트가 자동 구성되지는 않습니다. [로컬 컨텍스트 설정](docs/local-context-broker.md)

## 사용 전 알아둘 점

- 공식 Hosted Notion MCP가 지원하는 작업은 공식 연결을 우선합니다. 내부 API는 승인된 기능에만 선택적으로 사용하세요.
- 각 워크스페이스의 인증·쓰기 승인 정책을 따라야 합니다. CLI의 `--yes`는 대상별 권한 검토를 대신하지 않습니다.
- 로컬 파일은 범위·링크·민감 경로·응답 크기를 제한합니다. 마스킹이 모든 개인정보나 업무 기밀을 판별하지는 않습니다.
- 스킬 문서를 읽어도 Notion에 Codex의 도구·권한·대화가 복제되는 것은 아닙니다.
- 비공식 API와 UI는 변경될 수 있습니다. 모델·추론 레벨은 호출 시점의 목록으로 확인하세요.

자세한 제한은 [인증 안내](docs/authentication.md)와 [브로커 보안 범위](docs/local-context-broker.md)를 따릅니다.

## 구현 상태

SDK·CLI, 모델 선택 검증, 읽기 전용 브로커, 세션 예약·저장·복구는 구현되어 있습니다.
개인 연결의 실제 파일 읽기 검증은 [검증 기록](docs/cloudflare-setup-evidence-2026-09-07.md)에 별도로 남겼습니다.

실제 병렬 UI 자동루프, 코드 원문 무손실 회수, 분야별 모델 벤치마크, 재부팅 자동 시작은 아직 미완료입니다.
구현된 세션 계약을 완성된 자동 오케스트레이터로 해석하지 마세요. [남은 작업](docs/remaining-work-plan.md)

## 문서

- [문서 시작점](docs/README.md) — 목적에 맞는 사용 경로
- [SDK 레퍼런스](docs/sdk-reference.md) · [CLI 레퍼런스](docs/cli-reference.md)
- [인증과 프로필](docs/authentication.md) · [MCP 클라이언트 연결](docs/mcp-reference.md)
- [로컬 컨텍스트 브로커](docs/local-context-broker.md) · [세션 전달·복구](docs/desktop-session-handoff.md)
- [모델 선택](docs/notion-ai-model-guide.md) · [오케스트레이션 상세](docs/orchestration.md)

## 개발과 기여

```sh
uv run --with pytest pytest -q -m 'not integration'
node --test tests/notion-desktop-adapter.test.mjs
```

변경에는 관련 회귀 테스트와 문서 수정을 함께 포함해주세요.
외부 integration 테스트는 기본 실행에서 제외하며, 승인된 테스트 계정에서만 별도로 실행합니다.
[개발·테스트 안내](docs/development.md)

## 라이선스

[MIT](LICENSE)
