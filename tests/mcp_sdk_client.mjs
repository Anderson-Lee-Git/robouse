// Conformance check of `robo mcp` against the official MCP TypeScript SDK client (@modelcontextprotocol/client).
// usage: node mcp_sdk_client.mjs <sdk-client-dir> stdio <python> <robo-script>   (ROBOUSE_SOCKET in the environment)
//        node mcp_sdk_client.mjs <sdk-client-dir> http <url>
// Prints one JSON line with what it saw; exits non-zero on any protocol error.
import { pathToFileURL } from "node:url";
import { join } from "node:path";

const [sdkDir, mode, ...rest] = process.argv.slice(2);
const load = (p) => import(pathToFileURL(join(sdkDir, p)).href);
const { Client, StreamableHTTPClientTransport } = await load("dist/index.mjs");
let transport;
if (mode === "stdio") {
  const { StdioClientTransport } = await load("dist/stdio.mjs");
  transport = new StdioClientTransport({
    command: rest[0],
    args: [rest[1], "mcp"],
    env: { ROBOUSE_SOCKET: process.env.ROBOUSE_SOCKET, PATH: process.env.PATH },
  });
} else {
  transport = new StreamableHTTPClientTransport(new URL(rest[0]));
}
const client = new Client({ name: "sdk-conformance", version: "1.0.0" });
await client.connect(transport);
const out = {
  server: client.getServerVersion(),
  protocol: transport.protocolVersion ?? null,
  capabilities: client.getServerCapabilities(),
  instructions: !!client.getInstructions(),
};
await client.ping();
const tools = (await client.listTools()).tools;
out.tools = tools.map((t) => t.name);
const info = await client.callTool({ name: "info", arguments: {} });
out.info_text = info.content[0].text.split("\n")[0];
const obs = await client.callTool({ name: "observe", arguments: { image: true } });
out.observe_types = obs.content.map((c) => c.type);
const act = await client.callTool({ name: "act", arguments: { action: [1, 0, 0, -1], repeat: 3 } });
out.act_error = act.isError;
out.act_text = act.content[0].text;
const bad = await client.callTool({ name: "act", arguments: { action: "x" } });
out.bad_is_error = bad.isError;
try {
  await client.callTool({ name: "status", arguments: {} });
  out.unknown_tool = "accepted";
} catch (e) {
  out.unknown_tool = "rejected";
}
const done = await client.callTool({ name: "done", arguments: { message: "sdk" } });
out.done_text = done.content[0].text;
await client.close();
console.log(JSON.stringify(out));
