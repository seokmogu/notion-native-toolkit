# Notion Internal API Capture Results

Captured: 2026-04-12/13
Target: https://www.notion.so/worxphere/AX-33f7d8322b048046a0adf3bd451fee4f
Method: Playwright headless + Chrome cookie injection
Total unique endpoints: 82 (74 page load + 8 AI action-triggered)

## Key Discovery: saveTransactionsFanout

All write operations in Notion go through a single unified endpoint:

```
POST /api/v3/saveTransactionsFanout
```

Payload structure:

```json
{
  "requestId": "uuid",
  "transactions": [
    {
      "id": "uuid",
      "spaceId": "workspace-id",
      "debug": { "userAction": "description" },
      "operations": [
        {
          "command": "insertText|deleteText|update|set|listAfter|listRemove|...",
          "pointer": { "table": "block|collection|...", "id": "block-id", "spaceId": "..." },
          "path": [],
          "args": { ... }
        }
      ]
    }
  ]
}
```

Known operation commands (from capture + reverse engineering):
- `insertText` — Insert text into a block
- `deleteText` — Remove text from a block
- `update` — Update block/record properties
- `set` — Set a property value
- `listAfter` — Add item to a list (e.g., add child block)
- `listRemove` — Remove item from a list
- `listBefore` — Insert item before another in a list

## Key Discovery: Internal Search

```
POST /api/v3/search
```

Rich search with filters, sorting, and recent page boosting:

```json
{
  "type": "BlocksInSpace",
  "query": "search text",
  "limit": 20,
  "source": "quick_find",
  "filters": {
    "isDeletedOnly": false,
    "excludeTemplates": false,
    "navigableBlockContentOnly": false,
    "requireEditPermissions": false,
    "ancestors": [],
    "createdBy": [],
    "editedBy": [],
    "lastEditedTime": {},
    "createdTime": {},
    "inTeams": [],
    "contentStatusFilter": "all_without_archived"
  },
  "sort": { "field": "relevance" },
  "spaceId": "workspace-id"
}
```

## Captured Endpoints by Module

### AI/Agent (14)

| Endpoint | Type | Response |
|----------|------|----------|
| `getCustomAgents` | READ | agentIds, mostRecentTranscripts, activityScores |
| `listAIConnectors` | READ | connectedConnectors, availableConnectors |
| `getAIConnectorAuthorizationUrl` | READ | authorizationUrl |
| `getAIUsageEligibilityV2` | READ | usage, limits, basicCredits, premiumCredits |
| `getAIUsageEligibility` | READ | isEligible, spaceUsage, spaceLimit, userUsage |
| `getUserPromptsInSpace` | READ | categories, recordMap, usage |
| `detectPageLanguage` | READ | detectedLanguage |
| `isEligibleForLanguageSwitchPrompt` | READ | isEligible |
| `isEmailEducation` | READ | isEligible |
| `getIsMailUser` | READ | isMailUser |
| `getTrustedDomainsForSpace` | READ | results |
| `getEmailDomainSettings` | READ | isDomainVerified, settings |
| `getSpacePermissionGroupIdsContainingMembers` | READ | userToGroupMap |
| `syncRecordValuesMain` | SYNC | recordMap |

### Content/Page (10)

| Endpoint | Type | Response |
|----------|------|----------|
| `loadCachedPageChunkV2` | READ | cursors, recordMap, spaceId |
| `getBacklinksForBlockInitial` | READ | backlinks, recordMap |
| `getSidebarSections` | READ | sidebarSections, recordMap |
| `getUserHomePages` | READ | homePageId, recordMap |
| `getLibraryPage` | READ | libraryPageId, recordMap |
| `getPageVisitors` | READ | pageVisits, totalCount |
| `getPublicPageData` | READ | pageId, spaceName, spaceId |
| `getRecentPageVisits` | READ | pages, spaceRole, recordMap |
| `recordPageVisit` | WRITE | recordMap, pageVisits |
| **`saveTransactionsFanout`** | **WRITE** | (all mutations) |

### Search (4)

| Endpoint | Type | Response |
|----------|------|----------|
| `search` | READ | (results) |
| `searchIntegrations` | READ | integrationIds, recordMap |
| `warmSearchCache` | WRITE | (cache warm) |
| `warmVectorDBCache` | WRITE | (vector cache warm) |

### Workspace/Team (18)

| Endpoint | Type | Response |
|----------|------|----------|
| `getTeamsV2` | READ | teams, recordMap |
| `getSpacesInitial` | READ | users, spaceInaccessiblePages |
| `getSpacesFanout` | READ | users, spaceInaccessiblePages |
| `getAllSpacePermissionGroupsWithMemberCount` | READ | groupsWithMemberCount |
| `getMemberCountsInTeams` | READ | membershipByTeam |
| `getSpaceUserCountsByType` | READ | countsByType |
| `getSpaceBlockUsage` | READ | blockUsage |
| `getPublicSpaceData` | READ | results |
| `getUserSharedPagesInSpace` | READ | pages, recordMap |
| `getUserSpaceExternalBots` | READ | botIds, externalAuthenticationIds |
| `getCustomEmojisForSpace` | READ | recordMap, totalCount |
| `getUserOrganizations` | READ | organizationsInfo |
| `getOrganizationOnboardingInfo` | READ | result |
| `getWorkspaceRecommendations` | READ | results |
| `getTrustedDomainsForSpace` | READ | results |
| `hasJoinableSpaces` | READ | hasJoinableSpaces, joinableSpacesCount |
| `getAllUpgradeRequestsForSpace` | READ | requests |

### Members/Users (12)

| Endpoint | Type | Response |
|----------|------|----------|
| `getVisibleUsers` | READ | users, userSimilarity, joinedMemberIds |
| `getSimilarUsers` | READ | userSimilarity |
| `getExtendedUserProfiles` | READ | profiles |
| `getUserTasks` | READ | taskIds |
| `getUserSignals` | READ | signals, recordMap |
| `getUserNotificationsInitial` | READ | results, recordMap |
| `getUserNotificationsFanout` | READ | results, recordMap |
| `getUnreadInAppMessagesForUser` | READ | messages |
| `getPresenceAuthorizationToken` | READ | presenceAuthorizationToken |
| `getLifecycleUserProfile` | READ | userProfile |
| `getUserAnalyticsSettings` | READ | user_id, user_email, user_name |
| `getIsCalendarUser` | READ | isCalendarUser, calendarEmails |

### Integration (4)

| Endpoint | Type | Response |
|----------|------|----------|
| `getCalendarEvents` | READ | accounts, calendars, events |
| `getExternalIntegrations` | READ | (data) |
| `getExternalOrgData` | READ | (data) |
| `getWebhookSubscriptions` | READ | webhookSubscriptionIds, recordMap |

### Billing/Usage (7)

| Endpoint | Type | Response |
|----------|------|----------|
| `getBillingData` | READ | billingData |
| `getFeatureBillingData` | READ | billingData, overrides |
| `getSubscriptionData` | READ | type, users, members |
| `getSubscriptionBanner` | READ | bannerIds |
| `getTranscriptionUsage` | READ | usage, unit, eligibility |
| `getPossibleOffers` | READ | offerCampaigns |
| `getCustomerOffersReceived` | READ | (data) |

## Key Discovery: Notion AI Execution (runInferenceTranscript)

The core AI endpoint. All Notion AI features (chat, writing, agents) go through this.

```
POST /api/v3/runInferenceTranscript
Response: application/x-ndjson (streaming, newline-delimited JSON)
Response size: ~300KB per interaction
```

### Transcript Payload Structure

The request body contains a `transcript` array with typed entries:

```json
{
  "traceId": "uuid",
  "spaceId": "workspace-id",
  "threadId": "thread-id",
  "createThread": true,
  "generateTitle": true,
  "threadType": "workflow",
  "asPatchResponse": true,
  "transcript": [
    { "id": "...", "type": "config", "value": { ... } },
    { "id": "...", "type": "context", "value": { ... } },
    { "id": "...", "type": "user", "value": [["user prompt"]], "userId": "..." }
  ]
}
```

### Transcript Entry Types

**config** — Feature flags and agent capabilities:
```json
{
  "type": "workflow",
  "enableScriptAgent": true,
  "enableAgentIntegrations": true,
  "enableCustomAgents": true,
  "enableAgentDiffs": true,
  "enableAgentGenerateImage": true,
  "useWebSearch": true,
  "enableScriptAgentSlack": true,
  "enableScriptAgentMail": true,
  "enableScriptAgentCalendar": true,
  "enableScriptAgentMcpServers": false,
  "writerMode": false,
  "isCustomAgent": false,
  "isMobile": false,
  "availableConnectors": ["notion-calendar"],
  "searchScopes": [{ "type": "everything" }]
}
```

**context** — User and workspace context:
```json
{
  "timezone": "Asia/Seoul",
  "userName": "user_name",
  "userId": "user-id",
  "userEmail": "email",
  "spaceName": "workspace name",
  "spaceId": "space-id",
  "currentDatetime": "2026-04-13T00:24:19.687+09:00",
  "surface": "workflows",
  "blockId": "current-page-id",
  "agentName": "하하",
  "agentAccessory": "flower"
}
```

**user** — User message (Notion's rich text format):
```json
{
  "type": "user",
  "value": [["Translate to English"]],
  "userId": "user-id",
  "createdAt": "ISO-timestamp"
}
```

### AI Context via saveTransactionsFanout

When AI is invoked with selected blocks, the context is passed via a separate transaction:
```json
{
  "debug": { "userAction": "WorkflowActions.addStepsToExistingThreadAndRun" },
  "operations": [{
    "command": "set",
    "pointer": { "table": "thread_message", "id": "..." },
    "args": {
      "step": {
        "type": "user-specified-context",
        "value": {
          "blockSelection": {
            "type": "blocks",
            "value": [{ "table": "block", "id": "block-id", "spaceId": "..." }]
          }
        }
      }
    }
  }]
}
```

### Supporting AI Endpoints

| Endpoint | Purpose | Response |
|----------|---------|----------|
| `getAvailableModels` | List AI models for workspace | `{ models: [...] }` |
| `getInferenceTranscriptsForUser` | AI chat history | threads list |
| `getInferenceTranscriptsUnreadCount` | Unread AI chat count | `{ count }` |
| `markInferenceTranscriptSeen` | Mark AI thread as read | `{ ok }` |
| `warmScriptAgentDynamicModuleCache` | Warm agent module cache | (warm) |
| `getAssetsJsonV2` | Asset manifest | (hash-based) |

### AI Feature Flags Discovered

From the config transcript entry, these feature flags control Notion AI behavior:

- `enableScriptAgent` — Core agent execution
- `enableAgentIntegrations` — Slack, Mail, Calendar integrations
- `enableCustomAgents` — User-created custom agents
- `enableAgentDiffs` — Diff-based page editing
- `enableAgentGenerateImage` — Image generation
- `enableScriptAgentMcpServers` — MCP server support (currently disabled)
- `enableCrdtOperations` — CRDT-based collaborative editing
- `enableDatabaseAgents` — Database-specific agents (currently disabled)
- `useWebSearch` — Web search capability
- `writerMode` — Writing-focused mode
- `yoloMode` — Auto-execute without confirmation

## Not Yet Captured (requires interactive browser actions)

These endpoints were not triggered by automated headless browsing.
They require headed mode with proper UI element interaction.

| Feature | Expected Endpoint | Trigger |
|---------|------------------|---------|
| AI Autofill on DB property | `runInferenceTranscript` with autofill config | Click AI autofill cell |
| Guest invite | `inviteGuestsToSpace` | Share modal → type email → invite |
| Permission change | `setPermissions` or `saveTransactionsFanout` | Change page/DB permissions |
| DB row CRUD | `saveTransactionsFanout` (set/listAfter) | Add/edit/delete DB row |
| DB filter/sort/group | `saveTransactionsFanout` (collection_view update) | Change view settings |
| Integration token create | `createBotToken` or similar | Create internal integration |
| Import/Export | `exportBlock` / `enqueueTask` | Export page/DB |
| Duplicate page | `saveTransactionsFanout` (duplicateBlock) | Duplicate page |

## Common Request Pattern

All internal API calls share:
- Base URL: `https://www.notion.so/api/v3/{endpoint}`
- Method: POST (always)
- Auth: `token_v2` cookie
- Content-Type: application/json
- Key headers: `x-notion-active-user-header`, `x-notion-space-id`

## Auth Requirements

- `token_v2` cookie (from browser session)
- `notion_user_id` cookie
- Space ID (workspace identifier)
- User ID (for user-scoped requests)

These are NOT OAuth tokens — they are browser session cookies.
The official API uses bearer tokens; the internal API uses cookie-based auth.
