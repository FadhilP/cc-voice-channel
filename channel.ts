import http from 'node:http'
import { Server } from '@modelcontextprotocol/sdk/server/index.js'
import { StdioServerTransport } from '@modelcontextprotocol/sdk/server/stdio.js'
import { CallToolRequestSchema, ListToolsRequestSchema } from '@modelcontextprotocol/sdk/types.js'
import { isAuthorized, loadToken } from './auth.ts'

const CHANNEL_PORT = 8788
const DAEMON_SPEAK_URL = 'http://127.0.0.1:8789/speak'

const token = loadToken()

const mcp = new Server(
  { name: 'voice', version: '0.1.0' },
  {
    capabilities: { experimental: { 'claude/channel': {} }, tools: {} },
    instructions: [
      'The user talks to you by voice. Each spoken request arrives as <channel source="voice">transcript</channel>.',
      'Transcripts come from local speech-to-text, so expect misheard words and fix them from context.',
      'The user is usually not looking at the screen. Call the speak tool when you finish a request, when a subagent reports back, or when you need a decision.',
      'Speak one or two short plain sentences: no markdown, code, file paths, or lists.',
    ].join(' '),
  },
)

mcp.setRequestHandler(ListToolsRequestSchema, async () => ({
  tools: [{
    name: 'speak',
    description: 'Say text aloud to the user through local text-to-speech.',
    inputSchema: {
      type: 'object',
      properties: {
        text: { type: 'string', description: 'One or two plain spoken sentences.' },
      },
      required: ['text'],
    },
  }],
}))

mcp.setRequestHandler(CallToolRequestSchema, async req => {
  if (req.params.name !== 'speak') throw new Error(`unknown tool: ${req.params.name}`)
  const { text } = req.params.arguments as { text: string }
  const res = await fetch(DAEMON_SPEAK_URL, {
    method: 'POST',
    headers: { 'X-Voice-Token': token },
    body: text,
  })
  if (!res.ok) {
    return { content: [{ type: 'text', text: `speak failed: HTTP ${res.status}` }], isError: true }
  }
  return { content: [{ type: 'text', text: 'spoken' }] }
})

await mcp.connect(new StdioServerTransport())

http.createServer((req, res) => {
  if (req.method !== 'POST' || !isAuthorized(req.headers, token)) {
    res.writeHead(403).end()
    return
  }
  let body = ''
  req.setEncoding('utf8')
  req.on('data', chunk => { body += chunk })
  req.on('end', async () => {
    await mcp.notification({ method: 'notifications/claude/channel', params: { content: body } })
    res.writeHead(202).end()
  })
}).listen(CHANNEL_PORT, '127.0.0.1')
