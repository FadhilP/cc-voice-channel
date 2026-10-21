import assert from 'node:assert/strict'
import { mkdtempSync } from 'node:fs'
import { tmpdir } from 'node:os'
import { join } from 'node:path'
import test from 'node:test'
import { isAuthorized, loadToken } from './auth.ts'

test('rejects requests without the exact token or with a browser Origin', () => {
  const token = 'secret'
  assert.equal(isAuthorized({ 'x-voice-token': token }, token), true)
  assert.equal(isAuthorized({}, token), false)
  assert.equal(isAuthorized({ 'x-voice-token': 'wrong' }, token), false)
  assert.equal(isAuthorized({ 'x-voice-token': token, origin: 'https://evil.example' }, token), false)
})

test('loadToken creates a token once and never overwrites it', () => {
  const path = join(mkdtempSync(join(tmpdir(), 'cc-voice-channel-')), 'nested', 'token')
  const first = loadToken(path)
  assert.match(first, /^[0-9a-f]{64}$/)
  assert.equal(loadToken(path), first)
})
