/**
 * AudioPlayer — renders an AudioBlock from the backend.
 *
 * Features:
 * - Fetches the audio asset via the authenticated API (bearer token).
 * - Standard HTML5 <audio> controls (play/pause/seek/volume).
 * - Karaoke mode: highlights the current word as audio plays.
 * - Speed display (read-only — the speed was fixed at generation time).
 * - Screen-reader accessible: aria-live region announces the current word.
 *
 * The karaoke highlight uses a simple linear scan through word_timestamps
 * matching currentTime (in ms). It runs on requestAnimationFrame when
 * playing and stops immediately on pause.
 */
import { useCallback, useEffect, useRef, useState } from "react";
import { useActions } from "../api/ActionsContext";
import { t } from "../i18n";
import type { BlockOf } from "../ui-schema/schema";

type Props = { block: BlockOf<"audio"> };

/** Returns the index of the word currently being spoken, or -1. */
function activeWordIndex(timestamps: BlockOf<"audio">["word_timestamps"], currentMs: number): number {
  for (let i = 0; i < timestamps.length; i++) {
    if (currentMs >= timestamps[i].start_ms && currentMs < timestamps[i].end_ms) return i;
  }
  return -1;
}

export function AudioPlayer({ block }: Props) {
  const actions = useActions();
  const audioRef = useRef<HTMLAudioElement>(null);
  const rafRef = useRef<number>(0);
  const [url, setUrl] = useState<string | null>(null);
  const [failed, setFailed] = useState(false);
  const [currentWordIdx, setCurrentWordIdx] = useState(-1);
  const [playing, setPlaying] = useState(false);
  const liveRef = useRef<HTMLSpanElement>(null);

  const hasKaraoke = block.word_timestamps.length > 0;

  // Load audio asset via authenticated fetch
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
      cancelAnimationFrame(rafRef.current);
    };
  }, [actions, block.asset_id]);

  // RAF loop for karaoke word highlighting
  const tick = useCallback(() => {
    const audio = audioRef.current;
    if (!audio || audio.paused) return;
    const ms = audio.currentTime * 1000;
    setCurrentWordIdx(activeWordIndex(block.word_timestamps, ms));
    rafRef.current = requestAnimationFrame(tick);
  }, [block.word_timestamps]);

  const onPlay = () => {
    setPlaying(true);
    if (hasKaraoke) rafRef.current = requestAnimationFrame(tick);
  };
  const onPause = () => {
    setPlaying(false);
    cancelAnimationFrame(rafRef.current);
  };
  const onEnded = () => {
    setPlaying(false);
    setCurrentWordIdx(-1);
    cancelAnimationFrame(rafRef.current);
  };

  if (failed) {
    return (
      <div className="audio-player audio-failed" role="status">
        {t("audio.failed")}
      </div>
    );
  }

  if (!url) {
    return (
      <div className="audio-player audio-loading" role="status" aria-busy="true">
        {t("audio.loading")}
      </div>
    );
  }

  return (
    <div className="audio-player" lang={block.language ?? undefined}>
      {/* Speed badge */}
      {block.speed !== 1.0 && (
        <span className="audio-speed-badge" aria-label={t("audio.speed", { speed: String(block.speed) })}>
          {block.speed.toFixed(1)}×
        </span>
      )}

      {/* Native audio controls */}
      <audio
        ref={audioRef}
        src={url}
        controls
        onPlay={onPlay}
        onPause={onPause}
        onEnded={onEnded}
        aria-label={t("audio.player_label")}
      />

      {/* Karaoke transcript */}
      {hasKaraoke && (
        <>
          {/* Screen reader: current word announced live */}
          <span
            ref={liveRef}
            aria-live="polite"
            aria-atomic="true"
            className="sr-only"
          >
            {currentWordIdx >= 0 ? block.word_timestamps[currentWordIdx].word : ""}
          </span>

          {/* Visual karaoke line */}
          <p className="karaoke-line" aria-hidden="true">
            {block.word_timestamps.map((w, i) => (
              <span
                key={i}
                className={
                  i === currentWordIdx
                    ? "karaoke-word karaoke-active"
                    : i < currentWordIdx
                    ? "karaoke-word karaoke-past"
                    : "karaoke-word"
                }
              >
                {w.word}{" "}
              </span>
            ))}
          </p>
        </>
      )}
    </div>
  );
}
