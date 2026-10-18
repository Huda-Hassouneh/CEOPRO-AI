import test from 'node:test';
import assert from 'node:assert/strict';
import React from 'react';
import {renderToStaticMarkup} from 'react-dom/server';
import {CompetitorProductLinks} from '../src/features/market-intelligence/components/CompetitorProductLinks.jsx';
import {CompetitorSourceReviews} from '../src/features/market-intelligence/components/CompetitorSourceReviews.jsx';
import {SmartAlertsPage} from '../src/features/smart-alerts/SmartAlertsPage.jsx';
import {businessPrimaryNavigation} from '../src/shared/config/businessNavigation.js';
import {competitorsApi} from '../src/features/market-intelligence/api/competitorsApi.js';
globalThis.React=React;
test('withdrawn worker interfaces render nothing without mounting query hooks',()=>{
 for(const Component of [CompetitorProductLinks,CompetitorSourceReviews,SmartAlertsPage])assert.equal(renderToStaticMarkup(React.createElement(Component)), '');
 assert.ok(!businessPrimaryNavigation.some(item=>item.key==='smartAlerts'));
 for(const key of ['connectData','rag'])assert.ok(businessPrimaryNavigation.some(item=>item.key===key));
});
test('direct frontend mutation attempts reject before invoking HTTP',async()=>{
 for(const key of ['discover','catalog','productCandidates','linkProduct','rejectCandidate','previewProduct','create','track','schedule','cancelDiscovery','retryCollection','reviewSource','confirm'])await assert.rejects(()=>competitorsApi[key](),error=>error.code==='NOT_IMPLEMENTED');
});
