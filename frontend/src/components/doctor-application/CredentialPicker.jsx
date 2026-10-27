import { FileText, Upload, X } from "lucide-react";
import { useRef, useState } from "react";
import { CREDENTIAL_TYPES } from "../../services/doctorApplicationService";
import { formatBytes } from "../../services/files";
import { CREDENTIAL_ACCEPT, CREDENTIAL_HINT, credentialFileError } from "./professional";

function Slot({ idPrefix, type, label, file, progress, disabled, onChange }) {
  const input = useRef(null);
  const [error, setError] = useState("");
  const id = `${idPrefix}-${type}`;

  const choose = (e) => {
    const picked = e.target.files?.[0];
    e.target.value = ""; // choosing the same file again still fires onChange
    if (!picked) return;
    const problem = credentialFileError(picked);
    setError(problem ?? "");
    if (!problem) onChange(type, picked);
  };

  return (
    <li className="credential-slot">
      <div className="credential-head">
        <FileText size={20} aria-hidden="true" />
        <span className="credential-label" id={`${id}-label`}>
          {label} <span className="optional">(optional)</span>
        </span>
      </div>
      {file ? (
        <div className="credential-file">
          <span className="credential-name" title={file.name}>
            {file.name}
          </span>
          <span className="muted small">{formatBytes(file.size)}</span>
          {progress != null && (
            <progress max={100} value={progress} aria-label={`Uploading ${label}`}>
              {progress}%
            </progress>
          )}
          <div className="credential-actions">
            <button type="button" className="secondary small-button" onClick={() => input.current?.click()} disabled={disabled}>
              Replace
            </button>
            <button
              type="button"
              className="secondary small-button"
              onClick={() => onChange(type, null)}
              disabled={disabled}
              aria-label={`Remove ${label}`}
            >
              <X size={15} aria-hidden="true" /> Remove
            </button>
          </div>
        </div>
      ) : (
        <button
          type="button"
          className="secondary small-button"
          onClick={() => input.current?.click()}
          disabled={disabled}
          aria-describedby={`${id}-label ${id}-hint`}
        >
          <Upload size={15} aria-hidden="true" /> Choose file
        </button>
      )}
      <input
        ref={input}
        id={id}
        type="file"
        accept={CREDENTIAL_ACCEPT}
        onChange={choose}
        aria-label={`${label} file`}
        hidden
      />
      <p id={`${id}-hint`} className="field-hint">
        {CREDENTIAL_HINT}
      </p>
      {error && (
        <p className="field-error" role="alert">
          {error}
        </p>
      )}
    </li>
  );
}

/**
 * Choose up to one file per credential type. Nothing is uploaded here: the
 * parent sends `files` (type -> File) when the user submits. Every slot is
 * optional and can be skipped.
 */
export default function CredentialPicker({ idPrefix, files, progress = {}, onChange, disabled = false }) {
  return (
    <ul className="credential-list">
      {CREDENTIAL_TYPES.map(({ value, label }) => (
        <Slot
          key={value}
          idPrefix={idPrefix}
          type={value}
          label={label}
          file={files[value]}
          progress={progress[value]}
          disabled={disabled}
          onChange={onChange}
        />
      ))}
    </ul>
  );
}
