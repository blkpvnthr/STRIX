import type { ReferenceDocument, SupportingDocumentation } from "./types";

/**
 * Renders the unified supporting-documentation + citation-mapping contract
 * (spec §7/§15) below the answer: genuine numbered references that inline [n]
 * citations resolve to. The same contract the CLI and workers render. When
 * citation-mapping integrity is incomplete, an explicit caveat is shown — a
 * material claim without a resolvable citation must never read as fully sourced.
 */
export function SupportingDocumentationPanel({
  documentation,
}: {
  documentation: SupportingDocumentation | null | undefined;
}) {
  if (!documentation || documentation.references.length === 0) return null;
  const { references, integrity } = documentation;

  return (
    <section
      className="rounded-lg ring-1 ring-slate-500/20 bg-white/[0.02] p-3 text-[12px]"
      aria-label="Supporting documentation"
    >
      <h3 className="font-semibold uppercase tracking-wide text-slate-300">
        Supporting documentation
      </h3>

      {!integrity.complete && (
        <p className="mt-2 text-amber-300/90">
          Citation mapping is incomplete — some material claims are not fully
          traceable to a cited source; treat affected statements as unverified.
        </p>
      )}

      <ol className="mt-2 space-y-2">
        {references.map((ref) => (
          <li key={ref.number} className="text-slate-300">
            <Reference reference={ref} />
          </li>
        ))}
      </ol>
    </section>
  );
}

function Reference({ reference: r }: { reference: ReferenceDocument }) {
  const locator = [r.pages ? `pp. ${r.pages}` : null, r.sections].filter(Boolean).join(", ");
  return (
    <div>
      <div>
        <span className="text-slate-500">[{r.number}]</span>{" "}
        <span className="text-slate-200">{r.title}</span>
        <span className="text-slate-500"> — {r.provider}</span>
        {r.published_date && <span className="text-slate-500"> ({r.published_date})</span>}
      </div>
      {r.authors.length > 0 && (
        <div className="text-slate-400">{r.authors.join(", ")}</div>
      )}
      <div className="flex flex-wrap gap-x-3 gap-y-0.5 text-[11px] text-slate-500">
        {locator && <span>{locator}</span>}
        {r.doi && <span>DOI: {r.doi}</span>}
        {r.dataset_id && <span>dataset: {r.dataset_id}</span>}
        {r.data_timestamp && <span>as of {r.data_timestamp}</span>}
        {r.methodology && <span>method: {r.methodology}</span>}
      </div>
      <div className="flex flex-wrap gap-x-3 text-[11px]">
        {r.url && (
          <a href={r.url} className="text-sky-400 hover:underline" target="_blank" rel="noreferrer">
            source
          </a>
        )}
        {r.pdf_url && (
          <a
            href={r.pdf_url}
            className="text-sky-400 hover:underline"
            target="_blank"
            rel="noreferrer"
          >
            PDF
          </a>
        )}
      </div>
    </div>
  );
}
