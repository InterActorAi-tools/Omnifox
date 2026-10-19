import { describe, expect, it } from "vitest";
import { describeDevice } from "../utils/device";

describe("describeDevice", () => {
    it.each([
        ["Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/141.0 Safari/537.36", "Chrome on Windows"],
        ["Mozilla/5.0 (Windows NT 10.0) AppleWebKit/537.36 Chrome/141.0 Safari/537.36 Edg/141.0", "Edge on Windows"],
        ["Mozilla/5.0 (iPhone; CPU iPhone OS 18_0 like Mac OS X) AppleWebKit/605.1.15 Version/18.0 Mobile/15E148 Safari/604.1", "Safari on iOS"],
        ["Mozilla/5.0 (Macintosh; Intel Mac OS X 14_5; rv:131.0) Gecko/20100101 Firefox/131.0", "Firefox on macOS"],
        ["Mozilla/5.0 (Linux; Android 15) AppleWebKit/537.36 Chrome/141.0 Mobile Safari/537.36", "Chrome on Android"],
        ["curl/8.5.0", "Unknown device"],
        [null, "Unknown device"],
    ])("%s -> %s", (ua, label) => {
        expect(describeDevice(ua)).toBe(label);
    });
});
