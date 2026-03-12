-- Migration: switch file_embeddings from one-per-file to one-per-chunk
-- Run once against your PostgreSQL database, then re-sync all files.
--
--   psql $DATABASE_URL -f db/migrate_add_chunks.sql

-- 1. Drop the old unique constraint that enforced one embedding per file
ALTER TABLE file_embeddings
    DROP CONSTRAINT IF EXISTS file_embeddings_file_id_key;

-- 2. Add chunk_index (0-based); existing rows become chunk 0
ALTER TABLE file_embeddings
    ADD COLUMN IF NOT EXISTS chunk_index INTEGER NOT NULL DEFAULT 0;

-- 3. New unique constraint: one row per (file, chunk) pair
ALTER TABLE file_embeddings
    ADD CONSTRAINT uq_file_chunk UNIQUE (file_id, chunk_index);
