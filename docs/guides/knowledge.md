# Knowledge Base

## Overview

The OMEGA knowledge base lets you ingest documents (PDF, markdown, web pages, plain text, CSV, JSON) into a searchable store with semantic chunking and vector embeddings. Once ingested, documents are searchable alongside your memories, enabling RAG-style retrieval over personal and project documentation.

Install PDF support:
- Full: `pip install omega-memory[knowledge-pdf]` (Docling primary extractor + pdfplumber fallback)
- Lite: `pip install omega-memory[knowledge-pdf-lite]` (pdfplumber only)

Without PDF extras, markdown, HTML, plain text, CSV, and JSON are supported out of the box.

Documents can be scoped to entities (e.g., `entity_id="acme"`) to keep different organizations' knowledge separate.

## Quick Example

```
# Ingest a PDF
omega_ingest_document(path_or_url="/path/to/architecture.pdf", title="System Architecture")

# Ingest a webpage
omega_ingest_document(path_or_url="https://docs.example.com/api-reference")

# Search across all ingested documents
omega_search_documents(query="authentication flow", limit=5)

# List everything in the knowledge base
omega_list_documents()
```

## Tools Reference

| Tool | Purpose |
|------|---------|
| `omega_ingest_document` | Ingest a document from a file path or URL. Supports `title`, `source_type` override, and `entity_id` for scoping. |
| `omega_search_documents` | Semantic search across all ingested chunks. Filter by `entity_id`, `source_type`, and `limit`. |
| `omega_list_documents` | List all documents in the knowledge base with chunk counts and metadata |
| `omega_remove_document` | Remove a document and all its chunks/embeddings by source path |
| `omega_scan_documents` | Scan a directory (default `~/.omega/documents/`) for new or changed files and auto-ingest. Checksum-based --- only re-ingests modified files. |
| `omega_sync_kb` | Sync pending files from the cloud knowledge base queue (Supabase uploads via web app) into the local knowledge base. |

## Supported Formats

| Format | Source Type | Notes |
|--------|------------|-------|
| PDF | `pdf` | Docling (primary, native markdown output) with pdfplumber fallback |
| Markdown | `markdown` | `.md` files |
| HTML | `webpage` | Web URLs and `.html` files |
| Plain text | `text` | `.txt` files |
| CSV | `text` | Ingested as text |
| JSON | `text` | Ingested as text |

Source type is auto-detected from the file extension or URL. Override with the `source_type` parameter if needed.

## Common Workflows

### Ingest a Document

From a local file:
```
omega_ingest_document(path_or_url="/Users/me/docs/api-spec.pdf", title="API Specification v2")
```

From a URL:
```
omega_ingest_document(path_or_url="https://docs.example.com/getting-started")
```

With entity scoping:
```
omega_ingest_document(path_or_url="/Users/me/docs/acme-contract.pdf", entity_id="acme", title="Acme Service Agreement")
```

### Search Documents

Basic search:
```
omega_search_documents(query="rate limiting configuration")
```

Filtered by entity:
```
omega_search_documents(query="billing terms", entity_id="acme", limit=3)
```

Filtered by source type:
```
omega_search_documents(query="deployment steps", source_type="pdf")
```

### Auto-Scan a Directory

Place files in `~/.omega/documents/` (or any directory), then scan:

```
omega_scan_documents()
```

Or scan a custom directory:
```
omega_scan_documents(directory="/Users/me/Projects/myapp/docs")
```

The scanner is checksum-based: it only re-ingests files whose content has changed since the last scan. New files are ingested automatically.

### Remove a Document

```
omega_remove_document(source_path="/Users/me/docs/old-spec.pdf")
```

This removes the document and all its chunks and embeddings from the knowledge base.

### CLI Commands

```bash
omega knowledge scan                          # Scan default directory
omega knowledge scan --directory /path/to/docs  # Scan custom directory
omega knowledge list                          # List all documents
omega knowledge search "authentication flow"  # Search documents
```

## Tips

- **Docling produces better PDF output.** The full `knowledge-pdf` extra uses Docling, which extracts native markdown with proper heading structure. The lite extra (pdfplumber only) works but produces flatter text.
- **Chunking is semantic.** Documents are split into chunks at natural boundaries (headings, paragraphs) rather than fixed token counts. This improves retrieval relevance.
- **Use entity scoping for multi-org work.** If you manage documents for multiple companies, scope each with `entity_id` so searches return only relevant results.
- **Auto-scan for hands-free ingestion.** Drop files into `~/.omega/documents/` and let hooks or CLI handle ingestion. The checksum check prevents duplicate work.
- **Search returns chunks, not whole documents.** Each result is a specific chunk with source attribution (document title, page number if applicable). This keeps results focused and relevant.
- **Remove and re-ingest to update.** If a document changes, remove the old version and ingest the new one. The scan command handles this automatically via checksum comparison.
