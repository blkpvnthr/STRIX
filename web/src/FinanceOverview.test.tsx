import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";
import { FinanceOverview } from "./FinanceOverview";
import type { NetWorth } from "./finance";

function mockFetch(netWorth: NetWorth): void {
  vi.stubGlobal(
    "fetch",
    vi.fn(async (url: string) => {
      if (String(url).includes("/net-worth")) {
        return new Response(JSON.stringify(netWorth), { status: 200 });
      }
      return new Response("not found", { status: 404 });
    }),
  );
}

afterEach(() => {
  vi.unstubAllGlobals();
});

const NW: NetWorth = {
  assets_total: "1000.00",
  liabilities_total: "200.00",
  net_worth: "800.00",
  accounts: [
    { account_id: "ACCT-1", name: "Checking", account_type: "asset", balance: "1000.00" },
    { account_id: "ACCT-2", name: "Visa", account_type: "liability", balance: "200.00" },
  ],
};

describe("FinanceOverview", () => {
  it("shows a loading state first, then the net worth and accounts", async () => {
    mockFetch(NW);
    render(<FinanceOverview />);
    expect(screen.getByText(/loading/i)).toBeInTheDocument();
    await waitFor(() => expect(screen.getByText("$800.00")).toBeInTheDocument());
    expect(screen.getByText("Checking")).toBeInTheDocument();
    expect(screen.getByText("Visa")).toBeInTheDocument();
    // Exact string money is rendered verbatim (no float formatting drift).
    expect(screen.getAllByText("$1000.00").length).toBeGreaterThan(0);
  });

  it("shows an empty state when there are no accounts", async () => {
    mockFetch({ assets_total: "0", liabilities_total: "0", net_worth: "0", accounts: [] });
    render(<FinanceOverview />);
    await waitFor(() => expect(screen.getByText(/no accounts/i)).toBeInTheDocument());
  });

  it("shows an error state when the API is unavailable", async () => {
    vi.stubGlobal("fetch", vi.fn(async () => new Response("boom", { status: 503 })));
    render(<FinanceOverview />);
    await waitFor(() => expect(screen.getByText(/unavailable|error/i)).toBeInTheDocument());
  });
});
