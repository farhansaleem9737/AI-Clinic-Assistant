import { keepPreviousData, useQuery } from "@tanstack/react-query";
import { useEffect, useId, useState } from "react";
import { getErrorMessage } from "../services/api";
import { cacheOwner, freshnessOf, queryClient } from "../services/queryClient";

const noop = () => {};
const IDLE = { data: null, loading: false, error: "", status: null, code: null, reset: noop, reload: () => Promise.resolve() };

/**
 * Run an API call and expose it as { data, loading, error, status, code }.
 * `status` is the HTTP status of a failed call (e.g. 404) and `code` the
 * API's error code (e.g. "NO_PATIENT_PROFILE"), or null.
 *
 * `fetcher` returns an axios promise and is re-run when `deps` change.
 * Options:
 * - `query`: a name such as "appointments/list". Named results are kept in the
 *   app's cache for the signed-in user (services/queryClient.js): opening the
 *   page again shows them at once and refreshes them in the background when
 *   they are older than their category's freshness. Unnamed calls run on
 *   every mount, as before (e.g. the last availability check before booking).
 * - `refresh`: any value; a change (e.g. a "Try again" counter) re-fetches.
 * - `enabled: false` skips the call (e.g. a section this role lacks).
 * - `errorMessage`: shown when the server gives no message.
 *
 * `reset()` forgets the loaded data and loads it again (e.g. data that failed
 * to render): `loading` and no data until it arrives. `reload()` fetches again
 * in the background (data stays on screen) and resolves when done.
 *
 * `loading` is true only while nothing usable is on screen for these deps or
 * an explicit refresh runs; a background refresh keeps the data and does not
 * set it. A failed background refresh keeps the data too (it is retried on the
 * next visit). Identical requests from several components (and React's
 * development double-mount) are sent once.
 */
export function useFetch(fetcher, deps, { query, enabled = true, refresh, errorMessage = "Could not load this section" } = {}) {
  const localId = useId();
  const queryKey = [cacheOwner(), query ?? `local:${localId}`, ...deps];
  const reset = () => queryClient.resetQueries({ queryKey, exact: true });
  const result = useQuery(
    {
      queryKey,
      queryFn: () => fetcher().then((res) => res.data),
      enabled,
      // Different deps (a filter, the next page): the previous data stays on screen while they load.
      placeholderData: keepPreviousData,
      staleTime: query ? freshnessOf(query) : 0,
      ...(query ? {} : { gcTime: 0 }),
    },
    queryClient
  );

  // A new `refresh` value re-fetches, and `loading` covers it until done.
  const [settled, setSettled] = useState(refresh); // the last value whose fetch finished
  const { refetch } = result;
  const reload = () => refetch({ cancelRefetch: false });
  useEffect(() => {
    if (!enabled || Object.is(settled, refresh)) return;
    let live = true;
    // Joins a request already running for the same data instead of repeating it.
    refetch({ cancelRefetch: false }).finally(() => live && setSettled(refresh));
    return () => {
      live = false;
    };
  }, [refresh, settled, enabled, refetch]);

  if (!enabled) return IDLE;
  const current = result.data !== undefined && !result.isPlaceholderData;
  const refetching = !Object.is(settled, refresh) && result.isFetching;
  if (result.isError && !current && !refetching) {
    const { response } = result.error ?? {};
    return {
      data: null,
      loading: false,
      error: getErrorMessage(result.error, errorMessage),
      status: response?.status ?? null,
      code: response?.data?.error?.code ?? null,
      reset,
      reload,
    };
  }
  return { data: result.data ?? null, loading: !current || refetching, error: "", status: null, code: null, reset, reload };
}
