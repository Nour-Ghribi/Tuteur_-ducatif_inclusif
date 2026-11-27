/**
 * VideoPlayer — renders a VideoBlock from the backend.
 *
 * Features:
 * - Fetches the video asset via the authenticated API (bearer token).
 * - Native HTML5 <video> controls (play/pause/seek/fullscreen).
 * - Shows topic caption + slide count + duration.
 * - Screen-reader accessible: aria-label on the video element.
 * - Graceful loading/error states.
 */
import { useEffect, useState } from "react";
import { useActions } from "../api/ActionsContext";
import { t } from "../i18n";
import type { BlockOf } from "../ui-schema/schema";

type Props = { block: BlockOf<"video"> };

export function VideoPlayer({ block }: Props) {
  const actions = useActions();
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);

  useEffect(() => {
    if (!actions) return;
    let revoked = false;
    let objectUrl: string | null = null;
    actions
      .loadAsset(block.asset_id)
      .then((u) => {
        objectUrl = u;
        if (!revoked) setUrl(u);
      })
      .catch(() => setFailed(true));
    return () => {
      revoked = true;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [actions, block.asset_id]);

  const durationLabel = block.duration_s
    ? `${Math.round(block.duration_s)} s`
    : "";
  const metaLabel = [
    block.slide_count > 1 ? `${block.slide_count} diapositives` : "1 diapositive",
    durationLabel,
  ]
    .filter(Boolean)
    .join(" · ");

  if (failed) {
    return (
      <div className="video-player video-failed" role="status">
        {t("video.failed")}
      </div>
    );
  }

  return (
    <figure className="video-player">
      {!url ? (
        <div className="video-loading" role="status" aria-busy="true">
          {t("video.loading")}
        </div>
      ) : (
        <video
          src={url}
          controls
          aria-label={`${t("video.player_label")} : ${block.topic}`}
          style={{ width: "100%", borderRadius: "8px" }}
        />
      )}
      <figcaption className="video-caption">
        <strong>{block.topic}</strong>
        {metaLabel && <span className="muted"> · {metaLabel}</span>}
      </figcaption>
    </figure>
  );
}
