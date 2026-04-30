type SinkCapableAudioElement = HTMLAudioElement & {
  setSinkId?: (sinkId: string) => Promise<void>;
};

const sinkRegistry = new Set<SinkCapableAudioElement>();
let currentOutputDeviceId = "";

function supportsSetSinkId(element: SinkCapableAudioElement): boolean {
  return typeof element.setSinkId === "function";
}

async function applySinkIdToElement(
  element: SinkCapableAudioElement,
  outputDeviceId: string,
): Promise<void> {
  if (!outputDeviceId || !supportsSetSinkId(element)) {
    return;
  }

  await element.setSinkId!(outputDeviceId);
}

export function registerAudioSink(element: HTMLAudioElement): void {
  const sink = element as SinkCapableAudioElement;
  sinkRegistry.add(sink);

  if (currentOutputDeviceId) {
    void applySinkIdToElement(sink, currentOutputDeviceId).catch(() => undefined);
  }
}

export function unregisterAudioSink(element: HTMLAudioElement): void {
  sinkRegistry.delete(element as SinkCapableAudioElement);
}

export async function setRoomAudioOutputDevice(outputDeviceId: string): Promise<void> {
  currentOutputDeviceId = outputDeviceId;

  if (!outputDeviceId || sinkRegistry.size === 0) {
    return;
  }

  const applyResults = await Promise.allSettled(
    Array.from(sinkRegistry).map((sink) => applySinkIdToElement(sink, outputDeviceId)),
  );

  const firstFailure = applyResults.find((result) => result.status === "rejected");
  if (firstFailure && firstFailure.status === "rejected") {
    throw firstFailure.reason;
  }
}

export function getRoomAudioOutputDevice(): string {
  return currentOutputDeviceId;
}
