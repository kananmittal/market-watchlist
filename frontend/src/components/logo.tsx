/**
 * Groww brand mark.
 *
 * Recreated as inline SVG rather than a raster asset: it stays crisp at every
 * size, adds no network request, and inherits the page's own rendering.
 */
export function GrowwLogo({
  size = 26,
  withWordmark = true,
  className = "",
}: {
  size?: number;
  withWordmark?: boolean;
  className?: string;
}) {
  return (
    <span className={`inline-flex items-center gap-2 ${className}`}>
      <svg
        width={size}
        height={size}
        viewBox="0 0 100 100"
        role="img"
        aria-label="Groww"
        className="shrink-0"
      >
        <defs>
          <clipPath id="groww-circle">
            <circle cx="50" cy="50" r="50" />
          </clipPath>
        </defs>
        <g clipPath="url(#groww-circle)">
          {/* Blue occupies the upper-left; the chart line divides the mark. */}
          <rect width="100" height="100" fill="#5367FF" />
          <path
            d="M-6 84 L33 57 L52 26 L64 47 L106 1 L106 106 L-6 106 Z"
            fill="#00D09C"
          />
        </g>
      </svg>
      {withWordmark ? (
        <span
          className="text-[17px] font-bold tracking-[-0.02em] text-ink"
          style={{ fontFeatureSettings: '"ss01"' }}
        >
          Groww
        </span>
      ) : null}
    </span>
  );
}
