import { describe, expect, it } from "vitest";
import { localDate, localHHMM, zoned } from "./time";

describe("institute timezone helpers", () => {
  it("converts IST wall-clock to the right instant regardless of the browser zone", () => {
    expect(zoned("2026-11-03", "10:00").toISOString()).toBe("2026-11-03T04:30:00.000Z");
    expect(zoned("2026-11-03", "00:15").toISOString()).toBe("2026-11-02T18:45:00.000Z");
  });
  it("round-trips date and time", () => {
    const d = zoned("2026-12-31", "23:30");
    expect(localDate(d)).toBe("2026-12-31");
    expect(localHHMM(d)).toBe("23:30");
  });
});
