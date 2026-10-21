import { describe, expect, it } from 'vitest'
import { bytes, compact, duration, money, pct, ratio } from './format'

describe('formatting', () => {
  it('formats money with more precision for small amounts', () => {
    expect(money(0.00271)).toBe('$0.0027')
    expect(money(48320)).toBe('$48,320.00')
    expect(money(null)).toBe('–')
  })

  it('formats durations', () => {
    expect(duration(450)).toBe('450 ms')
    expect(duration(1658)).toBe('1.7 s')
    expect(duration(125_000)).toBe('2m 5s')
    expect(duration(undefined)).toBe('–')
  })

  it('formats percentages and ratios', () => {
    expect(pct(98.61, 1)).toBe('98.6%')
    expect(ratio(0.9)).toBe('90%')
    expect(pct(null)).toBe('–')
  })

  it('formats counts and sizes', () => {
    expect(compact(20500)).toBe('20.5K')
    expect(bytes(2048)).toBe('2.0 KB')
    expect(bytes(512)).toBe('512 B')
  })
})
