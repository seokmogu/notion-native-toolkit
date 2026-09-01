# Notion AI 모델 선택 지침

이 문서는 `worxphere` 프로필에서 2026-09-01에 조회한 Notion AI 모델 목록의
스냅샷이다. 모델과 내부 코드는 Notion의 비공식 API에서 동적으로 제공되므로,
실제 호출 전에는 항상 `get_available_models()` 또는 `notion_ai_models`로
현재 목록을 다시 확인한다.

## 호출 규칙

- 사용자에게 보여줄 때는 `modelMessage`를 사용한다.
- API 요청에는 화면 표시명이 아니라 `model` 내부 코드를 전달한다.
- 사용자가 모델을 직접 선택한 경우 `config.value.modelFromUser`를 `true`로
  설정한다.
- 추론 레벨은 `config.value.reasoningEffort`에 소문자 값으로 전달한다.
- 지원 레벨은 `none`, `low`, `medium`, `high`, `xhigh`, `max`다.
- 자동 라우팅을 사용할 때는 `model`과 `reasoningEffort`를 생략한다.
- 모델별로 허용되는 추론 레벨 조합은 변경될 수 있으므로, 오류가 발생하면
  자동 라우팅 또는 해당 모델의 기본 레벨로 재시도하지 말고 현재 모델 목록과
  UI 선택 상태를 먼저 확인한다.

## 현재 조회된 모델

`displayGroup`은 Notion이 제공한 분류를 그대로 기록한 값이다. 이는 품질
순위가 아니라 UI상의 `fast`/`intelligent` 분류다.

| 표시명 | 내부 model 코드 | 계열 | 분류 |
|---|---|---|---|
| Grok 4.6 | `soursop-shortcake` | xai | intelligent |
| GPT-5.6 Luna | `olive-jellyroll` | openai | fast |
| GPT-5.6 Terra | `orchid-muffin` | openai | intelligent |
| GPT-5.6 Sol | `orange-mousse` | openai | intelligent |
| GPT-5.2 | `oatmeal-cookie` | openai | fast |
| GPT-5.4 | `oval-kumquat-medium` | openai | fast |
| GPT-5.5 | `opal-quince-medium` | openai | intelligent |
| Gemini 3.5 Flash | `vertex-gemini-3.5-flash` | gemini | fast |
| Gemini 3.6 Flash | `vertex-gemini-3.6-flash` | gemini | fast |
| Gemini 3.7 Flash | `grapefruit-zeppole` | gemini | fast |
| Sonnet 4.6 | `almond-croissant-low` | anthropic | fast |
| Sonnet 5 | `angel-cake-high` | anthropic | intelligent |
| Opus 4.6 | `avocado-froyo-medium` | anthropic | intelligent |
| Opus 4.7 | `apricot-sorbet-high` | anthropic | intelligent |
| Opus 4.8 | `ambrosia-tart-high` | anthropic | intelligent |
| Opus 5 | `agave-flan` | anthropic | intelligent |
| GPT-5.4 Mini | `oregon-grape-medium` | openai | fast |
| GPT-5.4 Nano | `otaheite-apple-medium` | openai | fast |
| Kimi K2.6 | `fireworks-kimi-k2.6` | mystery | intelligent |
| Kimi K2.7 Code | `fireworks-kimi-k2.7` | mystery | intelligent |
| Kimi K3 | `fireworks-kimi-k3` | mystery | intelligent |
| DeepSeek V4 Pro | `baseten-deepseek-v4-pro` | mystery | intelligent |
| DeepSeek V4 Flash | `baseten-deepseek-v4-flash` | mystery | fast |
| GLM 5.2 | `baseten-glm-5.2` | mystery | intelligent |
| Grok 4.3 | `xigua-mochi-medium` | xai | intelligent |
| Grok 4.5 | `strawberry-whoopiepie` | xai | intelligent |
| Grok Build 0.1 | `xinomavro-cake` | xai | intelligent |
| Gemini 3.1 Pro | `galette-medium-thinking` | gemini | intelligent |
| Haiku 4.5 | `anthropic-haiku-4.5` | anthropic | fast |
| Fable 5 | `acai-budino-high` | anthropic | intelligent |
| Gemini 3 Flash | `gingerbread` | gemini | fast |

## 선택 예시

```python
models = client.get_available_models() or {}
model_code = next(
    item["model"]
    for item in models.get("models", [])
    if item.get("modelMessage") == "GPT-5.6 Sol"
)

for chunk in client.run_ai(
    "복잡한 정책을 분석해줘",
    model=model_code,
    reasoning_effort="high",
):
    print(chunk)
```

이 지침은 모델 목록의 현재성을 보장하지 않는다. 목록이 바뀌면 이 파일은
새 조회 일자와 함께 갱신하고, 코드에는 특정 내부 코드를 기본값으로
하드코딩하지 않는다.
