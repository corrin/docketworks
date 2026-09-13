"""Read-only MCP tools bound to the authenticated job, never a model-supplied id."""

from agents.mcp import MCPServer as AgentMCPServer
from asgiref.sync import sync_to_async
from mcp.server.mcpserver import MCPServer
from mcp.types import CallToolResult, GetPromptResult, ListPromptsResult, Tool
from pydantic import TypeAdapter

from apps.job.chat.store import ChatContext
from apps.job.services.job_service import JobEditData, get_job_summary
from apps.quoting.services.product_search import ProductSearchResult, search_products

JOB_ADAPTER = TypeAdapter(JobEditData)


class QuotingTools(AgentMCPServer):
    """Use the MCP SDK's schema generation, validation and dispatch in process."""

    def __init__(self, context: ChatContext) -> None:
        """Bind a fresh tool server to this request's trusted job scope."""
        super().__init__(failure_error_function=None)
        self.server = MCPServer[None]("DocketWorks quoting")

        @self.server.tool()
        async def job_context() -> str:
            """Read this job's details, estimate/quote totals and configured shop defaults."""
            data = await sync_to_async(get_job_summary)(context.job_id)
            return JOB_ADAPTER.dump_json(data).decode()

        @self.server.tool()
        async def supplier_prices(query: str, offset: int = 0) -> ProductSearchResult:
            """Search stored supplier products by words/code; return prices, units and sources.

            Prices may be unknown or outdated. Never treat a null price as zero.
            Use offset to page through results; refine searches with many matches.
            """
            return await sync_to_async(search_products)(query, offset)

    @property
    def name(self) -> str:
        """Identify this tool collection to the Agents runtime."""
        return "DocketWorks quoting"

    async def connect(self) -> None:
        """No network connection is needed for the request-local MCP SDK server."""

    async def cleanup(self) -> None:
        """Release no external resources: this server is request-local."""

    async def list_tools(self, _run_context: object = None, _agent: object = None) -> list[Tool]:
        """Let the MCP SDK describe the registered Python tools."""
        return await self.server.list_tools()

    async def call_tool(
        self,
        tool_name: str,
        arguments: dict[str, object] | None,
        meta: dict[str, object] | None = None,  # noqa: ARG002 -- GPT: Agents passes this SDK parameter by keyword; tools do not consume client metadata.
    ) -> CallToolResult:
        """Delegate validation and execution to MCP; no hand-written tool dispatcher."""
        result = await self.server.call_tool(tool_name, {} if arguments is None else arguments)
        if not isinstance(result, CallToolResult):
            raise TypeError("Read-only quoting tools must return a completed tool result")
        return result

    async def list_prompts(self) -> ListPromptsResult:
        """Expose no prompts; this server provides tools only."""
        return ListPromptsResult(prompts=[])

    async def get_prompt(
        self, name: str, _arguments: dict[str, object] | None = None
    ) -> GetPromptResult:
        """Refuse prompt lookup rather than inventing an empty prompt."""
        raise ValueError(f"Quoting MCP does not expose prompt {name}")
