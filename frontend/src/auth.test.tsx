import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { AuthProvider, useAuth } from "./auth";

const ME = { id: 1, name: "Prof. Pooja Rao", email: "pooja.rao@relay.test", csrf_token: "t", labs: [], departments: [] };

function respond(status: number, body: unknown) {
  return Promise.resolve(new Response(JSON.stringify(body), { status, headers: { "Content-Type": "application/json" } }));
}

let auth: ReturnType<typeof useAuth>;
function Probe() {
  auth = useAuth();
  return <div>{auth.loading ? "loading" : auth.me ? `in:${auth.me.name}` : "out"}</div>;
}

afterEach(() => vi.unstubAllGlobals());

describe("AuthProvider", () => {
  it("shows the user as signed in right after login, and signed out after logout", async () => {
    vi.stubGlobal("fetch", vi.fn((url: string) => {
      if (url.endsWith("/auth/me")) return respond(401, { error: { code: "unauthenticated", message: "Please sign in." } });
      if (url.endsWith("/auth/login")) return respond(200, ME);
      if (url.endsWith("/auth/logout")) return respond(200, { ok: true });
      return respond(404, {});
    }));
    render(<QueryClientProvider client={new QueryClient()}><AuthProvider><Probe /></AuthProvider></QueryClientProvider>);
    await screen.findByText("out");

    await act(() => auth.login("pooja.rao@relay.test", "relay-demo-pass").then(() => undefined));
    await waitFor(() => expect(screen.getByText("in:Prof. Pooja Rao")).toBeTruthy());

    await act(() => auth.logout());
    await waitFor(() => expect(screen.getByText("out")).toBeTruthy());
  });
});
