import { useCallback, useRef } from 'react'

/**
 * After triggering a refresh, poll for new data every `interval` ms
 * for up to `maxAttempts` attempts. Stops early when a newer batch appears.
 *
 * @param {Function} fetchFn   - async function that returns the latest recommendations
 * @param {Function} setData   - state setter
 * @param {string}   currentRunAt - run_at of the currently displayed batch (may be null)
 * @param {number}   interval  - ms between polls (default 10s)
 * @param {number}   maxAttempts - how many times to poll (default 18 = 3 minutes)
 */
export function useRefreshPoller(fetchFn, setData, interval = 10000, maxAttempts = 18) {
  const timerRef = useRef(null)
  const attemptsRef = useRef(0)
  const baseRunAtRef = useRef(null)

  const stop = useCallback(() => {
    if (timerRef.current) {
      clearTimeout(timerRef.current)
      timerRef.current = null
    }
    attemptsRef.current = 0
  }, [])

  const poll = useCallback(() => {
    if (attemptsRef.current >= maxAttempts) {
      stop()
      return
    }
    attemptsRef.current += 1
    timerRef.current = setTimeout(async () => {
      try {
        const data = await fetchFn()
        if (data && data.length > 0) {
          const latestRunAt = data[0]?.run_at
          // Stop polling if we got a newer batch
          if (!baseRunAtRef.current || new Date(latestRunAt) > new Date(baseRunAtRef.current)) {
            setData(data)
            stop()
            return
          }
        }
      } catch (_) {
        // ignore transient fetch errors during polling
      }
      poll() // schedule next attempt
    }, interval)
  }, [fetchFn, setData, interval, maxAttempts, stop])

  const start = useCallback((currentRunAt) => {
    stop()
    baseRunAtRef.current = currentRunAt || null
    attemptsRef.current = 0
    poll()
  }, [poll, stop])

  return { start, stop }
}
