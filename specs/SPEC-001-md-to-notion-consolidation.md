# SPEC-001: MD-to-Notion 통합 변환기 개선

- **Status**: Draft
- **Created**: 2026-03-24
- **Project**: notion-native-toolkit
- **Language**: Python 3.13+, uv

---

## 1. 배경 및 문제 정의

### 현황

6개 프로젝트에 Notion 관련 도구가 산재하며, MD→Notion 변환 로직이 3곳에서 중복 구현되어 있다:

| 구현체 | 파서 | 강점 | 약점 |
|--------|------|------|------|
| `notion-native-toolkit/markdown.py` | mistletoe | 양방향 변환, 모듈화, 프로필 관리 | batch 배포 없음, 코드블록 2000자 초과 미처리 |
| `knowledge-base/upload_to_notion.py` | line-by-line regex | page_mapping, idempotent 배포, 링크 변환 | API 키 하드코딩, bare except, 단일 프로젝트 전용 |
| `jk-po-copilot/md-to-notion/upload_to_notion.py` | markdown-it-py | 코드블록 청킹, CLI 유연성, 클래스 기반 | page_mapping 없음, 상대경로 드롭, callout 단일 이모지 |

### 해결할 문제

1. **경로 깨짐**: `./img/a.png`, `../docs/b.md` 등 상대 링크가 Notion에서 동작하지 않음
2. **표현 차이**: 테이블, Mermaid, callout, 코드블록 등 MD 구문이 Notion 블록과 1:1 매핑되지 않음
3. **문서 구조 손실**: 헤딩 기반 계층이 Notion 페이지 트리로 변환되지 않음
4. **중복 코드**: 3곳의 변환 로직을 하나로 통합 필요

---

## 2. 요구사항 (EARS Format)

### FR-01: MD 파싱 파이프라인 개선

**When** 사용자가 Markdown 파일을 변환 요청하면,
**the system shall** mistletoe AST를 기반으로 다음 블록 타입을 Notion Block으로 1:1 변환한다:

| MD 구문 | Notion Block | 우선순위 |
|---------|-------------|---------|
| `# ~ ###` | heading_1 ~ heading_3 | P0 |
| paragraph | paragraph | P0 |
| `- item` | bulleted_list_item | P0 |
| `1. item` | numbered_list_item | P0 |
| `- [ ] / - [x]` | to_do | P0 |
| `` ```lang ``` `` | code (with language) | P0 |
| `> quote` | quote / callout | P0 |
| `\| table \|` | table | P0 |
| `---` | divider | P1 |
| `![alt](url)` | image | P1 |
| `` ```mermaid ``` `` | code (mermaid, sanitized) | P1 |
| `> [!NOTE]` etc. | callout (GitHub-style admonitions) | P2 |
| nested lists | bulleted_list_item children | P2 |

### FR-02: 코드블록 청킹

**When** 코드블록이 2000자를 초과하면,
**the system shall** 언어별 주석 구문으로 `# Part N of M` 라벨을 붙여 분할한다.

**When** Mermaid 다이어그램인 경우,
**the system shall** 분할하지 않고 Notion 호환 문법으로 정제(sanitize)만 수행한다.

### FR-03: 상대 경로 변환

**When** Markdown에 상대 경로 링크(`./`, `../`, 확장자 `.md/.png/.jpg`)가 포함되면,
**the system shall** 다음 우선순위로 변환한다:

1. `page_mapping.json`에 매핑된 Notion URL로 변환
2. `--base-url` 옵션이 제공되면 GitHub/GitLab raw URL로 변환
3. 이미지 파일이면 Notion File Upload API로 업로드 후 image 블록 생성
4. 변환 불가시 `pending_links` 목록에 기록하고 경고 출력

### FR-04: Idempotent 배치 배포

**When** 사용자가 디렉토리 단위로 배포 명령을 실행하면,
**the system shall** `page_mapping.json`을 기반으로:

- 신규 파일: Notion 페이지 생성 후 매핑 기록
- 기존 파일: 페이지 내용 교체 (clear → append), URL 유지
- 삭제된 파일: 경고 출력 (자동 삭제하지 않음)

**page_mapping.json 스키마:**
```json
{
  "docs/guide.md": {
    "page_id": "abc123...",
    "url": "https://notion.so/...",
    "title": "Guide",
    "last_deployed": "2026-03-24T12:00:00Z",
    "content_hash": "sha256:..."
  }
}
```

### FR-05: 문서 구조 → 페이지 트리 변환

**When** `--tree` 옵션이 활성화되면,
**the system shall** H1 기준으로 Notion 하위 페이지를 자동 생성하고, H2/H3는 해당 하위 페이지 내 헤딩으로 배치한다.

**When** `--tree` 옵션이 비활성화(기본값)이면,
**the system shall** 모든 헤딩을 단일 페이지 내 heading 블록으로 유지한다.

### FR-06: 듀얼 배포 지원

**When** 사용자가 `deploy` 명령을 실행하면,
**the system shall** 동일 MD 소스에서:

- Notion API 배포 (page_mapping 기반)
- Git 저장소 배포용 MD 유지 (상대 경로 보존)

를 동시 지원한다. Notion 배포 시 소스 MD 파일을 수정하지 않는다.

### FR-07: Callout 변환 강화

**When** blockquote가 다음 패턴을 포함하면,
**the system shall** Notion callout 블록으로 변환한다:

| 패턴 | 이모지 | 타입 |
|------|--------|------|
| `> [!NOTE]` | 💡 | info |
| `> [!TIP]` | 💡 | info |
| `> [!WARNING]` | ⚠️ | warning |
| `> [!CAUTION]` | ❌ | danger |
| `> [!IMPORTANT]` | ❗ | important |
| 첫 글자 이모지 (`> ⚠️ text`) | 해당 이모지 | auto |

Callout 내부 블록(리스트, 코드 등)은 children으로 중첩 지원한다.

### FR-08: 레이트 리밋 및 에러 처리

**The system shall** Notion API 제한(3 req/sec)을 준수하며:

- 요청 간 0.35초 지연 (기존 client.py 유지)
- 429 응답 시 `Retry-After` 헤더 기반 백오프
- 최대 3회 재시도 후 실패 보고
- 배치 실패 시 개별 블록 단위 재시도 (기존 writer.py 유지)

### FR-09: CLI 인터페이스 확장

기존 CLI에 `deploy` 서브커맨드 추가:

```
notion-native deploy <DIR_OR_FILE> \
  --profile <PROFILE> \
  --parent-page-id <ID> \
  --base-url <GITHUB_RAW_BASE> \
  --tree \
  --dry-run \
  --force
```

| 옵션 | 설명 | 기본값 |
|------|------|--------|
| `--profile` | 워크스페이스 프로필 | default |
| `--parent-page-id` | 배포 대상 상위 페이지 | 프로필 설정값 |
| `--base-url` | 이미지/링크 절대경로 베이스 | None |
| `--tree` | H1 기준 하위 페이지 분리 | False |
| `--dry-run` | 변환 결과만 출력, API 호출 안 함 | False |
| `--force` | content_hash 무시하고 전체 재배포 | False |

### NFR-01: 보안

- API 키는 환경변수 또는 Keychain으로만 관리 (기존 credentials.py 유지)
- 소스 코드에 시크릿 하드코딩 금지
- SSL 검증은 기본 활성, `NO_SSL_VERIFY` 환경변수로만 비활성화

### NFR-02: 성능

- content_hash 기반 변경 감지로 불필요한 재배포 스킵
- 100개 문서 배치 배포 시 10분 이내 완료
- 블록 청킹: 생성 시 30개, 추가 시 100개 (기존 writer.py 유지)

### NFR-03: 호환성

- Python 3.11+ (pyproject.toml 기존 설정 유지)
- 기존 CLI 명령어 하위 호환 보장
- 기존 `markdown_to_notion_blocks()` API 시그니처 유지

---

## 3. 구현 설계

### 신규 모듈

```
src/notion_native_toolkit/
├── deploy.py          # NEW: 배치 배포 엔진 (FR-04, FR-06)
├── mapping.py         # NEW: page_mapping.json 관리 (FR-04)
├── resolver.py        # NEW: 상대 경로 변환 (FR-03)
├── markdown.py        # MODIFY: 파싱 강화 (FR-01, FR-02, FR-07)
├── writer.py          # MODIFY: 이미지 업로드 연동 (FR-03)
├── cli.py             # MODIFY: deploy 서브커맨드 추가 (FR-09)
└── (기존 모듈 유지)
```

### 변환 파이프라인

```
MD File
  → mistletoe AST 파싱
  → Block 변환 (markdown.py)
  → 코드블록 청킹 (FR-02)
  → 상대경로 해석 (resolver.py)
  → Notion API 전송 (writer.py + client.py)
  → page_mapping.json 업데이트 (mapping.py)
```

### 기존 코드 흡수 계획

| 기능 | 출처 | 흡수 대상 모듈 |
|------|------|---------------|
| page_mapping.json 관리 | knowledge-base | mapping.py (신규) |
| 코드블록 청킹 + 언어별 주석 | jk-po-copilot | markdown.py (기존 수정) |
| 이모지 callout 매핑 (8종) | knowledge-base | markdown.py (기존 수정) |
| GitHub admonition 변환 | 신규 구현 | markdown.py (기존 수정) |
| 배치 디렉토리 순회 | knowledge-base | deploy.py (신규) |
| content_hash 변경 감지 | 신규 구현 | mapping.py (신규) |
| 이미지 파일 업로드 | 기존 writer.py 확장 | writer.py + resolver.py |

---

## 4. 인수 기준

### AC-01: 단일 파일 배포

```
Given: README.md 파일 (헤딩, 코드블록, 테이블, 이미지 링크 포함)
When: notion-native deploy README.md --profile test
Then: Notion 페이지 생성, 모든 블록 타입 정확히 렌더링, page_mapping.json 생성
```

### AC-02: Idempotent 재배포

```
Given: 이미 배포된 README.md (page_mapping.json 존재)
When: notion-native deploy README.md --profile test (내용 변경 후)
Then: 기존 페이지 URL 유지, 내용만 교체, content_hash 업데이트
```

### AC-03: 상대 경로 변환

```
Given: MD 파일에 ./images/arch.png, ./api.md#auth 링크 포함
When: notion-native deploy . --base-url https://github.com/org/repo/raw/main
Then: 이미지는 GitHub raw URL 또는 Notion 업로드, MD 링크는 page_mapping URL로 변환
```

### AC-04: 코드블록 청킹

```
Given: 3000자 Python 코드블록
When: 변환 실행
Then: 2개 블록으로 분할, 각각 "# Part 1 of 2", "# Part 2 of 2" 라벨 포함
```

### AC-05: 배치 배포

```
Given: docs/ 디렉토리에 10개 MD 파일
When: notion-native deploy docs/ --profile test
Then: 10개 Notion 페이지 생성/업데이트, page_mapping.json에 전체 매핑 기록
```

### AC-06: Dry Run

```
Given: 배포 대상 MD 파일
When: notion-native deploy . --dry-run
Then: 변환 결과 JSON 출력, Notion API 호출 없음, page_mapping.json 변경 없음
```

### AC-07: 페이지 트리 변환

```
Given: H1 3개가 포함된 대형 MD 파일, --tree 옵션 활성
When: notion-native deploy large.md --tree
Then: H1마다 하위 페이지 생성, H2/H3는 각 하위 페이지 내 헤딩으로 배치
```

---

## 5. 구현 순서 (Phase)

### Phase 1: 코어 변환 강화 (P0)

- [ ] markdown.py: 코드블록 청킹 로직 추가
- [ ] markdown.py: GitHub admonition (`[!NOTE]` 등) callout 변환
- [ ] markdown.py: 이모지 callout 매핑 확장 (8종)
- [ ] markdown.py: 이미지 블록 지원 (`![alt](url)`)

### Phase 2: 배포 엔진 (P0)

- [ ] mapping.py: page_mapping.json CRUD + content_hash
- [ ] resolver.py: 상대 경로 → 절대 URL / Notion URL 변환
- [ ] deploy.py: 단일 파일 / 디렉토리 배포 로직
- [ ] writer.py: 이미지 업로드 연동

### Phase 3: CLI 확장 (P1)

- [ ] cli.py: `deploy` 서브커맨드 추가
- [ ] cli.py: `--dry-run`, `--force`, `--tree`, `--base-url` 옵션

### Phase 4: 고급 기능 (P2)

- [ ] deploy.py: `--tree` 모드 (H1 기준 하위 페이지 분리)
- [ ] markdown.py: nested list 지원
- [ ] 테스트: 각 AC에 대한 테스트 케이스

---

## 6. 테스트 전략

| 레벨 | 대상 | 도구 |
|------|------|------|
| Unit | markdown.py 블록 변환 함수별 | pytest |
| Unit | mapping.py CRUD, content_hash | pytest |
| Unit | resolver.py 경로 변환 | pytest |
| Integration | deploy.py → Notion API (mock) | pytest + respx |
| E2E | CLI deploy → 실제 Notion 페이지 | pytest (--run-e2e flag) |

---

## 7. 범위 제외

- Notion → MD 역방향 동기화 (기존 from-page 명령으로 수동 처리)
- 데이터베이스 프로퍼티 관리
- 실시간 양방향 동기화
- 기존 knowledge-base, jk-po-copilot 스크립트 삭제/마이그레이션 (별도 SPEC)
