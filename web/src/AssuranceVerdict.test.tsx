import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { AssuranceVerdict } from "./AssuranceVerdict";
import type { Assurance } from "./types";

const authorized: Assurance = {
  gateway_outcome: "authorized",
  answer_released: true,
  reason_codes: ["all_pillars_cleared"],
  uncertainty_level: "low",
  certificate_id: "AGC-abc123def456",
  signed: true,
  audit_event_ids: ["EVT-1", "EVT-2", "EVT-3"],
};

const abstained: Assurance = {
  gateway_outcome: "abstain",
  answer_released: false,
  reason_codes: ["evidence_admission_abstained"],
  uncertainty_level: "insufficient",
  certificate_id: "AGC-000",
  signed: false,
  audit_event_ids: ["EVT-1"],
};

describe("AssuranceVerdict", () => {
  it("shows RELEASED and the gateway outcome for an authorized run", () => {
    render(<AssuranceVerdict assurance={authorized} />);
    expect(screen.getByText(/released/i)).toBeInTheDocument();
    expect(screen.getByText(/authorized/i)).toBeInTheDocument();
    expect(screen.getByText(/AGC-abc123def456/)).toBeInTheDocument();
  });

  it("shows WITHHELD and a caveat when the gateway did not authorize release", () => {
    render(<AssuranceVerdict assurance={abstained} />);
    expect(screen.getByText(/withheld/i)).toBeInTheDocument();
    // A withheld answer must carry an explicit not-authorized caveat.
    expect(screen.getByText(/not.*authoriz/i)).toBeInTheDocument();
  });

  it("surfaces a fail-closed assurance error", () => {
    render(
      <AssuranceVerdict
        assurance={{ gateway_outcome: "rejected", answer_released: false, error: "boom" }}
      />,
    );
    expect(screen.getByText(/withheld/i)).toBeInTheDocument();
    expect(screen.getByText(/boom/i)).toBeInTheDocument();
  });

  it("renders nothing when no assurance verdict is present", () => {
    const { container } = render(<AssuranceVerdict assurance={null} />);
    expect(container).toBeEmptyDOMElement();
  });
});
