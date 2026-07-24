import CallingPackage from "webex/calling";
import { LocalMicrophoneStream } from "@webex/calling";

import { unwrapDefaultExport } from "./module-interop";

type RunConfig = {
  accessToken: string;
  destination: string;
  audioUrl: string;
};

type EventDetails = Record<string, string | number | boolean | undefined>;

type CallingLine = {
  on: (name: string, callback: (...args: unknown[]) => void) => void;
  register: () => Promise<void> | void;
  makeCall: (destination: { type: "uri"; address: string }) => CallingCall;
};

type CallingSdk = {
  on: (name: string, callback: (...args: unknown[]) => void) => void;
  register: () => Promise<void>;
  callingClient?: {
    getLines: () => Record<string, CallingLine>;
  };
};

type CallingFactory = {
  init: (config: unknown) => Promise<CallingSdk>;
  createMicrophoneStream: (options: { audio: boolean }) => Promise<LocalMicrophoneStream>;
};

// `webex/calling` is CommonJS and its browser bundle exposes the default
// export as either the module itself or a nested `default`, depending on the
// bundler's interop shim.
const Calling = unwrapDefaultExport(
  CallingPackage as unknown as CallingFactory | { default?: CallingFactory },
);

type CallingCall = {
  on: (name: string, callback: (...args: unknown[]) => void) => void;
  dial: (stream: LocalMicrophoneStream) => Promise<void> | void;
  end: () => void;
};

declare global {
  interface Window {
    byovaE2E: {
      dial: () => Promise<void>;
      injectAudio: (trigger?: string) => Promise<void>;
      endCall: () => Promise<void>;
    };
  }
}

const status = document.querySelector<HTMLParagraphElement>("#status")!;
const startButton = document.querySelector<HTMLButtonElement>("#start-calling-test")!;

function updateStatus(message: string): void {
  status.textContent = message;
}

function waitForEvent(
  target: { on: (name: string, callback: (...args: unknown[]) => void) => void },
  name: string,
  timeoutMilliseconds: number,
): Promise<void> {
  return new Promise((resolve, reject) => {
    const timeout = window.setTimeout(
      () => reject(new Error(`Timed out waiting for Calling SDK event: ${name}`)),
      timeoutMilliseconds,
    );
    target.on(name, () => {
      window.clearTimeout(timeout);
      resolve();
    });
  });
}

async function report(name: string, details: EventDetails = {}): Promise<void> {
  await fetch("/api/events", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ name, timestamp: performance.now() / 1000, details }),
  });
}

class RemoteAudioActivity {
  private readonly analyser: AnalyserNode;
  private readonly values: Uint8Array<ArrayBuffer>;
  private remoteActive = false;
  private animationFrame?: number;

  constructor(context: AudioContext, track: MediaStreamTrack) {
    const stream = new MediaStream([track]);
    const source = context.createMediaStreamSource(stream);
    this.analyser = context.createAnalyser();
    const mutedOutput = context.createGain();
    this.analyser.fftSize = 1024;
    this.values = new Uint8Array(this.analyser.fftSize);
    source.connect(this.analyser);
    // Web Audio only renders a graph with an output path. Keep remote media
    // flowing through the analyser but silence it locally.
    mutedOutput.gain.value = 0;
    this.analyser.connect(mutedOutput);
    mutedOutput.connect(context.destination);
  }

  start(): void {
    const observe = () => {
      this.analyser.getByteTimeDomainData(this.values);
      let squaredTotal = 0;
      for (const value of this.values) {
        const sample = (value - 128) / 128;
        squaredTotal += sample * sample;
      }
      const rms = Math.sqrt(squaredTotal / this.values.length);
      const active = rms >= 0.012;
      if (active !== this.remoteActive) {
        this.remoteActive = active;
        void report(active ? "remote_audio_active" : "remote_audio_inactive", { rms });
      }
      this.animationFrame = requestAnimationFrame(observe);
    };
    observe();
  }

  stop(): void {
    if (this.animationFrame !== undefined) {
      cancelAnimationFrame(this.animationFrame);
    }
  }
}

class CallingMediaClient {
  private config!: RunConfig;
  private audioContext!: AudioContext;
  private destinationNode!: MediaStreamAudioDestinationNode;
  private localMicrophone!: LocalMicrophoneStream;
  private line!: CallingLine;
  private call?: CallingCall;
  private observer?: RemoteAudioActivity;
  private injected = false;

  async initialise(): Promise<void> {
    // This method is called from the Start button's trusted click event. Chrome
    // requires Web Audio to be created and resumed within that user gesture.
    this.audioContext = new AudioContext();
    await this.audioContext.resume();
    if (this.audioContext.state !== "running") {
      throw new Error("The browser did not activate the Web Audio context");
    }
    const response = await fetch("/api/config", { cache: "no-store" });
    if (!response.ok) {
      throw new Error(`Cannot retrieve local run config: ${response.status}`);
    }
    this.config = (await response.json()) as RunConfig;
    this.destinationNode = this.audioContext.createMediaStreamDestination();
    // This follows the official Calling SDK sample lifecycle.  Calling.init
    // creates the core SDK, `ready` confirms its initialization, and
    // `register` creates the calling client before a line can register/dial.
    const calling = (await Calling.init({
      webexConfig: {
        credentials: { access_token: this.config.accessToken },
        config: {
          logger: { level: "info" },
          calling: { cacheU2C: true },
        },
      },
      callingConfig: {
        clientConfig: { calling: true, contact: false, callHistory: false, callSettings: false, voicemail: false },
        callingClientConfig: {
          logger: { level: "info" },
          discovery: { region: "", country: "" },
          serviceData: { indicator: "calling", domain: "" },
        },
        logger: { level: "info" },
      },
    })) as CallingSdk;
    await waitForEvent(calling, "ready", 45_000);
    await calling.register();
    const callingClient = calling.callingClient;
    if (!callingClient) {
      throw new Error("Calling SDK registration completed without creating a calling client");
    }
    const firstLine = Object.values(callingClient.getLines())[0];
    if (!firstLine) {
      throw new Error("Webex Calling did not expose a line for this user");
    }
    this.line = firstLine as CallingLine;
    const lineRegistered = waitForEvent(this.line, "registered", 45_000);
    this.line.on("registered", () => {
      updateStatus("Webex Calling registered; preparing the test media stream.");
    });
    this.line.on("error", (error) => void this.reportError(error));
    await this.line.register();
    await lineRegistered;

    // Establish the LocalMicrophoneStream through the public Calling SDK API,
    // as in the official sample. Then replace only its output with our Web
    // Audio track so the SDK keeps its supported local-media lifecycle.
    this.localMicrophone = await Calling.createMicrophoneStream({ audio: true });
    this.localMicrophone.changeOutputTrack(this.destinationNode.stream.getAudioTracks()[0]);
    updateStatus("Webex Calling registered; waiting for Python runner.");
    await report("frontend_ready");
  }

  async dial(): Promise<void> {
    this.assertReady();
    const call = this.line.makeCall({ type: "uri", address: this.config.destination });
    if (!call) {
      throw new Error("Webex Calling could not create the call");
    }
    this.call = call;
    this.call.on("progress", () => void report("progress"));
    this.call.on("established", () => {
      updateStatus("Call established; listening for the remote prompt.");
      void report("established");
    });
    this.call.on("remote_media", (track) => this.attachRemoteMedia(track));
    this.call.on("disconnect", () => {
      this.observer?.stop();
      updateStatus("Call disconnected.");
      void report("disconnect");
    });
    this.call.on("call_error", (error) => void this.reportError(error));
    await this.call.dial(this.localMicrophone);
  }

  async injectAudio(trigger = "remote_prompt"): Promise<void> {
    if (!this.call) {
      throw new Error("Cannot inject audio before dialing");
    }
    if (this.injected) {
      throw new Error("The test caller only supports one injected utterance per call");
    }
    this.injected = true;
    const response = await fetch(this.config.audioUrl);
    if (!response.ok) {
      throw new Error(`Cannot load prepared caller audio: ${response.status}`);
    }
    const buffer = await response.arrayBuffer();
    const audio = await this.audioContext.decodeAudioData(buffer);
    const source = this.audioContext.createBufferSource();
    source.buffer = audio;
    source.connect(this.destinationNode);
    source.addEventListener("ended", () => void report("injection_finished"), { once: true });
    updateStatus("Injecting prepared caller audio.");
    void report("injection_started", { durationSeconds: audio.duration, trigger });
    source.start();
  }

  async endCall(): Promise<void> {
    this.call?.end();
  }

  private attachRemoteMedia(value: unknown): void {
    if (!(value instanceof MediaStreamTrack)) {
      void this.reportError(new Error("Calling SDK remote_media event contained no audio track"));
      return;
    }
    this.observer?.stop();
    this.observer = new RemoteAudioActivity(this.audioContext, value);
    this.observer.start();
    void report("remote_media");
  }

  private assertReady(): void {
    if (!this.line || !this.localMicrophone) {
      throw new Error("Calling client has not registered yet");
    }
  }

  private async reportError(error: unknown): Promise<void> {
    const message = error instanceof Error ? error.message : String(error);
    updateStatus(`Calling client error: ${message}`);
    await report("error", { message });
  }
}

const client = new CallingMediaClient();
window.byovaE2E = {
  dial: () => client.dial(),
  injectAudio: (trigger) => client.injectAudio(trigger),
  endCall: () => client.endCall(),
};

startButton.addEventListener("click", () => {
  startButton.disabled = true;
  client.initialise().catch((error: unknown) => {
    const message = error instanceof Error ? error.message : String(error);
    updateStatus(`Startup failed: ${message}`);
    void report("error", { message });
  });
});
