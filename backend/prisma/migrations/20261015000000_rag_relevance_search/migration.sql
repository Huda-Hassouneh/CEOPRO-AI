-- SQL-managed search sidecars; original documents and citation chunks are preserved.
CREATE TABLE public.rag_document_search (
  tenant_id uuid NOT NULL,
  document_id uuid NOT NULL,
  index_version integer NOT NULL,
  content_state text NOT NULL CHECK (content_state IN ('ready','empty','unreadable')),
  indexed_at timestamptz NOT NULL DEFAULT now(),
  PRIMARY KEY (tenant_id, document_id),
  FOREIGN KEY (tenant_id, document_id) REFERENCES public.rag_documents_metadata(tenant_id, document_id) ON DELETE CASCADE
);
CREATE TABLE public.rag_document_search_passages (
  tenant_id uuid NOT NULL,
  document_id uuid NOT NULL,
  passage_index integer NOT NULL CHECK (passage_index >= 0),
  search_text text NOT NULL,
  search_vector tsvector GENERATED ALWAYS AS (
    to_tsvector('simple'::regconfig, search_text) || to_tsvector('english'::regconfig, search_text)
  ) STORED,
  PRIMARY KEY (tenant_id, document_id, passage_index),
  FOREIGN KEY (tenant_id, document_id) REFERENCES public.rag_document_search(tenant_id, document_id) ON DELETE CASCADE
);
CREATE INDEX idx_rag_search_passages_vector ON public.rag_document_search_passages USING gin(search_vector);
ALTER TABLE public.rag_document_search ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_document_search FORCE ROW LEVEL SECURITY;
ALTER TABLE public.rag_document_search_passages ENABLE ROW LEVEL SECURITY;
ALTER TABLE public.rag_document_search_passages FORCE ROW LEVEL SECURITY;
REVOKE ALL ON public.rag_document_search, public.rag_document_search_passages FROM PUBLIC;
GRANT SELECT, INSERT, UPDATE, DELETE ON public.rag_document_search, public.rag_document_search_passages TO ceopro_app;
CREATE POLICY rag_search_tenant ON public.rag_document_search TO ceopro_app
  USING (tenant_id = public.get_current_tenant() AND EXISTS (
    SELECT 1 FROM public.rag_documents_metadata d WHERE d.tenant_id=rag_document_search.tenant_id AND d.document_id=rag_document_search.document_id
  ))
  WITH CHECK (tenant_id = public.get_current_tenant() AND EXISTS (
    SELECT 1 FROM public.rag_documents_metadata d WHERE d.tenant_id=rag_document_search.tenant_id AND d.document_id=rag_document_search.document_id
  ));
CREATE POLICY rag_search_passages_tenant ON public.rag_document_search_passages TO ceopro_app
  USING (tenant_id = public.get_current_tenant() AND EXISTS (
    SELECT 1 FROM public.rag_documents_metadata d WHERE d.tenant_id=rag_document_search_passages.tenant_id AND d.document_id=rag_document_search_passages.document_id
  ))
  WITH CHECK (tenant_id = public.get_current_tenant() AND EXISTS (
    SELECT 1 FROM public.rag_documents_metadata d WHERE d.tenant_id=rag_document_search_passages.tenant_id AND d.document_id=rag_document_search_passages.document_id
  ));

-- Other trusted writers can modify source bytes/chunks. Invalidate only that
-- parent's derived index, without granting those roles general sidecar access.
-- Owned by the schema administrator deploying this migration, never ceopro_app.
CREATE FUNCTION public.invalidate_rag_document_search() RETURNS trigger
LANGUAGE plpgsql SECURITY DEFINER SET search_path = pg_catalog, public, pg_temp AS $$
BEGIN
  IF TG_TABLE_NAME = 'rag_documents_metadata' THEN
    DELETE FROM public.rag_document_search WHERE tenant_id=OLD.tenant_id AND document_id=OLD.document_id;
  ELSE
    IF TG_OP <> 'INSERT' THEN
      DELETE FROM public.rag_document_search s
      WHERE s.tenant_id=OLD.tenant_id AND s.document_id=OLD.document_id AND EXISTS (
        SELECT 1 FROM public.rag_documents_metadata d WHERE d.tenant_id=OLD.tenant_id
          AND d.document_id=OLD.document_id AND d.source_file_content IS NULL
      );
    END IF;
    IF TG_OP <> 'DELETE' THEN
      DELETE FROM public.rag_document_search s
      WHERE s.tenant_id=NEW.tenant_id AND s.document_id=NEW.document_id AND EXISTS (
        SELECT 1 FROM public.rag_documents_metadata d WHERE d.tenant_id=NEW.tenant_id
          AND d.document_id=NEW.document_id AND d.source_file_content IS NULL
      );
    END IF;
  END IF;
  RETURN NULL;
END $$;
REVOKE ALL ON FUNCTION public.invalidate_rag_document_search() FROM PUBLIC;
CREATE TRIGGER invalidate_rag_source_search AFTER UPDATE OF file_name, source_file_content, storage_bucket_path, processed_status
  ON public.rag_documents_metadata FOR EACH ROW EXECUTE FUNCTION public.invalidate_rag_document_search();
CREATE TRIGGER invalidate_rag_chunk_search AFTER INSERT OR UPDATE OR DELETE
  ON public.rag_document_chunks FOR EACH ROW EXECUTE FUNCTION public.invalidate_rag_document_search();
