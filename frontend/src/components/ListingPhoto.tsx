import { useState } from "react";

/**
 * A listing's photo, with a placeholder for the cars that don't have one.
 *
 * Two things this gets right that the inline `<img>` it replaces did not:
 *
 * - **`key={src}` forces a fresh DOM node per photo.** React otherwise
 *   reuses one node and only swaps `src`, and a browser keeps painting the
 *   old image until the new one has finished loading. On the scatter chart,
 *   where a single hover card is reused as the cursor moves between points,
 *   that meant one listing's photo sitting above another listing's price.
 * - **A failed load is React state, not `element.style.display = "none"`.**
 *   Hiding the node imperatively happened behind React's back, so the flag
 *   outlived the listing that set it: the same node, reused for the next
 *   card, stayed invisible however good its own photo was.
 */
/** A quiet car silhouette for ads without a photo.
 *
 * Ink-coloured and sized in em so the existing placeholderClassName
 * font-size keeps controlling its scale everywhere it appears. The emoji
 * it replaces read as a toy - one bright red cartoon repeated across
 * every photo-less card was the loudest thing on the page, saying
 * nothing. */
function CarSilhouette() {
  return (
    <svg viewBox="0 0 48 20" style={{ width: "3.4em" }} aria-hidden="true" fill="currentColor" opacity="0.55">
      <path d="M1.5 13.2c0-2.4 1.8-3.5 4.4-3.9l4.6-.7 3.4-4A5.6 5.6 0 0 1 18.2 2.6h8c1.7 0 3.4.8 4.5 2.1l3.4 3.9 5.8.8c2.5.4 4.6 1.6 4.6 3.9v1c0 .9-.7 1.6-1.6 1.6h-2.2a4.9 4.9 0 0 0-9.6 0H16.9a4.9 4.9 0 0 0-9.6 0H3.1c-.9 0-1.6-.7-1.6-1.6v-1.1Z" />
      <circle cx="12.1" cy="15.3" r="3" fill="var(--surface-2)" />
      <circle cx="12.1" cy="15.3" r="1.3" />
      <circle cx="35.9" cy="15.3" r="3" fill="var(--surface-2)" />
      <circle cx="35.9" cy="15.3" r="1.3" />
    </svg>
  );
}

export function ListingPhoto({
  src,
  placeholderClassName = "text-2xl",
  withLabel = false,
}: {
  src: string | undefined;
  placeholderClassName?: string;
  /** Larger cards say why there is no picture. A bare car emoji reads as
   * "the site is broken"; these are ads whose sellers uploaded no photo
   * (verified against the offer pages - AutoScout24 shows a placeholder
   * there too), and saying so makes the gap the ad's, not ours. */
  withLabel?: boolean;
}) {
  // Which src failed, rather than a bare "it failed" boolean — the flag then
  // clears itself as soon as a different photo arrives, with no effect hook
  // and no way for one broken URL to blank out the next listing's photo.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  if (!src || failedSrc === src) {
    return (
      <div className={`flex h-full w-full flex-col items-center justify-center gap-1.5 text-muted ${placeholderClassName}`}>
        <CarSilhouette />
        {withLabel && <span className="text-[10px]">No photo in this ad</span>}
      </div>
    );
  }

  return (
    <img
      key={src}
      src={src}
      alt=""
      loading="lazy"
      className="h-full w-full object-cover"
      onError={() => setFailedSrc(src)}
    />
  );
}
