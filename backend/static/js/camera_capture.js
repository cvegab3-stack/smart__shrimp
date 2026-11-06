"use strict";

window.SmartShrimpCapture = {
  async fileAsBase64(file) {
    const image = await createImageBitmap(file);
    const canvas = document.createElement("canvas");
    canvas.width = image.width; canvas.height = image.height;
    canvas.getContext("2d").drawImage(image, 0, 0); image.close?.();
    return canvas.toDataURL("image/jpeg", 0.92).split(",")[1];
  },
  async videoAsBase64(video) {
    const canvas = document.createElement("canvas");
    canvas.width = video.videoWidth; canvas.height = video.videoHeight;
    canvas.getContext("2d").drawImage(video, 0, 0);
    return canvas.toDataURL("image/jpeg", 0.82).split(",")[1];
  },
};
