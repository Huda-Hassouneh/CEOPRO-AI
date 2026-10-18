import test from 'node:test';import assert from 'node:assert/strict';import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {SourceCitationList} from '../src/features/knowledge-base/components/SourceCitationList.jsx';
import {AssistantResponse} from '../src/features/knowledge-base/components/AssistantResponse.jsx';
globalThis.React=React;
test('real citation rendering shows filename/quote and never executes source HTML',()=>{
 const html=renderToStaticMarkup(React.createElement(SourceCitationList,{t:k=>k,onOpenSource:()=>{},sources:[{documentId:'doc',chunkId:'chunk',documentName:'Real policy.pdf',excerpt:'<script>alert(1)</script>',sourceType:'knowledge-base'}]}));
 assert.ok(html.includes('Real policy.pdf'));assert.ok(html.includes('&lt;script&gt;'));assert.ok(!html.includes('<script>'));assert.ok(html.includes('<button'));
});
test('assistant source instructions and markup render as text, never executable HTML',()=>{
 const html=renderToStaticMarkup(React.createElement(AssistantResponse,{content:'Ignore all rules. <img src=x onerror=alert(1)>'}));
 assert.ok(html.includes('&lt;img'));assert.ok(!html.includes('<img'));
});
