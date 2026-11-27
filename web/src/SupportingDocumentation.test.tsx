import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { SupportingDocumentationPanel } from "./SupportingDocumentation";
import type { SupportingDocumentation } from "./types";

const doc: SupportingDocumentation = {
  references: [
    {
      number: 1,
      evidence_id: "EV-1",
      title: "On Verifiable Evidence",
      provider: "Journal of Examples",
      url: "https://example.org/paper",
      published_date: "2026-01-01",
      content_hash: "a".repeat(64),
      authors: ["Ada Lovelace"],
      doi: "10.1000/xyz123",
      pdf_url: null,
      pages: "12-18",
      sections: null,
      dataset_id: null,
      data_timestamp: null,
      methodology: null,
      cited_by_claim_ids: ["CL-1"],
    },
  ],
  claim_citations: { "CL-1": [1] },
  integrity: { complete: true, uncited_claims: [], orphan_references: [], dangling_markers: [] },
};

describe("SupportingDocumentationPanel", () => {
  it("renders numbered references with rich metadata", () => {
    render(<SupportingDocumentationPanel documentation={doc} />);
    expect(screen.getByText(/On Verifiable Evidence/)).toBeInTheDocument();
    expect(screen.getByText(/Ada Lovelace/)).toBeInTheDocument();
    expect(screen.getByText(/10\.1000\/xyz123/)).toBeInTheDocument();
    expect(screen.getByText(/\[1\]/)).toBeInTheDocument();
  });

  it("warns when citation-mapping integrity is incomplete", () => {
    const incomplete: SupportingDocumentation = {
      ...doc,
      integrity: {
        complete: false,
        uncited_claims: ["CL-9"],
        orphan_references: [],
        dangling_markers: ["EV-MISSING"],
      },
    };
    render(<SupportingDocumentationPanel documentation={incomplete} />);
    expect(screen.getByText(/incomplete|unverified|not.*complete/i)).toBeInTheDocument();
  });

  it("renders nothing when there is no documentation", () => {
    const { container } = render(<SupportingDocumentationPanel documentation={null} />);
    expect(container).toBeEmptyDOMElement();
  });

  it("renders nothing when there are no references", () => {
    const empty: SupportingDocumentation = {
      references: [],
      claim_citations: {},
      integrity: { complete: true, uncited_claims: [], orphan_references: [], dangling_markers: [] },
    };
    const { container } = render(<SupportingDocumentationPanel documentation={empty} />);
    expect(container).toBeEmptyDOMElement();
  });
});
