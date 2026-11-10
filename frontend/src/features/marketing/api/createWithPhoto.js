// Creating a post from the Studio, in the order that keeps the owner's
// product IN the picture: the campaign (copy) first, then the product photo
// is stored and selected as the reference, and only then is the picture made.
// Asking the server for the picture while creating the campaign would make
// it before the photo exists - a picture with no product in it.
//
// api: { createCampaign, uploadCampaignImage, setReferenceSelection,
//        generateImage, queueImageBatch } (marketingApi + the create mutation).
// Returns the created campaign. Photo/picture failures never lose the post.
export async function createPostWithPhoto(api, { request, photo, queueImages, imageFormat }) {
  const campaign = await api.createCampaign({ ...request, generateImage: !queueImages && !photo, imageFormat });
  if (photo) {
    try {
      await api.uploadCampaignImage({ campaignId: campaign.campaign_id, file: photo });
      await api.setReferenceSelection(campaign.campaign_id, 'ORIGINAL');
    } catch { /* the post is saved; the photo can be added again from it */ }
  }
  if (queueImages) {
    try {
      await api.queueImageBatch(campaign.campaign_id, { formats: [imageFormat], variations: 1, attachFirst: true });
    } catch { /* the post is saved; pictures can be made from it */ }
  } else if (photo) {
    try {
      await api.generateImage(campaign.campaign_id, { imageFormat });
    } catch { /* the post is saved; "Try a different picture" makes one */ }
  }
  return campaign;
}
