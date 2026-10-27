import { Camera } from "lucide-react";
import { useEffect, useRef, useState } from "react";
import Alert from "./Alert";
import Avatar from "./Avatar";
import { getErrorMessage } from "../services/api";
import { MAX_PHOTO_BYTES } from "../services/files";

const ACCEPT = ["image/jpeg", "image/png", "image/webp"];

/**
 * The current photo with Upload/Change and Remove buttons.
 *
 * `onUpload(file)` / `onRemove()` call the API and put the returned profile
 * (with its new photo_url) into the parent's state; a thrown error is shown
 * here. The type and size checks only give a quick message: the API
 * re-checks the actual file content.
 *
 * `layout="stacked"` puts the photo above a centred button (profile cards);
 * the default is photo and buttons side by side.
 *
 * `confirm` shows the chosen picture as a preview with Upload and Cancel
 * before anything is sent; without it the upload starts straight away.
 */
export default function PhotoUploader({
  name,
  role,
  photoUrl,
  onUpload,
  onRemove,
  layout = "row",
  confirm = false,
}) {
  const stacked = layout === "stacked";
  const input = useRef(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [pending, setPending] = useState(null); // { file, preview } while confirming

  // Release the preview's object URL when it is replaced or the card unmounts.
  useEffect(() => () => pending && URL.revokeObjectURL(pending.preview), [pending]);

  const run = async (action) => {
    setBusy(true);
    setError("");
    try {
      await action();
      return true;
    } catch (err) {
      setError(getErrorMessage(err, "Could not update the photo"));
      return false;
    } finally {
      setBusy(false);
    }
  };

  const choose = (e) => {
    const file = e.target.files?.[0];
    e.target.value = ""; // picking the same file again still fires onChange
    if (!file) return;
    if (!ACCEPT.includes(file.type)) return setError("Choose a JPEG, PNG or WebP image.");
    if (file.size > MAX_PHOTO_BYTES) return setError("The photo must be 5 MB or smaller.");
    setError("");
    if (confirm) setPending({ file, preview: URL.createObjectURL(file) });
    else run(() => onUpload(file));
  };

  const uploadPending = async () => {
    if (await run(() => onUpload(pending.file))) setPending(null);
  };

  return (
    <div
      className={stacked ? "photo-uploader stacked" : "row"}
      style={stacked ? undefined : { alignItems: "center", gap: 16 }}
    >
      <Avatar
        name={name}
        role={role}
        src={pending?.preview ?? photoUrl}
        size={stacked ? 136 : 88}
        alt={pending ? `Preview of the new photo for ${name}` : `Photo of ${name}`}
      />
      <div className="stack" style={{ gap: 8 }}>
        {pending ? (
          <div className="row">
            <button type="button" onClick={uploadPending} disabled={busy} aria-busy={busy}>
              {busy ? "Uploading…" : "Upload photo"}
            </button>
            <button type="button" className="secondary" onClick={() => setPending(null)} disabled={busy}>
              Cancel
            </button>
          </div>
        ) : (
          <div className="row">
            <button type="button" className="secondary" onClick={() => input.current?.click()} disabled={busy}>
              {stacked && <Camera size={17} aria-hidden="true" />}
              {busy ? "Saving…" : photoUrl ? "Change photo" : "Upload photo"}
            </button>
            {photoUrl && onRemove && (
              <button type="button" className="secondary" onClick={() => run(onRemove)} disabled={busy}>
                Remove
              </button>
            )}
          </div>
        )}
        <input ref={input} type="file" accept={ACCEPT.join(",")} onChange={choose} hidden />
        <p className="muted small">{pending ? "Preview — not saved yet." : "JPG, PNG or WebP (max 5 MB)."}</p>
        <Alert>{error}</Alert>
      </div>
    </div>
  );
}
