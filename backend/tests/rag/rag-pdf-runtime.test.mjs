import test, {mock} from 'node:test';
import assert from 'node:assert/strict';

test('PDF runtime failure is distinct from malformed input; extraction failure cannot become an empty success', async () => {
  let failure;
  await mock.module('pdfjs-dist/legacy/build/pdf.mjs', {namedExports: {
    getDocument: () => { throw failure; }
  }});
  try {
    const {extractSearchContent, RagDocumentProcessingError} = await import('../../src/modules/rag/service/rag-search-text.ts');
    const input = {file_name:'valid.pdf', source_file_content:Buffer.from('%PDF-1.7'), rag_document_chunks:[]};
    failure = new Error('Setting up fake worker failed: module unavailable');
    await assert.rejects(extractSearchContent(input), error => error instanceof RagDocumentProcessingError && error.cause === failure);
    failure = Object.assign(new Error('Invalid PDF structure'), {name:'InvalidPDFException'});
    assert.equal((await extractSearchContent(input)).state, 'unreadable');
    failure = Object.assign(new Error('Password required'), {name:'PasswordException'});
    assert.equal((await extractSearchContent(input)).state, 'unreadable');
  } finally {mock.restoreAll();}
});
