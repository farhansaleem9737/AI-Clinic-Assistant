import { useEffect, useState } from "react";
import { getErrorMessage } from "../services/api";

const IDLE = { data: null, loading: false, error: "", status: null };
const sameDeps = (a, b) => a.length === b.length && a.every((value, i) => Object.is(value, b[i]));

/**
 * Run an API call and expose it as { data, loading, error, status }.
 * `status` is the HTTP status of a failed call (e.g. 404), or null.
 *
 * `fetcher` returns an axios promise and is re-run when `deps` change.
 * Pass `enabled: false` to skip the call (e.g. a section this role lacks).
 *
 * "Loading" is derived, not stored: the result remembers which deps it was
 * fetched for, and anything else means a request is in flight. While the
 * next request runs, the previous data stays available (no flicker), and a
 * slow old response can never overwrite a newer one.
 */
export function useFetch(fetcher, deps, { enabled = true } = {}) {
  const [result, setResult] = useState(null); // { deps, data, error }

  useEffect(() => {
    if (!enabled) return;
    let cancelled = false;
    fetcher()
      .then((res) => !cancelled && setResult({ deps, data: res.data, error: "", status: null }))
      .catch(
        (err) =>
          !cancelled &&
          setResult({
            deps,
            data: null,
            error: getErrorMessage(err, "Could not load this section"),
            status: err.response?.status ?? null,
          })
      );
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [enabled, ...deps]);

  if (!enabled) return IDLE;
  if (result && sameDeps(result.deps, deps)) {
    return { data: result.data, loading: false, error: result.error, status: result.status };
  }
  return { data: result?.data ?? null, loading: true, error: "", status: null };
}
