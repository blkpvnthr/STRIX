import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { StatusBadge, fmtDate } from "./ui";

describe("StatusBadge", () => {
  it("renders the human label for a known status", () => {
    render(<StatusBadge status="verified" />);
    expect(screen.getByText("Verified")).toBeInTheDocument();
  });

  it("falls back to Pending for an unknown status", () => {
    // @ts-expect-error - deliberately exercising the fallback path
    render(<StatusBadge status="bogus" />);
    expect(screen.getByText("Pending")).toBeInTheDocument();
  });
});

describe("fmtDate", () => {
  it("renders an em dash for empty input", () => {
    expect(fmtDate(null)).toBe("—");
  });

  it("passes through an unparseable string unchanged", () => {
    expect(fmtDate("not-a-date")).toBe("not-a-date");
  });
});
