---
name: notion-native-toolkit
description: >
  Notion 통합 툴킷 - 공식 API, 내부 API(AI/검색/사용량), 브라우저 자동화, Markdown 변환을 제공합니다.
  Notion AI 호출, 모델 조회, 크레딧 확인, 워크스페이스 검색 등에 사용하세요.
allowed-tools: Read, Bash, Grep, Glob
metadata:
  version: "0.2.0"
  category: "domain"
  status: "active"
  updated: "2026-04-17"
  tags: "notion, ai, search, mcp, internal-api"
triggers:
  keywords: ["notion ai", "notion 검색", "notion search", "notion 모델", "notion 크레딧", "notion usage", "notion-native"]
---

# notion-native-toolkit

Notion 공식 API + 내부 API(v3) 통합 Python 툴킷.

## Notion AI 호출

```bash
# Notion AI에 질문 (기본 모델)
uv run --directory ~/project/notion-native-toolkit python -c "
import json
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
user_id = next((c['value'] for c in cookies if c['name'] == 'notion_user_id' and 'notion.so' in c.get('domain','')), None)

with NotionInternalClient(token_v2=token, space_id='$1', user_id=user_id) as cli:
    for chunk in cli.run_ai('$2'):
        for v in chunk.get('v', []):
            if v.get('o') in ('a','x') and '/value/' in v.get('p','') and 'content' in v.get('p',''):
                if isinstance(v.get('v'), str): print(v['v'], end='')
            elif v.get('o') == 'a' and isinstance(v.get('v'), dict) and v['v'].get('type') == 'agent-inference':
                for p in v['v'].get('value', []):
                    if isinstance(p, dict) and 'content' in p: print(p['content'], end='')
    print()
"
```

사용 예: `/notion-native-toolkit <space_id> <프롬프트>`

## AI 모델 목록

```bash
uv run --directory ~/project/notion-native-toolkit python -c "
import json
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))

with NotionInternalClient(token_v2=token, space_id='$0') as cli:
    models = cli.get_available_models()
    for m in (models or {}).get('models', []):
        print(f\"{m.get('modelMessage','?'):20s} [{m.get('modelFamily','?'):10s}] code={m.get('model','?')}\")
"
```

## AI 크레딧 사용량

```bash
uv run --directory ~/project/notion-native-toolkit python -c "
import json
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))

with NotionInternalClient(token_v2=token, space_id='$0') as cli:
    print(json.dumps(cli.get_ai_usage(), indent=2, ensure_ascii=False))
"
```

## 워크스페이스 검색

```bash
uv run --directory ~/project/notion-native-toolkit python -c "
import json
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))

with NotionInternalClient(token_v2=token, space_id='$1') as cli:
    result = cli.search('$2', limit=10)
    for r in (result or {}).get('results', []):
        print(f\"- {r.get('highlight',{}).get('text', r.get('id','?'))} (id: {r.get('id','?')})\")
"
```

## 기존 기능 (변경 없음)

```bash
# 프로필 관리
notion-native profile init
notion-native profile add my-workspace --workspace-url https://www.notion.so/my-workspace
notion-native profile set-token my-workspace --value "ntn_xxx" --keychain

# Markdown → Notion
notion-native page create-from-markdown --profile my-workspace --title "제목" --parent-page-id PAGE_ID --file doc.md

# 브라우저 자동 로그인
notion-native browser login --profile my-workspace --headed
```

## 인증

- `~/.chrome-automation-profile/cookies.json`에서 token_v2 자동 로드
- 쿠키 없으면 `notion-native login` 으로 Playwright 자동 로그인
- 401/403 에러: token_v2 만료 → 브라우저 재로그인 후 쿠키 재동기화

## Rules

- 비밀 정보는 환경 변수 또는 macOS Keychain 사용
- 프로젝트별 비즈니스 로직은 해당 프로젝트에 유지
- 공식 API 우선, 브라우저 자동화는 미지원 기능에만 사용
