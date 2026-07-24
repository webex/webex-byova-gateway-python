declare module "webex/calling" {
  import type { LocalMicrophoneStream } from "@webex/calling";

  type Listener = (...args: unknown[]) => void;

  type CallingInstance = {
    on(name: string, callback: Listener): void;
    register(): Promise<void>;
    callingClient?: unknown;
  };

  const Calling: {
    init(config: unknown): Promise<CallingInstance>;
    createMicrophoneStream(options: { audio: boolean }): Promise<LocalMicrophoneStream>;
  };

  export default Calling;
}
