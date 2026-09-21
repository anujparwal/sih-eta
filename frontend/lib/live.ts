"use client";

import { useEffect, useState } from "react";
import type { TrainETA } from "./types";

export async function fetchData<T>(
  path: string,
  signal?: AbortSignal,
): Promise<T> {
  const response = await fetch(`/api${path}`, { signal, cache: "no-store" });
  if (!response.ok)
    throw new Error(
      response.status === 404
        ? "Not found in the six-train demo network."
        : "Unable to reach train data. Retrying automatically.",
    );
  return response.json();
}

export function useClock() {
  const [now, setNow] = useState(0);
  useEffect(() => {
    const timer = setInterval(() => setNow(Date.now()), 1000);
    return () => clearInterval(timer);
  }, []);
  return now;
}

export function usePolling<T>(path: string | null, interval = 10000) {
  const [attempt, setAttempt] = useState(0);
  const [state, setState] = useState<{
    path: string | null;
    data: T | null;
    error: string | null;
    received: number | null;
  }>({ path, data: null, error: null, received: null });
  useEffect(() => {
    if (!path) return;
    let closed = false;
    let timer: ReturnType<typeof setTimeout>;
    let controller: AbortController;
    async function poll() {
      controller = new AbortController();
      let succeeded = false;
      const timeout = setTimeout(() => controller.abort(), 10000);
      try {
        const data = await fetchData<T>(path!, controller.signal);
        succeeded = true;
        if (!closed)
          setState({ path, data, error: null, received: Date.now() });
      } catch (error) {
        if (!closed)
          setState((prev) => ({
            path,
            data: prev.path === path ? prev.data : null,
            received: prev.path === path ? prev.received : null,
            error:
              error instanceof Error && error.name !== "AbortError"
                ? error.message
                : "The request timed out. Retrying automatically.",
          }));
      } finally {
        clearTimeout(timeout);
        if (!closed && (interval > 0 || !succeeded))
          timer = setTimeout(poll, interval || 10000);
      }
    }
    void poll();
    return () => {
      closed = true;
      controller.abort();
      clearTimeout(timer);
    };
  }, [path, interval, attempt]);
  return {
    ...(state.path === path
      ? state
      : { data: null, error: null, received: null }),
    retry: () => setAttempt((n) => n + 1),
  };
}

export type Feed = {
  data: TrainETA | null;
  connection: "connecting" | "live" | "polling" | "offline";
  error: string | null;
  trend: number | null;
};
export const emptyFeed: Feed = {
  data: null,
  connection: "connecting",
  error: null,
  trend: null,
};
function reduceSnapshot(previous: Feed, data: TrainETA): Feed {
  if (
    previous.data &&
    Date.parse(data.generated_at) < Date.parse(previous.data.generated_at)
  )
    return previous;
  const before = previous.data?.stations[0];
  const next = data.stations[0];
  const comparable =
    previous.data?.journey_id === data.journey_id &&
    before?.station_code === next?.station_code &&
    before?.model_version === next?.model_version &&
    before?.predicted_delay_minutes != null &&
    next?.predicted_delay_minutes != null;
  const changed =
    previous.data?.position_id !== data.position_id ||
    before?.predicted_delay_minutes !== next?.predicted_delay_minutes;
  const trend = !comparable
    ? null
    : changed
      ? next!.predicted_delay_minutes! - before!.predicted_delay_minutes!
      : previous.trend;
  return { ...previous, data, trend, error: null };
}

function subscribeTrain(
  number: string,
  update: (fn: (previous: Feed) => Feed) => void,
) {
  let closed = false;
  let socket: WebSocket | null = null;
  let retry: ReturnType<typeof setTimeout>;
  let poll: ReturnType<typeof setTimeout>;
  let backoff = 1000;
  let streamReady = false;
  let handshake: ReturnType<typeof setTimeout>;
  const controllers = new Set<AbortController>();
  async function refresh() {
    const controller = new AbortController();
    controllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), 8000);
    try {
      const data = await fetchData<TrainETA>(
        `/trains/${number}/eta`,
        controller.signal,
      );
      if (!closed)
        update((prev) => ({
          ...reduceSnapshot(prev, data),
          connection: streamReady ? "live" : "polling",
        }));
    } catch (error) {
      if (!closed)
        update((prev) => ({
          ...prev,
          connection: streamReady ? "live" : "offline",
          error:
            error instanceof Error && error.name !== "AbortError"
              ? error.message
              : "Train data request timed out. Reconnecting…",
        }));
    } finally {
      clearTimeout(timeout);
      controllers.delete(controller);
      if (!closed) poll = setTimeout(refresh, 10000);
    }
  }
  function connect() {
    if (closed) return;
    try {
      const base =
        process.env.NEXT_PUBLIC_API_BASE_URL ||
        `${location.protocol}//${location.hostname}:8000`;
      const url = new URL(`${base.replace(/\/$/, "")}/ws/trains/${number}`);
      url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
      const candidate = new WebSocket(url);
      socket = candidate;
      streamReady = false;
      handshake = setTimeout(() => {
        if (!closed && !streamReady) candidate.close();
      }, 8000);
      // An accepted handshake is not evidence that the server can deliver data.
      candidate.onmessage = (event) => {
        if (closed || socket !== candidate) return;
        try {
          const message = JSON.parse(event.data);
          if (
            message.type === "eta_update" &&
            message.data?.train_number === number &&
            Array.isArray(message.data.stations) &&
            Array.isArray(message.data.active_events) &&
            Number.isFinite(Date.parse(message.data.generated_at))
          ) {
            clearTimeout(handshake);
            streamReady = true;
            backoff = 1000;
            update((prev) => ({
              ...reduceSnapshot(prev, message.data),
              connection: "live",
            }));
          } else {
            throw new Error("Invalid or unavailable live snapshot");
          }
        } catch {
          streamReady = false;
          update((prev) => ({
            ...prev,
            connection: prev.data ? "polling" : "offline",
            error: "Live updates interrupted. Retrying…",
          }));
          candidate.close();
        }
      };
      candidate.onerror = () => candidate.close();
      candidate.onclose = () => {
        clearTimeout(handshake);
        streamReady = false;
        if (!closed) {
          update((prev) => ({
            ...prev,
            connection: prev.data ? "polling" : "offline",
          }));
          retry = setTimeout(connect, backoff);
          backoff = Math.min(backoff * 2, 10000);
        }
      };
    } catch {
      if (!closed) retry = setTimeout(connect, 10000);
    }
  }
  void refresh();
  connect();
  return () => {
    closed = true;
    clearTimeout(retry);
    clearTimeout(poll);
    clearTimeout(handshake);
    for (const c of controllers) c.abort();
    if (socket) {
      socket.onclose = null;
      socket.onerror = null;
      socket.onmessage = null;
      if (socket.readyState === WebSocket.CONNECTING) {
        // Closing during CONNECTING creates browser console errors on navigation.
        const pending = socket;
        pending.onopen = () => pending.close();
      } else socket.close();
    }
  };
}

export function useTrainStream(number: string | null) {
  const [state, setState] = useState<{ number: string | null; feed: Feed }>({
    number,
    feed: emptyFeed,
  });
  useEffect(
    () =>
      number
        ? subscribeTrain(number, (update) =>
            setState((prev) => ({
              number,
              feed: update(prev.number === number ? prev.feed : emptyFeed),
            })),
          )
        : undefined,
    [number],
  );
  return state.number === number ? state.feed : emptyFeed;
}
export function useFleetStreams(numbers: string[]) {
  const key = numbers.join(",");
  const [feeds, setFeeds] = useState<Record<string, Feed>>({});
  useEffect(() => {
    const unsubscribers = key
      ? key.split(",").map((number) =>
          subscribeTrain(number, (update) =>
            setFeeds((prev) => ({
              ...prev,
              [number]: update(prev[number] || emptyFeed),
            })),
          ),
        )
      : [];
    return () => unsubscribers.forEach((dispose) => dispose());
  }, [key]);
  return feeds;
}
