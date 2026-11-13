
import { McpServer } from "@modelcontextprotocol/server";
import { createMcpHandler } from "agents/mcp/server";

function createServer() {
  const server = new McpServer({
    name: "christian-reels-factory",
    version: "0.1.0",
  });

  server.registerTool(
    "project_status",
    {
      description: "Check the project status.",
      inputSchema: {},
    },
    async () => ({
      content: [
        {
          type: "text",
          text: "Christian Reels Factory MCP server is running.",
        },
      ],
    })
  );

  return server;
}

const handler = createMcpHandler(createServer);

export default {
  fetch(request, env, ctx) {
    return handler(request, env, ctx);
  },
} satisfies ExportedHandler;
