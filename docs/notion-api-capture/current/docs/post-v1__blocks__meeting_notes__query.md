> Query meeting notes for the workspace with optional filters, sorts, and a result limit.

# Query meeting notes

### Overview

Returns a list of **meeting notes** as [block objects](/reference/block) (`object` is `block`, `type` is `meeting_notes`) where the **user tied to the integration** (in the workspace) is listed as a attendee on the block.

The response contains:

* `results`: meeting note blocks (including `meeting_notes` payload with title, status, children tab IDs (e.g. summary, notes, transcription), and calendar and recording metadata when present).
* `has_more`: whether additional rows exist beyond this response for the current filter, sort, and `limit`.

**Field selection:** There is no field subset parameter—each `results[]` item is a full [block object](/reference/block). Read the fields you need (for example `meeting_notes`, timestamps, and people) from the response. Use `filter` to control **which** meeting notes are returned; allowed property names and operators are defined on this endpoint’s [request body schema](/reference/query-meeting-notes).

This endpoint does **not** use cursor-based pagination. There is no `start_cursor` or `next_cursor`—tune `filter`, `sort`, and `limit` (up to the maximum below) to refine the result set.

### Request body

The body is a JSON object; every field is optional.

| Field    | Description                                                                                                                      |
| -------- | -------------------------------------------------------------------------------------------------------------------------------- |
| `filter` | A single **property** filter, or a **combinator** (`"and"` / `"or"`) with a `filters` array. See **Filtering**.                  |
| `sort`   | Ordered list of sorts. Each entry has `property` and `direction` (`ascending` or `descending`). Earlier entries take precedence. |
| `limit`  | Maximum number of meeting notes to return. **Integer** from **1** to **50**. If omitted, the server uses **50**.                 |

<CodeGroup>
  ```json Default (implicit limit 50) theme={null}
  {}
  ```

  ```json Sort and cap results theme={null}
  {
    "sort": [
      { "property": "last_edited_time", "direction": "descending" }
    ],
    "limit": 10
  }
  ```
</CodeGroup>

### Filtering

A **filter** is either:

1. **Property filter (single condition)** — an object with `property` and `filter` (operator and optional `value`) at the **root** of the `filter` field.
2. **Combinator** — an object with `operator` (`"and"` or `"or"`) and a `filters` array. Each array element is another property filter or, for one level of nesting, a combinator whose inner `filters` are **property** filters only (see the [request schema](/reference/query-meeting-notes) in the API reference for the exact shape).

Property names, operators, and `value` shapes for text, date, and person filters are fully specified in the [request body schema](/reference/query-meeting-notes). Invalid properties or malformed filters return a **400** validation error.

### Filter examples

Three patterns below cover a **single** property filter, an **`and`** combinator, and an **`or`** combinator. For more properties and operators, use the schema link above. Replace sample strings and UUIDs with your own.

<CodeGroup>
  ```json Single property (title) theme={null}
  {
    "filter": {
      "property": "title",
      "filter": {
        "operator": "string_contains",
        "value": { "type": "exact", "value": "standup" }
      }
    }
  }
  ```

  ```json Combinator: and theme={null}
  {
    "filter": {
      "operator": "and",
      "filters": [
        {
          "property": "title",
          "filter": {
            "operator": "string_contains",
            "value": { "type": "exact", "value": "planning" }
          }
        },
        {
          "property": "attendees",
          "filter": { "operator": "is_not_empty" }
        }
      ]
    }
  }
  ```

  ```json Combinator: or, with sort and limit theme={null}
  {
    "filter": {
      "operator": "or",
      "filters": [
        {
          "property": "title",
          "filter": {
            "operator": "string_contains",
            "value": { "type": "exact", "value": "standup" }
          }
        },
        {
          "property": "title",
          "filter": {
            "operator": "string_contains",
            "value": { "type": "exact", "value": "sprint" }
          }
        }
      ]
    },
    "sort": [
      { "property": "last_edited_time", "direction": "descending" }
    ],
    "limit": 20
  }
  ```
</CodeGroup>

### Sorting

Each sort item has `property` and `direction` (`ascending` or `descending`). Property names are the same set as in the request body schema. **Earlier entries take precedence** when multiple sorts are present.

```json theme={null}
{
  "sort": [
    { "property": "last_edited_time", "direction": "descending" },
    { "property": "title", "direction": "ascending" }
  ]
}
```

### Response shape

Each item in `results` is a meeting note block with a `meeting_notes` object plus the usual block metadata (see the response schema for this endpoint).

<Info>
  **Integration capabilities**

  This endpoint requires an integration with **Read content**. The workspace must include **AI meeting notes** for the integration’s user; otherwise the call returns a validation error. See the [capabilities guide](/reference/capabilities).
</Info>

### Errors

Returns a 400 HTTP response if AI meeting notes aren't available for the integration's user, or if the filter or sort is invalid.

Returns a 400 or a 429 HTTP response if the request exceeds the [request limits](/reference/request-limits).

<Danger>
  **Note**: Each Public API endpoint can return several possible error codes. See the [Error codes section](/reference/status-codes#error-codes) of the Status codes documentation for more information.
</Danger>


## OpenAPI

````yaml post /v1/blocks/meeting_notes/query
openapi: 3.1.0
info:
  title: Notion API
  version: 1.0.0
  termsOfService: >-
    https://notion.notion.site/Terms-and-Privacy-28ffdd083dc3473e9c2da6ec011b58ac
servers:
  - url: https://api.notion.com
security:
  - bearerAuth: []
tags:
  - name: Databases
    description: Database endpoints
  - name: Data sources
    description: Data source endpoints
  - name: Pages
    description: Page endpoints
  - name: Blocks
    description: Block endpoints
  - name: Comments
    description: Comment endpoints
  - name: File uploads
    description: File upload endpoints
  - name: OAuth
    description: OAuth endpoints (basic authentication)
  - name: Users
    description: User endpoints
  - name: Search
    description: Search endpoints
  - name: Views
    description: View endpoints
  - name: Custom emojis
    description: Custom emoji endpoints
  - name: Meeting notes
    description: Meeting notes endpoints
paths:
  /v1/blocks/meeting_notes/query:
    post:
      tags:
        - Meeting notes
      summary: Query meeting notes
      operationId: query-meeting-notes
      parameters:
        - $ref: '#/components/parameters/notionVersion'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              type: object
              properties:
                filter:
                  type: object
                  properties:
                    operator:
                      type: string
                      enum:
                        - and
                        - or
                      description: Operator for combinator filters.
                    filters:
                      type: array
                      items:
                        description: >-
                          Meeting notes filter node (combinator or property
                          filter).
                        anyOf:
                          - type: object
                            properties:
                              operator:
                                type: string
                                enum:
                                  - and
                                  - or
                                description: Operator for nested combinator filters.
                              filters:
                                type: array
                                items:
                                  anyOf:
                                    - type: object
                                      properties:
                                        property:
                                          type: string
                                          description: Property name.
                                        filter:
                                          type: object
                                          properties:
                                            operator:
                                              type: string
                                              description: Operator.
                                            value:
                                              description: Value for the operator.
                                              anyOf:
                                                - type: object
                                                  description: Single date/datetime filter value.
                                                  properties:
                                                    type:
                                                      type: string
                                                      enum:
                                                        - relative
                                                        - exact
                                                    value:
                                                      anyOf:
                                                        - type: string
                                                        - type: object
                                                          properties:
                                                            type:
                                                              type: string
                                                              enum:
                                                                - date
                                                                - datetime
                                                            start_date:
                                                              type: string
                                                            start_time:
                                                              type: string
                                                            time_zone:
                                                              type: string
                                                          required:
                                                            - type
                                                            - start_date
                                                  required:
                                                    - type
                                                    - value
                                                - type: object
                                                  description: Date range filter value.
                                                  properties:
                                                    type:
                                                      type: string
                                                      enum:
                                                        - relative
                                                        - exact
                                                    value:
                                                      anyOf:
                                                        - type: string
                                                        - type: object
                                                          properties:
                                                            type:
                                                              type: string
                                                              enum:
                                                                - daterange
                                                            start_date:
                                                              type: string
                                                            end_date:
                                                              type: string
                                                          required:
                                                            - type
                                                            - start_date
                                                    direction:
                                                      type: string
                                                      enum:
                                                        - past
                                                        - future
                                                    unit:
                                                      type: string
                                                      enum:
                                                        - day
                                                        - week
                                                        - month
                                                        - year
                                                    count:
                                                      type: number
                                                  required:
                                                    - type
                                                    - value
                                                - type: object
                                                  description: >-
                                                    Text filter value for string_contains
                                                    and similar operators.
                                                  properties:
                                                    type:
                                                      type: string
                                                      enum:
                                                        - exact
                                                    value:
                                                      type: string
                                                      description: The text value to filter on.
                                                  required:
                                                    - type
                                                    - value
                                                - type: array
                                                  description: >-
                                                    Array of person references for
                                                    person_contains/person_does_not_contain
                                                    filters.
                                                  items:
                                                    type: object
                                                    properties:
                                                      type:
                                                        type: string
                                                        enum:
                                                          - exact
                                                      value:
                                                        type: object
                                                        properties:
                                                          table:
                                                            type: string
                                                            enum:
                                                              - notion_user
                                                          id:
                                                            type: string
                                                        required:
                                                          - table
                                                          - id
                                                    required:
                                                      - type
                                                      - value
                                          required:
                                            - operator
                                      required:
                                        - property
                                        - filter
                                    - type: object
                                      properties:
                                        operator:
                                          type: string
                                          enum:
                                            - and
                                            - or
                                          description: Operator for nested combinator filters.
                                        filters:
                                          type: array
                                          items:
                                            anyOf:
                                              - type: object
                                                properties:
                                                  property:
                                                    type: string
                                                    description: Property name.
                                                  filter:
                                                    type: object
                                                    properties:
                                                      operator:
                                                        type: string
                                                        description: Operator.
                                                      value:
                                                        description: Value for the operator.
                                                        anyOf:
                                                          - type: object
                                                            description: Single date/datetime filter value.
                                                            properties:
                                                              type:
                                                                type: string
                                                                enum:
                                                                  - relative
                                                                  - exact
                                                              value:
                                                                anyOf:
                                                                  - type: string
                                                                  - type: object
                                                                    properties:
                                                                      type: {}
                                                                      start_date: {}
                                                                      start_time: {}
                                                                      time_zone: {}
                                                                    required:
                                                                      - type
                                                                      - start_date
                                                            required:
                                                              - type
                                                              - value
                                                          - type: object
                                                            description: Date range filter value.
                                                            properties:
                                                              type:
                                                                type: string
                                                                enum:
                                                                  - relative
                                                                  - exact
                                                              value:
                                                                anyOf:
                                                                  - type: string
                                                                  - type: object
                                                                    properties:
                                                                      type: {}
                                                                      start_date: {}
                                                                      end_date: {}
                                                                    required:
                                                                      - type
                                                                      - start_date
                                                              direction:
                                                                type: string
                                                                enum:
                                                                  - past
                                                                  - future
                                                              unit:
                                                                type: string
                                                                enum:
                                                                  - day
                                                                  - week
                                                                  - month
                                                                  - year
                                                              count:
                                                                type: number
                                                            required:
                                                              - type
                                                              - value
                                                          - type: object
                                                            description: >-
                                                              Text filter value for string_contains
                                                              and similar operators.
                                                            properties:
                                                              type:
                                                                type: string
                                                                enum:
                                                                  - exact
                                                              value:
                                                                type: string
                                                                description: The text value to filter on.
                                                            required:
                                                              - type
                                                              - value
                                                          - type: array
                                                            description: >-
                                                              Array of person references for
                                                              person_contains/person_does_not_contain
                                                              filters.
                                                            items:
                                                              type: object
                                                              properties:
                                                                type:
                                                                  type: string
                                                                  enum:
                                                                    - exact
                                                                value:
                                                                  type: object
                                                                  properties:
                                                                    table:
                                                                      type: {}
                                                                      enum: {}
                                                                    id:
                                                                      type: {}
                                                                  required:
                                                                    - table
                                                                    - id
                                                              required:
                                                                - type
                                                                - value
                                                    required:
                                                      - operator
                                                required:
                                                  - property
                                                  - filter
                                      required:
                                        - operator
                                        - filters
                                description: Nested filters for combinator filters.
                            required:
                              - operator
                              - filters
                          - type: object
                            properties:
                              property:
                                type: string
                                description: Property name.
                              filter:
                                type: object
                                properties:
                                  operator:
                                    type: string
                                    description: Operator.
                                  value:
                                    description: Value for the operator.
                                    anyOf:
                                      - type: object
                                        description: Single date/datetime filter value.
                                        properties:
                                          type:
                                            type: string
                                            enum:
                                              - relative
                                              - exact
                                          value:
                                            anyOf:
                                              - type: string
                                              - type: object
                                                properties:
                                                  type:
                                                    type: string
                                                    enum:
                                                      - date
                                                      - datetime
                                                  start_date:
                                                    type: string
                                                  start_time:
                                                    type: string
                                                  time_zone:
                                                    type: string
                                                required:
                                                  - type
                                                  - start_date
                                        required:
                                          - type
                                          - value
                                      - type: object
                                        description: Date range filter value.
                                        properties:
                                          type:
                                            type: string
                                            enum:
                                              - relative
                                              - exact
                                          value:
                                            anyOf:
                                              - type: string
                                              - type: object
                                                properties:
                                                  type:
                                                    type: string
                                                    enum:
                                                      - daterange
                                                  start_date:
                                                    type: string
                                                  end_date:
                                                    type: string
                                                required:
                                                  - type
                                                  - start_date
                                          direction:
                                            type: string
                                            enum:
                                              - past
                                              - future
                                          unit:
                                            type: string
                                            enum:
                                              - day
                                              - week
                                              - month
                                              - year
                                          count:
                                            type: number
                                        required:
                                          - type
                                          - value
                                      - type: object
                                        description: >-
                                          Text filter value for string_contains
                                          and similar operators.
                                        properties:
                                          type:
                                            type: string
                                            enum:
                                              - exact
                                          value:
                                            type: string
                                            description: The text value to filter on.
                                        required:
                                          - type
                                          - value
                                      - type: array
                                        description: >-
                                          Array of person references for
                                          person_contains/person_does_not_contain
                                          filters.
                                        items:
                                          type: object
                                          properties:
                                            type:
                                              type: string
                                              enum:
                                                - exact
                                            value:
                                              type: object
                                              properties:
                                                table:
                                                  type: string
                                                  enum:
                                                    - notion_user
                                                id:
                                                  type: string
                                              required:
                                                - table
                                                - id
                                          required:
                                            - type
                                            - value
                                required:
                                  - operator
                            required:
                              - property
                              - filter
                      maxItems: 100
                      description: >-
                        Nested filters; each may be a combinator (and/or) or
                        property filter.
                  required:
                    - operator
                  description: >-
                    Optional filter for querying meeting notes. Supports
                    combinator (and/or) and property filters on title,
                    attendees, created_time, created_by, last_edited_time,
                    last_edited_by.
                sort:
                  type: array
                  items:
                    type: object
                    properties:
                      property:
                        type: string
                        enum:
                          - title
                          - attendees
                          - created_time
                          - created_by
                          - last_edited_time
                          - last_edited_by
                        description: Property name to sort by.
                      direction:
                        type: string
                        enum:
                          - ascending
                          - descending
                        description: Sort direction. Must be 'ascending' or 'descending'.
                    required:
                      - property
                      - direction
                  maxItems: 100
                  description: >-
                    Optional sort order for the results. Each entry specifies a
                    property name and direction.
                limit:
                  type: integer
                  minimum: 1
                  maximum: 50
                  description: Maximum number of results to return. Defaults to 50.
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                type: object
                properties:
                  results:
                    type: array
                    items:
                      type: object
                      properties:
                        object:
                          type: string
                          const: block
                          description: Always "block".
                        id:
                          $ref: '#/components/schemas/idResponse'
                          description: The ID of the meeting note block.
                        type:
                          type: string
                          const: meeting_notes
                          description: Always "meeting_notes".
                        meeting_notes:
                          type: object
                          properties:
                            title:
                              type: array
                              items:
                                $ref: '#/components/schemas/richTextItemResponse'
                              maxItems: 100
                              description: Title of the meeting note as rich text.
                            status:
                              type: string
                              enum:
                                - transcription_not_started
                                - transcription_paused
                                - transcription_in_progress
                                - summary_in_progress
                                - notes_ready
                              description: >-
                                Current processing status of the meeting note
                                transcription.
                            children:
                              type: object
                              properties:
                                summary_block_id:
                                  $ref: '#/components/schemas/idResponse'
                                  description: Block ID of the AI summary tab.
                                notes_block_id:
                                  $ref: '#/components/schemas/idResponse'
                                  description: Block ID of the meeting notes tab.
                                transcript_block_id:
                                  $ref: '#/components/schemas/idResponse'
                                  description: Block ID of the transcript tab.
                              additionalProperties: false
                              description: >-
                                Block IDs for each tab (summary, notes,
                                transcript).
                            calendar_event:
                              type: object
                              properties:
                                start_time:
                                  type: string
                                  description: ISO-8601 start time of the calendar event.
                                end_time:
                                  type: string
                                  description: ISO-8601 end time of the calendar event.
                                attendees:
                                  type: array
                                  items:
                                    $ref: '#/components/schemas/idResponse'
                                  maxItems: 100
                                  description: List of attendee user IDs.
                              additionalProperties: false
                              required:
                                - start_time
                                - end_time
                              description: >-
                                Calendar event metadata associated with this
                                meeting note.
                            recording:
                              type: object
                              properties:
                                start_time:
                                  type: string
                                  description: >-
                                    ISO-8601 timestamp when the recording
                                    started.
                                end_time:
                                  type: string
                                  description: ISO-8601 timestamp when the recording ended.
                              additionalProperties: false
                              description: Start and end times of the actual recording.
                          additionalProperties: false
                          description: Meeting note content fields.
                        created_time:
                          type: string
                          description: >-
                            ISO-8601 timestamp when this meeting note was
                            created.
                        last_edited_time:
                          type: string
                          description: >-
                            ISO-8601 timestamp when this meeting note was last
                            edited.
                        created_by:
                          $ref: '#/components/schemas/partialUserObjectResponse'
                          description: User who created this meeting note.
                        last_edited_by:
                          $ref: '#/components/schemas/partialUserObjectResponse'
                          description: User who last edited this meeting note.
                        has_children:
                          type: boolean
                          description: Whether this block has child blocks.
                        in_trash:
                          type: boolean
                          description: Whether this meeting note is in the trash.
                      additionalProperties: false
                      required:
                        - object
                        - id
                        - type
                        - meeting_notes
                        - created_time
                        - last_edited_time
                        - created_by
                        - last_edited_by
                        - has_children
                        - in_trash
                    maxItems: 100
                    description: Meeting note transcription block objects.
                  has_more:
                    type: boolean
                    description: >-
                      Whether additional results exist beyond the returned
                      limit.
                additionalProperties: false
                required:
                  - results
                  - has_more
        '400':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_400'
        '401':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_401'
        '403':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_403'
        '404':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_404'
        '409':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_409'
        '429':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_429'
        '500':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_500'
        '503':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_503'
        '504':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_504'
        '529':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/error_api_529'
      x-codeSamples:
        - lang: javascript
          label: TypeScript SDK
          source: |-
            import { Client } from "@notionhq/client"

            const notion = new Client({ auth: process.env.NOTION_API_KEY })

            const response = await notion.blocks.meetingNotes.query({
              filter: {
                operator: "and",
                filters: [
                  {
                    property: "title",
                    filter: {
                      operator: "string_contains",
                      value: {
                        type: "exact",
                        value: "Weekly sync"
                      }
                    }
                  },
                  {
                    property: "attendees",
                    filter: {
                      operator: "is_not_empty"
                    }
                  }
                ]
              },
              sort: [
                {
                  property: "created_time",
                  direction: "descending"
                }
              ],
              limit: 10
            })
components:
  parameters:
    notionVersion:
      name: Notion-Version
      in: header
      required: true
      schema:
        enum:
          - '2026-03-11'
      description: >-
        The [API version](/reference/versioning) to use for this request. The
        latest version is `2026-03-11`.
  schemas:
    idResponse:
      type: string
      format: uuid
    richTextItemResponse:
      allOf:
        - $ref: '#/components/schemas/richTextItemResponseCommon'
        - oneOf:
            - $ref: '#/components/schemas/textRichTextItemResponse'
            - $ref: '#/components/schemas/mentionRichTextItemResponse'
            - $ref: '#/components/schemas/equationRichTextItemResponse'
    partialUserObjectResponse:
      type: object
      properties:
        id:
          $ref: '#/components/schemas/idResponse'
        object:
          type: string
          const: user
          description: Always `user`
      additionalProperties: false
      required:
        - id
        - object
    error_api_400:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - invalid_json
                - invalid_request_url
                - invalid_request
                - missing_version
                - validation_error
            status:
              const: 400
          required:
            - code
            - status
          additionalProperties: false
    error_api_401:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - unauthorized
            status:
              const: 401
          required:
            - code
            - status
          additionalProperties: false
    error_api_403:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - restricted_resource
            status:
              const: 403
          required:
            - code
            - status
          additionalProperties: false
    error_api_404:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - object_not_found
            status:
              const: 404
          required:
            - code
            - status
          additionalProperties: false
    error_api_409:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - conflict_error
                - row_limit_exceeded
            status:
              const: 409
          required:
            - code
            - status
          additionalProperties: false
    error_api_429:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - rate_limited
            status:
              const: 429
          required:
            - code
            - status
          additionalProperties: false
    error_api_500:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - internal_server_error
            status:
              const: 500
          required:
            - code
            - status
          additionalProperties: false
    error_api_503:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - service_unavailable
            status:
              const: 503
          required:
            - code
            - status
          additionalProperties: false
    error_api_504:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - gateway_timeout
            status:
              const: 504
          required:
            - code
            - status
          additionalProperties: false
    error_api_529:
      allOf:
        - $ref: '#/components/schemas/publicApiCommonErrorResponse'
        - type: object
          properties:
            code:
              enum:
                - service_overload
            status:
              const: 529
          required:
            - code
            - status
          additionalProperties: false
    richTextItemResponseCommon:
      type: object
      properties:
        plain_text:
          type: string
          description: The plain text content of the rich text object, without any styling.
        href:
          oneOf:
            - type: string
            - type: 'null'
          description: A URL that the rich text object links to or mentions.
        annotations:
          $ref: '#/components/schemas/annotationResponse'
          description: >-
            All rich text objects contain an annotations object that sets the
            styling for the rich text.
      additionalProperties: false
      required:
        - plain_text
        - href
        - annotations
    textRichTextItemResponse:
      type: object
      properties:
        type:
          type: string
          const: text
          description: Always `text`
        text:
          type: object
          properties:
            content:
              type: string
              maxLength: 2000
              description: The actual text content of the text.
            link:
              oneOf:
                - type: object
                  properties:
                    url:
                      type: string
                      examples:
                        - https://www.notion.com
                      description: The URL of the link.
                  additionalProperties: false
                  required:
                    - url
                - type: 'null'
              description: >-
                An object with information about any inline link in this text,
                if included.
          additionalProperties: false
          required:
            - content
            - link
          description: >-
            If a rich text object's type value is `text`, then the corresponding
            text field contains an object including the text content and any
            inline link.
      required:
        - type
        - text
      title: Text
    mentionRichTextItemResponse:
      type: object
      properties:
        type:
          type: string
          const: mention
          description: Always `mention`
        mention:
          oneOf:
            - type: object
              properties:
                type:
                  type: string
                  const: user
                  description: Always `user`
                user:
                  $ref: '#/components/schemas/userValueResponse'
                  description: Details of the user mention.
              additionalProperties: false
              required:
                - type
                - user
              title: User
            - type: object
              properties:
                type:
                  type: string
                  const: date
                  description: Always `date`
                date:
                  $ref: '#/components/schemas/dateResponse'
                  description: Details of the date mention.
              additionalProperties: false
              required:
                - type
                - date
              title: Date
            - type: object
              properties:
                type:
                  type: string
                  const: link_preview
                  description: Always `link_preview`
                link_preview:
                  $ref: '#/components/schemas/linkPreviewMentionResponse'
                  description: Details of the link preview mention.
              additionalProperties: false
              required:
                - type
                - link_preview
              title: Link Preview
            - type: object
              properties:
                type:
                  type: string
                  const: link_mention
                  description: Always `link_mention`
                link_mention:
                  $ref: '#/components/schemas/linkMentionResponse'
                  description: Details of the link mention.
              additionalProperties: false
              required:
                - type
                - link_mention
              title: Link Mention
            - type: object
              properties:
                type:
                  type: string
                  const: page
                  description: Always `page`
                page:
                  type: object
                  properties:
                    id:
                      $ref: '#/components/schemas/idResponse'
                      description: The ID of the page in the mention.
                  additionalProperties: false
                  required:
                    - id
                  description: Details of the page mention.
              additionalProperties: false
              required:
                - type
                - page
              title: Page
            - type: object
              properties:
                type:
                  type: string
                  const: database
                  description: Always `database`
                database:
                  type: object
                  properties:
                    id:
                      $ref: '#/components/schemas/idResponse'
                      description: The ID of the database in the mention.
                  additionalProperties: false
                  required:
                    - id
                  description: Details of the database mention.
              additionalProperties: false
              required:
                - type
                - database
              title: Database
            - type: object
              properties:
                type:
                  type: string
                  const: template_mention
                  description: Always `template_mention`
                template_mention:
                  $ref: '#/components/schemas/templateMentionResponse'
                  description: Details of the template mention.
              additionalProperties: false
              required:
                - type
                - template_mention
              title: Template Mention
            - type: object
              properties:
                type:
                  type: string
                  const: custom_emoji
                  description: Always `custom_emoji`
                custom_emoji:
                  $ref: '#/components/schemas/customEmojiResponse'
                  description: Details of the custom emoji mention.
              additionalProperties: false
              required:
                - type
                - custom_emoji
              title: Custom Emoji
          description: >-
            Mention objects represent an inline mention of a database, date,
            link preview mention, page, template mention, or user. A mention is
            created in the Notion UI when a user types `@` followed by the name
            of the reference.
      required:
        - type
        - mention
      title: Mention
    equationRichTextItemResponse:
      type: object
      properties:
        type:
          type: string
          const: equation
          description: Always `equation`
        equation:
          type: object
          properties:
            expression:
              type: string
              examples:
                - e=mc^2
              description: A KaTeX compatible string.
          additionalProperties: false
          required:
            - expression
          description: >-
            Notion supports inline LaTeX equations as rich text objects with a
            type value of `equation`.
      required:
        - type
        - equation
      title: Equation
    publicApiCommonErrorResponse:
      type: object
      properties:
        object:
          const: error
        message:
          type: string
        additional_data:
          type: object
          additionalProperties:
            oneOf:
              - type: string
              - type: array
                items:
                  type: string
      required:
        - object
        - message
    annotationResponse:
      type: object
      properties:
        bold:
          type: boolean
        italic:
          type: boolean
        strikethrough:
          type: boolean
        underline:
          type: boolean
        code:
          type: boolean
        color:
          $ref: '#/components/schemas/apiColor'
      additionalProperties: false
      required:
        - bold
        - italic
        - strikethrough
        - underline
        - code
        - color
    userValueResponse:
      oneOf:
        - $ref: '#/components/schemas/partialUserObjectResponse'
        - $ref: '#/components/schemas/userObjectResponse'
    dateResponse:
      type: object
      properties:
        start:
          type: string
          format: date
          description: The start date of the date object.
        end:
          oneOf:
            - type: string
              format: date
            - type: 'null'
          description: The end date of the date object, if any.
        time_zone:
          oneOf:
            - $ref: '#/components/schemas/timeZoneRequest'
            - type: 'null'
          description: The time zone of the date object.
      additionalProperties: false
      required:
        - start
        - end
        - time_zone
    linkPreviewMentionResponse:
      type: object
      properties:
        url:
          type: string
          description: The URL of the link preview mention.
      additionalProperties: false
      required:
        - url
    linkMentionResponse:
      type: object
      properties:
        href:
          type: string
          description: The href of the link mention.
        title:
          type: string
          description: The title of the link.
        description:
          type: string
          description: The description of the link.
        link_author:
          type: string
          description: The author of the link.
        link_provider:
          type: string
          description: The provider of the link.
        thumbnail_url:
          type: string
          description: The thumbnail URL of the link.
        icon_url:
          type: string
          description: The icon URL of the link.
        iframe_url:
          type: string
          description: The iframe URL of the link.
        height:
          type: integer
          description: The height of the link preview iframe.
        padding:
          type: integer
          description: The padding of the link preview iframe.
        padding_top:
          type: integer
          description: The top padding of the link preview iframe.
      additionalProperties: false
      required:
        - href
    templateMentionResponse:
      oneOf:
        - $ref: '#/components/schemas/templateMentionDateTemplateMentionResponse'
        - $ref: '#/components/schemas/templateMentionUserTemplateMentionResponse'
    customEmojiResponse:
      type: object
      properties:
        id:
          $ref: '#/components/schemas/idResponse'
          description: The ID of the custom emoji.
        name:
          type: string
          description: The name of the custom emoji.
        url:
          type: string
          description: The URL of the custom emoji.
      additionalProperties: false
      required:
        - id
        - name
        - url
    apiColor:
      type: string
      enum:
        - default
        - gray
        - brown
        - orange
        - yellow
        - green
        - blue
        - purple
        - pink
        - red
        - default_background
        - gray_background
        - brown_background
        - orange_background
        - yellow_background
        - green_background
        - blue_background
        - purple_background
        - pink_background
        - red_background
      description: >-
        One of: `default`, `gray`, `brown`, `orange`, `yellow`, `green`, `blue`,
        `purple`, `pink`, `red`, `default_background`, `gray_background`,
        `brown_background`, `orange_background`, `yellow_background`,
        `green_background`, `blue_background`, `purple_background`,
        `pink_background`, `red_background`
    userObjectResponse:
      allOf:
        - $ref: '#/components/schemas/userObjectResponseCommon'
        - oneOf:
            - $ref: '#/components/schemas/personUserObjectResponse'
            - $ref: '#/components/schemas/botUserObjectResponse'
    timeZoneRequest:
      type: string
    templateMentionDateTemplateMentionResponse:
      type: object
      properties:
        type:
          type: string
          const: template_mention_date
          description: Always `template_mention_date`
        template_mention_date:
          type: string
          enum:
            - today
            - now
          description: The date of the template mention.
      additionalProperties: false
      required:
        - type
        - template_mention_date
      title: Template Mention Date
    templateMentionUserTemplateMentionResponse:
      type: object
      properties:
        type:
          type: string
          const: template_mention_user
          description: Always `template_mention_user`
        template_mention_user:
          type: string
          const: me
          description: The user of the template mention.
      additionalProperties: false
      required:
        - type
        - template_mention_user
      title: Template Mention User
    userObjectResponseCommon:
      type: object
      properties:
        id:
          $ref: '#/components/schemas/idResponse'
          description: The ID of the user.
        object:
          type: string
          const: user
          description: The user object type name.
        name:
          oneOf:
            - type: string
            - type: 'null'
          description: The name of the user.
        avatar_url:
          oneOf:
            - type: string
            - type: 'null'
          description: The avatar URL of the user.
      additionalProperties: false
      required:
        - id
        - object
        - name
        - avatar_url
    personUserObjectResponse:
      type: object
      properties:
        type:
          type: string
          const: person
          description: Indicates this user is a person.
        person:
          type: object
          properties:
            email:
              type: string
              description: The email of the person.
          additionalProperties: false
          description: Details about the person, when the `type` of the user is `person`.
      required:
        - type
        - person
      title: Person
    botUserObjectResponse:
      type: object
      properties:
        type:
          type: string
          const: bot
          description: Indicates this user is a bot.
        bot:
          oneOf:
            - $ref: '#/components/schemas/emptyObject'
            - $ref: '#/components/schemas/botInfoResponse'
          description: Details about the bot, when the `type` of the user is `bot`.
      required:
        - type
        - bot
      title: Bot
    emptyObject:
      type: object
      properties: {}
      additionalProperties: false
    botInfoResponse:
      type: object
      properties:
        owner:
          oneOf:
            - type: object
              properties:
                type:
                  type: string
                  const: user
                  description: Always `user`
                user:
                  oneOf:
                    - type: object
                      properties:
                        id:
                          $ref: '#/components/schemas/idResponse'
                          description: The ID of the user.
                        object:
                          type: string
                          const: user
                          description: The user object type name.
                        name:
                          oneOf:
                            - type: string
                            - type: 'null'
                          description: The name of the user.
                        avatar_url:
                          oneOf:
                            - type: string
                            - type: 'null'
                          description: The avatar URL of the user.
                        type:
                          type: string
                          const: person
                          description: The type of the user.
                        person:
                          type: object
                          properties:
                            email:
                              type: string
                              description: The email of the person.
                          additionalProperties: false
                          description: The person info of the user.
                      additionalProperties: false
                      required:
                        - id
                        - object
                        - name
                        - avatar_url
                        - type
                        - person
                    - $ref: '#/components/schemas/partialUserObjectResponse'
                  description: >-
                    Details about the owner of the bot, when the `type` of the
                    owner is `user`. This means the bot is for a integration.
              additionalProperties: false
              required:
                - type
                - user
              title: User
            - type: object
              properties:
                type:
                  type: string
                  const: workspace
                  description: Always `workspace`
                workspace:
                  type: boolean
                  const: true
                  description: >-
                    Details about the owner of the bot, when the `type` of the
                    owner is `workspace`. This means the bot is for an internal
                    integration.
              additionalProperties: false
              required:
                - type
                - workspace
              title: Workspace
          description: Details about the owner of the bot.
        workspace_id:
          type: string
          description: The ID of the bot's workspace.
        workspace_limits:
          type: object
          properties:
            max_file_upload_size_in_bytes:
              type: integer
              minimum: 0
              description: The maximum allowable size of a file upload, in bytes
          additionalProperties: false
          required:
            - max_file_upload_size_in_bytes
          description: Limits and restrictions that apply to the bot's workspace
        workspace_name:
          oneOf:
            - type: string
            - type: 'null'
          description: The name of the bot's workspace.
      additionalProperties: false
      required:
        - owner
        - workspace_id
        - workspace_limits
        - workspace_name
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````