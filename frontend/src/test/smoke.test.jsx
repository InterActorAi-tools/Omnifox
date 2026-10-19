import { describe, expect, it } from "vitest";
import { render, screen } from "@testing-library/react";

describe("frontend smoke", () => {
    it("renders a React component into jsdom", () => {
        render(<h1>OMNIFOX</h1>);
        expect(screen.getByRole("heading", { name: "OMNIFOX" })).toBeInTheDocument();
    });

    it("exposes runtime config on window.APP_CONFIG", () => {
        expect(window.APP_CONFIG).toBeDefined();
        expect(window.APP_CONFIG.API_URL).toBeTypeOf("string");
        expect(window.APP_CONFIG.GOOGLE_CLIENT_ID).toBeTypeOf("string");
    });
});
