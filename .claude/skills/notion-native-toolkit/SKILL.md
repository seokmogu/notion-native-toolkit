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

## 환경 설정

NOTION_SPACE_ID 환경변수가 필요합니다. `.envrc`, `.env.shared`, 또는 쉘에서 설정하세요:

```bash
export NOTION_SPACE_ID='xxxxxxxx-xxxx-xxxx-xxxx-xxxxxxxxxxxx'
```

인증은 `~/.chrome-automation-profile/cookies.json`에서 token_v2를 자동 로드합니다.

## Notion AI 호출

사용법: `/notion-native-toolkit <프롬프트>`

```bash
uv run --directory ~/project/notion-native-toolkit python -c "
import json, os
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
user_id = next((c['value'] for c in cookies if c['name'] == 'notion_user_id' and 'notion.so' in c.get('domain','')), None)
space_id = os.environ['NOTION_SPACE_ID']

with NotionInternalClient(token_v2=token, space_id=space_id, user_id=user_id) as cli:
    for chunk in cli.run_ai('$ARGUMENTS'):
        for v in chunk.get('v', []):
            if v.get('o') in ('a','x') and '/value/' in v.get('p','') and 'content' in v.get('p',''):
                if isinstance(v.get('v'), str): print(v['v'], end='')
            elif v.get('o') == 'a' and isinstance(v.get('v'), dict) and v['v'].get('type') == 'agent-inference':
                for p in v['v'].get('value', []):
                    if isinstance(p, dict) and 'content' in p: print(p['content'], end='')
    print()
"
```

## AI 모델 목록

`/notion-native-toolkit models` 또는 자연어로 "notion ai 모델 목록" 요청

```bash
uv run --directory ~/project/notion-native-toolkit python -c "
import json, os
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
space_id = os.environ['NOTION_SPACE_ID']

with NotionInternalClient(token_v2=token, space_id=space_id) as cli:
    models = cli.get_available_models()
    for m in (models or {}).get('models', []):
        print(f\"{m.get('modelMessage','?'):20s} [{m.get('modelFamily','?'):10s}] code={m.get('model','?')}\")
"
```

## AI 크레딧 사용량

```bash
uv run --directory ~/project/notion-native-toolkit python -c "
import json, os
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
space_id = os.environ['NOTION_SPACE_ID']

with NotionInternalClient(token_v2=token, space_id=space_id) as cli:
    print(json.dumps(cli.get_ai_usage(), indent=2, ensure_ascii=False))
"
```

## 워크스페이스 검색

```bash
uv run --directory ~/project/notion-native-toolkit python -c "
import json, os
from pathlib import Path
from notion_native_toolkit.internal import NotionInternalClient

cookies = json.loads(Path.home().joinpath('.chrome-automation-profile/cookies.json').read_text())
token = next(c['value'] for c in cookies if c['name'] == 'token_v2' and 'notion.so' in c.get('domain',''))
space_id = os.environ['NOTION_SPACE_ID']

with NotionInternalClient(token_v2=token, space_id=space_id) as cli:
    result = cli.search('$ARGUMENTS', limit=10)
    for r in (result or {}).get('results', []):
        print(f\"- {r.get('highlight',{}).get('text', r.get('id','?'))} (id: {r.get('id','?')})\")
"
```

## 기존 CLI 기능

```bash
notion-native profile init
notion-native profile add my-workspace --workspace-url https://www.notion.so/my-workspace
notion-native profile set-token my-workspace --value "ntn_xxx" --keychain
notion-native page create-from-markdown --profile my-workspace --title "제목" --parent-page-id PAGE_ID --file doc.md
notion-native browser login --profile my-workspace --headed
```

## 인증 트러블슈팅

| 증상 | 해결 |
|------|------|
| token_v2 없음 | `notion-native login` 실행 또는 Chrome DevTools에서 쿠키 복사 |
| 401/403 | token_v2 만료 → 브라우저 재로그인 후 쿠키 재동기화 |
| NOTION_SPACE_ID 없음 | Notion Settings에서 space ID 복사 후 환경변수 설정 |

## Rules

- 비밀 정보는 환경 변수 또는 macOS Keychain 사용
- 프로젝트별 비즈니스 로직은 해당 프로젝트에 유지
- 공식 API 우선, 브라우저 자동화는 미지원 기능에만 사용
