> Execute a view's query and return the first page of results.

# Create a view query

Executes the view's filter and sort configuration against its data source, caches the full result set, and returns the first page of page references along with a `query_id` for [paginating through results](/reference/get-view-query-results).

Cached results expire after 15 minutes. Use the `expires_at` field to check when the cache will be invalidated.

<Info>
  **Connection capabilities**

  This endpoint requires a connection to have read content capabilities. For more information on connection capabilities, see the [capabilities guide](/reference/capabilities).
</Info>

### Pagination limit

This endpoint caches up to **10,000 results** per query. If the view's filter and sort configuration matches more rows than this limit, the cache will be truncated and the response will include:

```json theme={null}
{
  "request_status": {
    "type": "incomplete",
    "incomplete_reason": "query_result_limit_reached"
  }
}
```

When `request_status.type` is `"incomplete"`, the `total_count` reflects only the truncated cache size (not the full matching row count), and subsequent [paginated requests](/reference/get-view-query-results) will stop once the cache is exhausted.

To work around this limit:

* Narrow the view's filter and sort configuration via [Update a view](/reference/update-a-view) (for example, filter by `last_edited_time` to only include recently changed rows).
* Set up [connection webhooks](/reference/webhooks) to detect changes in real time instead of polling this endpoint.

<Warning>
  **Incremental sync via webhooks**

  If your connection runs this endpoint on a recurring schedule to detect changes, consider switching to [connection webhooks](/reference/webhooks) for incremental sync. Webhooks notify your connection when rows change, removing the need to re-query the view and avoiding the pagination depth limit entirely.
</Warning>

### Errors

Returns a 404 HTTP response if the view doesn't exist, or if the connection doesn't have access.

Returns a 400 or 429 HTTP response if the request exceeds the [request limits](/reference/request-limits).


## OpenAPI

````yaml post /v1/views/{view_id}/queries
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
  /v1/views/{view_id}/queries:
    post:
      tags:
        - Views
      summary: Create a view query
      operationId: create-view-query
      parameters:
        - name: view_id
          in: path
          required: true
          schema:
            $ref: '#/components/schemas/idRequest'
            description: The ID of the view.
        - $ref: '#/components/parameters/notionVersion'
      requestBody:
        required: true
        content:
          application/json:
            schema:
              $ref: '#/components/schemas/createViewQueryRequest'
      responses:
        '200':
          description: ''
          content:
            application/json:
              schema:
                $ref: '#/components/schemas/viewQueryResponse'
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

            const response = await notion.views.queries.create({
              view_id: "a3f1b2c4-5678-4def-abcd-1234567890ab"
            })
components:
  schemas:
    idRequest:
      type: string
    createViewQueryRequest:
      type: object
      properties:
        page_size:
          type: integer
          minimum: 1
          maximum: 100
          description: 'The number of results to return per page. Maximum: 100'
    viewQueryResponse:
      type: object
      properties:
        object:
          type: string
          const: view_query
          description: The object type.
        id:
          $ref: '#/components/schemas/idResponse'
          description: The query ID.
        view_id:
          $ref: '#/components/schemas/idResponse'
          description: The view this query was executed against.
        expires_at:
          type: string
          format: date-time
          description: When the cached query results expire.
        total_count:
          type: number
          description: Total number of results in the query.
        results:
          type: array
          items:
            $ref: '#/components/schemas/pageReferenceResponse'
          maxItems: 100
          description: The page results for this page.
        next_cursor:
          oneOf:
            - $ref: '#/components/schemas/idResponse'
            - type: 'null'
          description: Cursor for the next page of results.
        has_more:
          type: boolean
          description: Whether there are more results.
        request_status:
          $ref: '#/components/schemas/requestStatusResponse'
          description: >-
            Set to `{ type: 'incomplete', incomplete_reason:
            'query_result_limit_reached' }` when the view's underlying data
            source has more rows matching this query than the server-side
            pagination depth limit allows.
      additionalProperties: false
      required:
        - object
        - id
        - view_id
        - expires_at
        - total_count
        - results
        - next_cursor
        - has_more
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
    idResponse:
      type: string
      format: uuid
    pageReferenceResponse:
      type: object
      properties:
        object:
          type: string
          description: The object type.
        id:
          $ref: '#/components/schemas/idResponse'
          description: The object ID.
      additionalProperties: false
      required:
        - object
        - id
    requestStatusResponse:
      type: object
      properties:
        type:
          type: string
          enum:
            - complete
            - incomplete
          description: >-
            Whether the result set is complete or incomplete. `incomplete` means
            the response does not include all rows that match the query
            parameters (e.g. due to a server-side pagination depth limit).
        incomplete_reason:
          type: string
          const: query_result_limit_reached
          description: >-
            Why the result set is incomplete. Only present when `type` is
            `incomplete`.
      additionalProperties: false
      required:
        - type
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
  securitySchemes:
    bearerAuth:
      type: http
      scheme: bearer

````