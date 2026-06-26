import { loadConfig } from "./config";

export function startServer(port: number) {
    const cfg = loadConfig();
    return runServer(cfg, port);
}

export class ServerWrapper {
    start() {
        return startServer(8080);
    }
}

const runServer = (cfg: Config, port: number) => null;
