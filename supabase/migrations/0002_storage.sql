-- STRIX cloud persistence — private evidence/replay object storage.
--
-- The `strix-evidence` bucket holds the byte-exact, SHA-256-verified run bundles
-- (raw evidence + replay artifacts) uploaded by the executor. It is PRIVATE:
-- objects are reachable only via the service role (server-side) or by the owning
-- user, whose id is the first path segment (`<user_id>/<run_id>.zip`).

insert into storage.buckets (id, name, public)
values ('strix-evidence', 'strix-evidence', false)
on conflict (id) do nothing;

-- Owner-scoped read of one's own evidence bundles. Writes are performed by the
-- service role only (the executor), so no INSERT/UPDATE policy is granted to
-- end users — they can never plant or alter evidence.
drop policy if exists strix_evidence_read_own on storage.objects;
create policy strix_evidence_read_own on storage.objects
    for select to authenticated
    using (
        bucket_id = 'strix-evidence'
        and (storage.foldername(name))[1] = (select auth.uid())::text
    );
