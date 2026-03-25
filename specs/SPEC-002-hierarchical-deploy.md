# SPEC-002: 디렉토리 구조 보존 배포 (Hierarchical Deploy)

- **Status**: Draft
- **Created**: 2026-03-24
- **Depends**: SPEC-001
- **Project**: notion-native-toolkit

---

## 1. 문제 정의

### 현재 deploy 로직의 한계

현재 `deploy()` 함수는 **flat 구조**만 지원한다:
- 모든 MD 파일을 같은 parent page 하위에 child page로 생성
- 하위 디렉토리의 파일도 동일 레벨에 생성됨
- 디렉토리 구조가 Notion 페이지 계층으로 매핑되지 않음

### 실제 문서 구조 (54개 MD 파일)

```
ai-strategy/
├── README.md                          ← 루트 랜딩
├── adoption/                          ← 15개 MD
│   ├── README.md
│   ├── 01-survey-design.md
│   ├── 01-survey-forms/               ← 하위 디렉토리
│   │   ├── 01-employee-survey.md
│   │   └── 02-org-pre-survey.md
│   ├── 02-education-track.md ~ 09-service-roadmap.md
│   ├── device-os-inventory.md
│   ├── org-chart.md
│   └── references.md
├── executive/                         ← 7개 MD
│   ├── README.md
│   └── 01-setup.md ~ security-policy.md
├── governance/                        ← 16개 MD
│   ├── README.md
│   └── 01-executive-summary.md ~ references.md
└── training/                          ← 16개 MD
    ├── README.md
    ├── curriculum/                    ← 하위 디렉토리
    │   └── 00-foundation.md ~ silver.md
    ├── design/                        ← 하위 디렉토리
    │   └── 01-assessment.md ~ 05-success-metrics.md
    ├── job-guides/                    ← 하위 디렉토리
    │   └── data-analytics.md ~ po.md
    └── references.md
```

### 기대하는 Notion 페이지 트리

```
target-page (--parent-page-id)
├── [landing: README.md 내용]
├── adoption (Notion page)
│   ├── [landing: adoption/README.md]
│   ├── 설문 설계 (child page)
│   ├── 설문 폼 (Notion page from 01-survey-forms/)
│   │   ├── 임직원 설문 (child page)
│   │   └── 조직 사전조사 (child page)
│   └── ...
├── executive (Notion page)
│   ├── [landing: executive/README.md]
│   └── ...
├── governance (Notion page)
│   ├── [landing: governance/README.md]
│   └── ...
└── training (Notion page)
    ├── [landing: training/README.md]
    ├── curriculum (Notion page)
    ├── design (Notion page)
    └── job-guides (Notion page)
```

---

## 2. 요구사항 (EARS Format)

### FR-01: 디렉토리 → Notion 페이지 계층 매핑

**When** `--recursive` 옵션이 활성화되면,
**the system shall** 디렉토리 구조를 Notion 페이지 계층으로 재귀적으로 매핑한다:

| 파일시스템 | Notion |
|-----------|--------|
| 디렉토리 | Notion page (컨테이너) |
| README.md | 해당 디렉토리 Notion page의 landing content |
| 기타 .md 파일 | 해당 디렉토리 Notion page의 child page |
| 하위 디렉토리 | 중첩된 Notion page |

### FR-02: 루트 랜딩 페이지

**When** 루트 디렉토리에 README.md가 존재하면,
**the system shall** `--parent-page-id`로 지정한 Notion 페이지에 README.md 내용을 직접 작성한다 (기존 landing 로직 유지).

### FR-03: 서브디렉토리 랜딩 페이지

**When** 서브디렉토리에 README.md가 존재하면,
**the system shall** 해당 디렉토리의 Notion 페이지에 README.md 내용을 landing으로 작성하고, 나머지 파일은 child page로 생성한다.

**When** 서브디렉토리에 README.md가 없으면,
**the system shall** 디렉토리 이름을 제목으로 빈 Notion 페이지를 생성하고, 파일들을 child page로 생성한다.

### FR-04: 배포 순서 (Bottom-Up)

**The system shall** leaf 디렉토리부터 루트 방향으로 배포한다:

```
Phase 1: leaf 파일들 (01-survey-forms/*.md, curriculum/*.md, etc.)
Phase 2: 중간 디렉토리 파일들 (adoption/*.md, executive/*.md, etc.)
Phase 3: 중간 디렉토리 README.md들 (landing)
Phase 4: 루트 파일들
Phase 5: 루트 README.md (landing)
```

이 순서로 배포하면 상위 README.md가 배포될 때 모든 하위 페이지 URL이 page_mapping에 이미 존재한다.

### FR-05: 단일 page_mapping.json

**The system shall** 루트 디렉토리에 하나의 page_mapping.json만 생성하며, 전체 트리의 매핑을 포함한다.

```json
{
  "README.md": {"page_id": "root-id", ...},
  "adoption/README.md": {"page_id": "adoption-id", ...},
  "adoption/01-survey-design.md": {"page_id": "...", ...},
  "adoption/01-survey-forms/01-employee-survey.md": {"page_id": "...", ...},
  "training/curriculum/bronze.md": {"page_id": "...", ...}
}
```

### FR-06: 디렉토리 Notion 페이지 매핑

**The system shall** 디렉토리 자체도 page_mapping에 기록한다 (key = 디렉토리 경로):

```json
{
  "adoption/": {"page_id": "adoption-page-id", ...},
  "adoption/01-survey-forms/": {"page_id": "survey-forms-page-id", ...}
}
```

이를 통해 재배포 시 디렉토리 Notion 페이지를 재활용한다.

### FR-07: 크로스 디렉토리 링크 해결

**When** MD 파일에 다른 디렉토리의 파일을 참조하는 상대 링크가 있으면 (예: `../../governance/README.md`),
**the system shall** page_mapping 기반으로 Notion URL로 변환한다.

### FR-08: 자동 구조 감지 (기본 동작)

**When** 디렉토리가 deploy 대상으로 지정되면,
**the system shall** 하위 디렉토리 존재 여부를 자동 감지하고:
- 하위 디렉토리가 있으면 → 계층 배포
- 하위 디렉토리가 없으면 → flat 배포 (자연스럽게 동일 결과)

별도 옵션 없이 **디렉토리 구조 = Notion 페이지 구조**가 기본 동작이다.

### FR-09: CLI (변경 없음)

```
notion-native deploy <DIR> \
  --profile <PROFILE> \
  --parent-page-id <ID> \
  --base-url <URL> \
  --dry-run \
  --force
```

`--recursive` 옵션 불필요. 디렉토리를 주면 자동으로 구조를 매핑한다.

---

## 3. 구현 설계

### 핵심 함수: `deploy_recursive()`

```python
def deploy_recursive(
    target: Path,
    writer: NotionWriter,
    parent_page_id: str,
    mapping: PageMapping,
    project_root: Path,
    base_url: str | None = None,
    force: bool = False,
    dry_run: bool = False,
    report: DeployReport | None = None,
) -> DeployReport:
    """Recursively deploy a directory tree to Notion."""
```

### 알고리즘

```
def deploy_recursive(dir, parent_page_id, ...):
    # 1. 현재 디렉토리의 즉시 하위 항목 분류
    readme = dir/README.md (있으면)
    md_files = dir/*.md (README 제외)
    subdirs = dir/*/ (하위 디렉토리들)

    # 2. 서브디렉토리 먼저 재귀 처리 (bottom-up)
    for subdir in subdirs:
        # 서브디렉토리용 Notion 페이지 생성/재활용
        subdir_page_id = get_or_create_dir_page(subdir, parent_page_id)
        # 재귀 배포
        deploy_recursive(subdir, subdir_page_id, ...)

    # 3. 현재 디렉토리의 MD 파일 배포 (README 제외)
    for md in md_files:
        deploy_file(md, parent_page_id, ...)

    # 4. README.md를 landing으로 배포 (마지막 - 모든 링크 해결 가능)
    if readme:
        _deploy_landing(readme, parent_page_id, ...)
```

### 변경 파일

| 파일 | 변경 | 내용 |
|------|------|------|
| `deploy.py` | 수정 | `deploy_recursive()` 추가, `deploy()`에 `recursive` 분기 |
| `mapping.py` | 수정 | 디렉토리 키(`adoption/`) 지원 |
| `cli.py` | 수정 | `--recursive` 옵션 추가 |

### 디렉토리 제목 추출

README.md가 없는 디렉토리의 Notion 페이지 제목:
- 디렉토리 이름을 Title Case로 변환
- `01-survey-forms` → `01 Survey Forms`
- `curriculum` → `Curriculum`

---

## 4. 인수 기준

### AC-01: 기본 계층 배포

```
Given: ai-strategy/ 디렉토리 (4개 서브디렉토리, 54개 MD)
When: notion-native deploy ai-strategy/ --recursive --profile test --dry-run
Then: Notion 페이지 트리 구조가 디렉토리 구조와 일치하는 결과 출력
```

### AC-02: 서브디렉토리 README landing

```
Given: adoption/README.md 존재
When: recursive 배포 실행
Then: adoption Notion 페이지에 README 내용이 직접 작성되고, 나머지 파일은 child page
```

### AC-03: README 없는 서브디렉토리

```
Given: training/curriculum/ 에 README.md 없음
When: recursive 배포 실행
Then: "Curriculum" 제목의 빈 Notion 페이지 생성, *.md는 child page
```

### AC-04: 크로스 디렉토리 링크

```
Given: adoption/README.md에 ../governance/README.md 링크 존재
When: recursive 배포 실행
Then: governance/README.md의 Notion URL로 변환
```

### AC-05: 하위 호환성

```
Given: --recursive 미지정
When: notion-native deploy adoption/ --profile test
Then: 기존 flat 배포 동작 (모든 파일이 같은 레벨)
```

### AC-06: Idempotent 재배포

```
Given: 이미 recursive 배포 완료된 상태
When: 동일 명령 재실행
Then: 변경된 파일만 업데이트, 디렉토리 페이지 재활용
```

---

## 5. 구현 순서

### Phase 1: 코어 로직

- [ ] deploy.py: `deploy_recursive()` 함수 구현
- [ ] deploy.py: `_get_or_create_dir_page()` 디렉토리 페이지 생성/재활용
- [ ] deploy.py: `_collect_immediate_items()` 현재 디렉토리 항목 분류
- [ ] mapping.py: 디렉토리 키 지원 확인

### Phase 2: CLI + 통합

- [ ] deploy.py: `deploy()` 함수에 `recursive` 파라미터 분기 추가
- [ ] cli.py: `--recursive` 옵션 추가

### Phase 3: 테스트

- [ ] Unit: `deploy_recursive` 디렉토리 분류 로직
- [ ] Unit: 디렉토리 제목 추출
- [ ] Integration: mock 기반 전체 트리 배포

---

## 6. 범위 제외

- 디렉토리 삭제 시 Notion 페이지 자동 아카이브 (stale 경고만)
- Notion에서 수동으로 변경한 페이지 순서 보존
- 디렉토리 이동/이름 변경 감지
