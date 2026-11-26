import { useEffect, useState } from "react";
import { useActions } from "../api/ActionsContext";
import { t, translateCode } from "../i18n";
import type { BlockOf } from "../ui-schema/schema";

function useAssetUrl(assetId: string): { url: string | null; failed: boolean } {
  const actions = useActions();
  const [state, setState] = useState<{ url: string | null; failed: boolean }>({ url: null, failed: false });
  useEffect(() => {
    let cancelled = false;
    let created: string | null = null;
    actions
      ?.loadAsset(assetId)
      .then((url) => {
        created = url;
        if (!cancelled) setState({ url, failed: false });
      })
      .catch(() => !cancelled && setState({ url: null, failed: true }));
    return () => {
      cancelled = true;
      if (created) URL.revokeObjectURL(created);
    };
  }, [actions, assetId]);
  return state;
}

export function ImageFigure({ block }: { block: BlockOf<"image"> }) {
  const { url, failed } = useAssetUrl(block.asset_id);
  const placeholder = block.description_source === "placeholder";
  const alt = block.alt_text ?? t("img.placeholder_alt");
  return (
    <figure className="figure">
      {url ? (
        <img src={url} alt={alt} />
      ) : (
        <p className="muted" role="img" aria-label={alt}>
          {failed ? t("img.failed") : t("img.loading")}
        </p>
      )}
      <figcaption>
        {placeholder ? t("img.no_description") : block.alt_text}
        {block.adapted && <span className="badge"> {t("img.adapted")}</span>}
      </figcaption>
      {block.long_description && (
        <details>
          <summary>{t("img.long")}</summary>
          <p>{block.long_description}</p>
        </details>
      )}
    </figure>
  );
}

export function FallbackView({ block }: { block: BlockOf<"fallback"> }) {
  return (
    <div className="callout callout-warning" role="status">
      <span aria-hidden="true" className="callout-icon">
        ⚠
      </span>
      <div>
        <p>{translateCode(t, "reason", block.reason_code)}</p>
        {block.text && <p className="muted">{block.text}</p>}
      </div>
    </div>
  );
}

export function UnknownBlock() {
  return (
    <p className="callout callout-warning" role="status">
      {t("meta.dropped")}
    </p>
  );
}
