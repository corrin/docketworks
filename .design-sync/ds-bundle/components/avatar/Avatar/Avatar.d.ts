import type { AvatarFallbackProps, AvatarImageProps } from 'reka-ui'

export interface AvatarProps {
  /** Extra classes merged via cn(). */
  class?: string
}

/**
 * Avatar — root container (reka-ui AvatarRoot).
 * Default geometry: size-8 (2rem) circle, overflow-hidden.
 * @slot default — expects <AvatarImage> and/or <AvatarFallback>.
 */
export declare const Avatar: import('vue').DefineComponent<AvatarProps>

/**
 * AvatarImage — the photo (reka-ui AvatarImage).
 * Hidden until the src loads; shows AvatarFallback meanwhile/on error.
 */
export interface AvatarImageProps_ extends AvatarImageProps {
  /** Image source URL (reka-ui). */
  src?: string
}
export declare const AvatarImage: import('vue').DefineComponent<AvatarImageProps>

/**
 * AvatarFallback — shown while the image is loading or has failed
 * (reka-ui AvatarFallback). Typically initials.
 * @slot default — fallback content (initials / icon).
 */
export interface AvatarFallbackProps_ extends AvatarFallbackProps {
  /** Delay (ms) before fallback renders, to avoid flash (reka-ui). */
  delayMs?: number
  /** Extra classes merged via cn(). */
  class?: string
}
export declare const AvatarFallback: import('vue').DefineComponent<AvatarFallbackProps & { class?: string }>
