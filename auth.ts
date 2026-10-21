import { randomBytes } from 'node:crypto'
import { mkdirSync, readFileSync, writeFileSync } from 'node:fs'
import type { IncomingHttpHeaders } from 'node:http'
import { homedir } from 'node:os'
import { dirname, join } from 'node:path'

export const TOKEN_PATH = join(homedir(), '.cc-voice-channel', 'token')

export function loadToken(path = TOKEN_PATH): string {
  mkdirSync(dirname(path), { recursive: true })
  try {
    writeFileSync(path, randomBytes(32).toString('hex'), { flag: 'wx' })
  } catch (error) {
    if ((error as NodeJS.ErrnoException).code !== 'EEXIST') throw error
  }
  return readFileSync(path, 'utf8').trim()
}

// A web page can POST text/plain to localhost without a CORS preflight, but it cannot drop Origin or add a custom header.
export function isAuthorized(headers: IncomingHttpHeaders, token: string): boolean {
  if (headers.origin !== undefined) return false
  return headers['x-voice-token'] === token
}
