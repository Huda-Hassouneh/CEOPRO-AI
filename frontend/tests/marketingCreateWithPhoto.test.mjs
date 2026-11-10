import test from 'node:test';
import assert from 'node:assert/strict';
import { createPostWithPhoto } from '../src/features/marketing/api/createWithPhoto.js';

// A fake api that records the order of calls, the way the Studio makes them.
function fakeApi({ failUpload = false } = {}) {
  const calls = [];
  return {
    calls,
    createCampaign: async (req) => { calls.push(['create', req.generateImage ? 'with-picture' : 'no-picture']); return { campaign_id: 'c1' }; },
    uploadCampaignImage: async () => { if (failUpload) throw new Error('upload'); calls.push(['upload']); },
    setReferenceSelection: async (_id, sel) => { calls.push(['select', sel]); },
    generateImage: async (_id, opts) => { calls.push(['picture', opts.imageFormat]); },
    queueImageBatch: async (_id, opts) => { calls.push(['queue', opts.formats[0]]); },
  };
}

test('with a product photo, the picture is made only after the photo is stored and selected', async () => {
  const api = fakeApi();
  await createPostWithPhoto(api, { request: {}, photo: {}, queueImages: false, imageFormat: 'PORTRAIT' });
  assert.deepEqual(api.calls, [['create', 'no-picture'], ['upload'], ['select', 'ORIGINAL'], ['picture', 'PORTRAIT']]);
});

test('queued pictures are also queued after the photo is in place', async () => {
  const api = fakeApi();
  await createPostWithPhoto(api, { request: {}, photo: {}, queueImages: true, imageFormat: 'SQUARE' });
  assert.deepEqual(api.calls, [['create', 'no-picture'], ['upload'], ['select', 'ORIGINAL'], ['queue', 'SQUARE']]);
});

test('without a photo the picture is still made with the post, as before', async () => {
  const api = fakeApi();
  await createPostWithPhoto(api, { request: {}, photo: null, queueImages: false, imageFormat: 'SQUARE' });
  assert.deepEqual(api.calls, [['create', 'with-picture']]);
});

test('a failed photo upload still gives the post a picture', async () => {
  const api = fakeApi({ failUpload: true });
  const campaign = await createPostWithPhoto(api, { request: {}, photo: {}, queueImages: false, imageFormat: 'STORY' });
  assert.equal(campaign.campaign_id, 'c1');
  assert.deepEqual(api.calls, [['create', 'no-picture'], ['picture', 'STORY']]);
});
