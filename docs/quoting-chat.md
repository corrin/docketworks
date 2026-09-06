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

1. Register the deployed domain in the OpenAI account's ChatKit domain allowlist.
   Enter the public domain key in **Admin → Integrations → Quoting chat**.
   Localhost development can use `local-dev`; deployed sites need their registered key.
2. Configure the desired model and API credentials in the existing `AIProvider`
   table, with exactly one provider marked default. Quoting chat uses that default;
   supplier parsing continues to use its existing configured parsing provider.
   An OpenAI model requires an OpenAI provider row and the owner's API key.
   Credentials stay in the database and never enter the embed.
3. Server provisioning can load `chatkit_domain_key` through the existing integration
   settings fixture. The corresponding root-owned provisioning value is
   `CHATKIT_DOMAIN_KEY`; it is not a new application environment credential.

Completed model calls record their reported token usage through the existing gateway.
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

Migrations 0005–0007 preserve existing message IDs, text, timestamps and legacy
metadata in a conversation named **Previous quoting conversation**. The data
migration refuses rollback once conversations exist. Empty targets can rewind for
v1 imports; populated databases require the release process's pre-migration backup
to roll back without discarding SDK items into the old text-only schema.

The CLI exercises the same persisted path:

```sh
python manage.py ai_chat_harness JOB_UUID "Find supplier prices for 304 stainless sheet"
python manage.py ai_chat_harness JOB_UUID "What about 1.2mm?" --thread-id THREAD_ID
```

Run the live SDK/tool integration tests and the job-quoting-chat Playwright spec
when upgrading these libraries. The latter checks streaming, reload/history and
1920px, 1366px, 1024px and 390px layouts against the actual embed.
