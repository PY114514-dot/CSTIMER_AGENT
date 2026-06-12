/**
 * services/smart-cube/EventEmitter.ts ── 适配器内部用的事件总线
 *
 * 跟 wsStore 一样的 Pub/Sub 思路, 但更轻 (不依赖 zustand), 适配器实例内部用
 * 解耦适配器与上层订阅者: 适配器只 emit, 谁订阅谁消费
 */
import type { SmartCubeEvent, SmartCubeEventInfo } from './types'

type Handler<E extends SmartCubeEventInfo> = (data: SmartCubeEvent[E]) => void
type WildcardHandler = (
  info: SmartCubeEventInfo,
  data: SmartCubeEvent[SmartCubeEventInfo],
) => void

export class AdapterEventEmitter {
  private handlers: Map<SmartCubeEventInfo | '*', Set<Handler<any> | WildcardHandler>> = new Map()

  on<E extends SmartCubeEventInfo>(event: E, handler: Handler<E>): () => void {
    let set = this.handlers.get(event)
    if (!set) { set = new Set(); this.handlers.set(event, set) }
    set.add(handler as Handler<any>)
    return () => this.off(event, handler)
  }

  onAny(handler: WildcardHandler): () => void {
    let set = this.handlers.get('*')
    if (!set) { set = new Set(); this.handlers.set('*', set) }
    set.add(handler)
    return () => {
      set!.delete(handler)
      if (set!.size === 0) this.handlers.delete('*')
    }
  }

  off(event: SmartCubeEventInfo, handler: Handler<any>): void {
    this.handlers.get(event)?.delete(handler)
    this.handlers.get('*')?.delete(handler as any)
  }

  emit<E extends SmartCubeEventInfo>(event: E, data: SmartCubeEvent[E]): void {
    const direct = this.handlers.get(event)
    if (direct) for (const h of direct) {
      try { (h as Handler<E>)(data) } catch (e) { console.error(`[adapter] handler error on ${event}:`, e) }
    }
    const wild = this.handlers.get('*')
    if (wild) for (const h of wild) {
      try { (h as WildcardHandler)(event, data) } catch (e) { console.error('[adapter] wildcard handler error:', e) }
    }
  }

  removeAll(): void {
    this.handlers.clear()
  }
}
