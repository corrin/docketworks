# Quoting chat

Open **Quoting Chat** on a job. ChatKit supplies the composer, streamed replies,
copy controls, new conversations and paged conversation history. Conversations
are saved against the job and shared with its office users, matching the previous
job-scoped history. Workshop users cannot access the configuration or chat endpoint.

The assistant can read the current job and search stored supplier catalogue prices.
It reports source links, units and recorded dates; catalogue prices are observations,
not live offers. It cannot change estimates, send quotes or place orders. Uploads,
web browsing and voice are not enabled. This is an embedded quoting assistant,
not the full ChatGPT product.

## Configuration

1. Open **Admin → Integrations → AI providers → Add provider** as a superuser.
   Choose OpenAI, give the entry a descriptive name, enter a model identifier available
   to your account and your API key, then save. **Test provider** sends a small billable
   request using that saved entry. Keys are never returned to the browser: editing
   metadata keeps the key, entering a replacement rotates it, and Clear removes it.
2. Select the radio button in **Default** to choose the application default. Code with no preference uses
   this entry. Quoting chat initially selects it and lets users choose any configured
   provider in ChatKit's model picker, including during a conversation. Catalogue parsing
   continues to request Gemini. Among configured models of a requested vendor,
   the application default wins if it matches; otherwise the oldest configured entry wins.
   A caller can select an exact provider row when it needs a specific model.
3. Register the browser hostname (including the development ngrok hostname) in
   [OpenAI’s domain allowlist](https://platform.openai.com/settings/organization/security/domain-allowlist).
   Enter its public domain key in **Admin → Integrations → Quoting chat** and save.
   Ngrok and deployed sites both need their registered key.
   This public embed setting is separate from the secret model API key.
4. Open a job's **Quoting Chat** tab. Missing configuration shows an actionable setup
   message, including an Integrations link for superusers. Test a supplier lookup and
   reopen the conversation from history to check the complete path.

For new instances, the root-owned provisioning credentials support `OPENAI_API_KEY`,
`OPENAI_MODEL_NAME`, optional other vendor keys, `AI_DEFAULT_PROVIDER` and
`CHATKIT_DOMAIN_KEY`. These seed database configuration; application code never reads
model credentials from environment variables. `load_ai_providers` adds missing vendors
independently, preserves existing configured entries and defaults, and refills only an
unambiguous exact empty seed. Incomplete or ambiguous entries require an administrator
choice. OpenAI-only provisioning is supported; Gemini-dependent parsing still requires
Gemini. Reconfiguration does not overwrite keys rotated through the UI.

Migration `ai/0002` enforces at most one application default. Where a database holds
multiple defaults it clears those flags, retaining every model and key, so an administrator
can make the choice. A missing default is reported rather than guessed.

Completed model calls record their reported token usage, wall time in milliseconds and
`estimated_cost_usd` through the existing gateway, one row per model round trip (including
tool requests). LiteLLM calculates the USD estimate from its model prices and reported
usage, including cache reads/writes. This is not a provider invoice or an NZD conversion.
Migration `observability/0002` adds the nullable cost column through normal provisioning
and deployment migrations. Historical rows retain unknown cost; they are not backfilled.
Pricing failures surface as errors rather than recording a misleading zero cost.
Agent calls have the gateway's 120-second request timeout, a 4096-token output limit
and at most eight model turns per submitted message. These limits are not an account
spending budget. Conversations supply the latest 100 stored items as model context;
older messages remain in history. No LangChain or additional gateway service is required.

## Maintenance

GPT: ChatKit owns its wire protocol and conversation UI; Django owns authentication,
CSRF, job scope and durable storage. Its endpoint sits outside Ninja, while embed
configuration uses the generated API client. See ADRs 0021 and 0041.

GPT: The MCP Python SDK generates and executes the read-only tools in process.
The Agents adapter uses that tool contract without a separate service or loopback
credentials. This slice does not expose an independently accessible remote MCP endpoint.

GPT: The tested SDK pair needs two small compatibility adaptations: assistant text
is converted through ChatKit's input-converter extension, and streamed message IDs
are allocated locally because the LiteLLM adapter emits a repeated placeholder ID.
The live multi-turn integration test guards against history rejection and overwrite.
ChatKit's process-local timestamps are made timezone-aware for database indexing;
its own payload keeps the format its workflow-duration code requires.

Migrations 0005–0007 preserve existing message IDs, text, timestamps and metadata
in a conversation named **Previous quoting conversation**. The data migration
refuses rollback once conversations exist. An empty target can still rewind;
a populated database requires the release process's pre-migration backup to roll
back without discarding SDK items into the old text-only schema.

The CLI exercises the same persisted path:

```sh
python manage.py ai_chat_harness JOB_UUID "Find supplier prices for 304 stainless sheet"
python manage.py ai_chat_harness JOB_UUID "What about 1.2mm?" --thread-id THREAD_ID
```

Run the live SDK/tool integration tests and the job-quoting-chat Playwright spec
when upgrading these libraries. The latter checks streaming, reload/history and
1920px, 1366px, 1024px and 390px layouts against the actual embed.
