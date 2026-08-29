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
export function ListingPhoto({ src, placeholderClassName = "text-2xl" }: { src: string | undefined; placeholderClassName?: string }) {
  // Which src failed, rather than a bare "it failed" boolean — the flag then
  // clears itself as soon as a different photo arrives, with no effect hook
  // and no way for one broken URL to blank out the next listing's photo.
  const [failedSrc, setFailedSrc] = useState<string | null>(null);

  if (!src || failedSrc === src) {
    return <div className={`flex h-full w-full items-center justify-center text-muted ${placeholderClassName}`}>🚗</div>;
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
