import { FileText, Image as ImageIcon, X } from "lucide-react";

const fileType = (attachment) =>
  attachment.name?.split(".").pop()?.toLocaleUpperCase() ||
  attachment.type ||
  "";

export function MessageAttachments({
  attachments,
  onRemove,
  formatSize,
  t,
  compact = false
}) {
  if (!Array.isArray(attachments) || attachments.length === 0) return null;
  return (
    <div className={`rag-message-attachments ${compact ? "is-compact" : ""}`}>
      {attachments.map((attachment) => (
        <div
          className={`rag-message-attachment is-${attachment.kind}`}
          key={attachment.id}
        >
          {attachment.kind === "image" && attachment.previewUrl ? (
            <img
              src={attachment.previewUrl}
              alt={
                attachment.name || t("ragAssistant.attachments.imagePreview")
              }
            />
          ) : (
            <span className="rag-message-attachment__icon">
              {attachment.kind === "image" ? (
                <ImageIcon size={16} />
              ) : (
                <FileText size={16} />
              )}
            </span>
          )}
          <span className="rag-message-attachment__copy">
            <strong title={attachment.name}>{attachment.name}</strong>
            <small>
              {[
                fileType(attachment),
                attachment.size != null && formatSize(attachment.size)
              ]
                .filter(Boolean)
                .join(" · ")}
            </small>
          </span>
          {onRemove && (
            <button
              type="button"
              onClick={() => onRemove(attachment.id)}
              aria-label={t("ragAssistant.attachments.remove", {
                name: attachment.name
              })}
            >
              <X size={14} />
            </button>
          )}
        </div>
      ))}
    </div>
  );
}
