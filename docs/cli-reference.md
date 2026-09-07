# CLI 레퍼런스

명령은 저장소 루트에서 실행하거나 설치된 notion-native를 사용한다. Notion에 쓰는 명령은 실행 전 대상/범위 승인이 필요하다. `page create-from-markdown`과 `page update-from-markdown`은 이제 `--yes`가 필수이며 인증/파일 읽기보다 먼저 확인한다. 기존 자동화도 명시적 승인 후 플래그를 추가해야 한다.

호환 기본값은 `--mode blocks`다. 공식 Markdown 경로를 사용할 때는 `--mode native`를 명시한다. 기본값을 바꾸지는 않았다. `--yes`는 실행 동의 표시이며 대상별 권한·내용 검토를 대신하지 않는다. [인증 정책](authentication.md)을 먼저 확인한다.

[문서 목록](README.md) · [프로젝트 소개](../README.md)

## CLI 사용법

### 페이지 관리

```bash
# 마크다운에서 페이지 생성
notion-native page create-from-markdown --yes \
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
notion-native page update-from-markdown --yes \
  --profile worxphere \
  --page-id 0123456789abcdef \
  --file docs/spec.md \
  --mode blocks  # blocks, native, cli (기본: blocks)

# Notion 공식 CLI 경로로 Markdown 페이지 생성/수정
notion-native page create-from-markdown --yes \
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

# 승인된 환경에서 안전하게 주입한 API 토큰 환경변수 참조
notion-native profile set-token team-a --value "ntn_xxx" --keychain
```
