// Runs with Vitest (`npx vitest run src/features/scan`) or any runner with describe/it/expect globals.
import { describe, expect, it } from 'vitest';
import { normalizeCode, parseMachineQr } from './parseQr';

describe('parseMachineQr', () => {
  it.each([
    ['https://app.kaarigar-ai.online/m/a1b2c3d4e5f6a1b2c3d4e5f6', 'a1b2c3d4e5f6a1b2c3d4e5f6'],
    ['https://dev.kaarigar-ai.online/m/a1b2c3d4e5f6a1b2c3d4e5f6/', 'a1b2c3d4e5f6a1b2c3d4e5f6'],
    ['http://192.168.1.20:5173/m/ABCDEF12?x=1', 'ABCDEF12'],
    ['  https://app.kaarigar-ai.online/m/a1b2c3d4e5f6a1b2c3d4e5f6  ', 'a1b2c3d4e5f6a1b2c3d4e5f6'],
    ['/m/a1b2c3d4e5f6', 'a1b2c3d4e5f6'],
    ['m/a1b2c3d4e5f6', 'a1b2c3d4e5f6'],
  ])('sticker %s', (raw, token) => {
    expect(parseMachineQr(raw)).toEqual({ kind: 'token', token });
  });

  it.each([['HP-07', 'HP-07'], ['hp 07', 'HP-07'], ['cnc-03', 'CNC-03'], ['AC01', 'AC01'], ['hp-12b', 'HP-12B']])(
    'machine code %s', (raw, code) => {
      expect(parseMachineQr(raw)).toEqual({ kind: 'code', code });
    });

  it.each([
    '', '   ', 'WIFI:T:WPA;S:plant;P:secret;;', 'upi://pay?pa=shop@upi&am=10', 'https://example.com/',
    'https://evil.example/m/../../admin', 'https://app.kaarigar-ai.online/m/short', 'https://app.kaarigar-ai.online/m/a1b2c3d4-e5f6',
    'https://app.kaarigar-ai.online/manager/setup/people', 'javascript:alert(1)', 'Hello world', 'x'.repeat(600),
  ])('not a Kaarigar sticker: %s', (raw) => {
    expect(parseMachineQr(raw)).toEqual({ kind: 'unknown' });
  });

  it('normalizes codes like the backend', () => {
    expect(normalizeCode(' hp  7 ')).toBe('HP-7');
  });
});
