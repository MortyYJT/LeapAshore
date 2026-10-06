// Avatar handling. The image never leaves the browser: it is downscaled on a canvas and stored as a
// small data URL in local storage, so the account control stays responsive and the storage quota is
// not blown by a multi-megabyte phone photo.

const MAX_EDGE = 256;
const JPEG_QUALITY = 0.85;

export class AvatarError extends Error {}

function loadImage(file: File): Promise<HTMLImageElement> {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(file);
    const img = new Image();
    img.onload = () => {
      URL.revokeObjectURL(url);
      resolve(img);
    };
    img.onerror = () => {
      URL.revokeObjectURL(url);
      reject(new AvatarError("无法读取这张图片"));
    };
    img.src = url;
  });
}

/** Downscale to a square data URL. Rejects anything that is not an image. */
export async function toAvatarDataUrl(file: File): Promise<string> {
  if (!file.type.startsWith("image/")) {
    throw new AvatarError("请选择图片文件");
  }

  const img = await loadImage(file);
  const edge = Math.min(img.width, img.height);
  if (!edge) {
    throw new AvatarError("这张图片没有可用的尺寸");
  }

  const target = Math.min(MAX_EDGE, edge);
  const canvas = document.createElement("canvas");
  canvas.width = target;
  canvas.height = target;

  const ctx = canvas.getContext("2d");
  if (!ctx) throw new AvatarError("当前浏览器不支持处理图片");

  // Centre-crop to a square so the circular frame never distorts the face.
  ctx.drawImage(
    img,
    (img.width - edge) / 2,
    (img.height - edge) / 2,
    edge,
    edge,
    0,
    0,
    target,
    target,
  );

  const dataUrl = canvas.toDataURL("image/jpeg", JPEG_QUALITY);
  // local storage is roughly 5 MB; keep a generous ceiling so one avatar cannot fill it.
  if (dataUrl.length > 400_000) {
    throw new AvatarError("图片过大，请换一张更小的");
  }
  return dataUrl;
}
