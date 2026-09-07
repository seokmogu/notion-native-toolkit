# 문서

[프로젝트 소개와 빠른 시작](../README.md)에서 시작하세요. 명령은 별도 표시가 없으면 저장소 루트에서 실행합니다.

## 사용하려는 기능 선택

| 목적 | 시작 문서 |
|---|---|
| Python으로 페이지·Markdown·내부 API 사용 | [SDK 레퍼런스](sdk-reference.md) |
| 프로필, API 인증, 브라우저 세션 준비 | [인증과 프로필](authentication.md) |
| CLI로 조회·변환·승인된 쓰기 | [CLI 레퍼런스](cli-reference.md) |
| Codex 등에서 선택적 Notion AI MCP 사용 | [MCP 클라이언트 연결](mcp-reference.md) |
| Notion AI가 내 로컬 소스 읽기 | [Local Context Broker](local-context-broker.md) |
| 세션 예약·JSON 전달·복구 통합 | [Desktop Session Handoff](desktop-session-handoff.md) |
| 기여·로컬 검증·프로젝트 구조 | [개발과 테스트](development.md) |

SDK/CLI 인증과 로컬 컨텍스트의 개인 OAuth는 별개입니다. 권한·쓰기 승인·민감자료 보호 조건을 먼저 확인하세요. 루트 README의 오프라인 예제에는 인증이 필요하지 않습니다.

## 설계와 운영 상세

- [오케스트레이션 개요](orchestration.md)
- [모델·추론 레벨 선택](notion-ai-model-guide.md) — 날짜가 있는 snapshot은 라이브 목록을 대신하지 않음
- [데스크톱 세션 계약](notion-desktop-sessions.md)
- [공식 API 캡처 절차](official-api-capture.md)
- [내부 API 캡처 레퍼런스](internal-api-capture.md)
- [운영 지침](notion-toolkit-guidelines.md)

## 계획과 검증 기록

- [현재 개선 목표와 남은 작업](remaining-work-plan.md)
- [원격 연결 검증 기록](cloudflare-setup-evidence-2026-09-07.md)
- [초기 구현 평가](evaluation-2026-09-07.md)
- [README/구현 정합성 점검](readme-implementation-audit-2026-09-07.md)

이력 문서는 당시 관측입니다. 현재 동작은 코드와 최신 검증을 기준으로 확인합니다. 비공개 운영 주소·credential·내부 채팅 기록은 공개 문서에 넣지 않습니다.
