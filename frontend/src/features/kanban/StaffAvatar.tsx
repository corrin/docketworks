/**
 * One staff face, in the panel and on a card's avatar strip.
 *
 * The person shape is declared structurally rather than as a union of the two
 * wire types: KanbanStaffOut and KanbanJobPersonOut both already carry id,
 * display_name and icon_url, so a union would only reintroduce v1's
 * "which shape is this?" branching (StaffAvatar.vue:63-120).
 */
export interface AvatarPerson {
  id: string
  display_name: string
  icon_url: string | null
}

// v1's palette (StaffAvatar.vue:122-146), kept so a given person keeps the
// same colour across the rewrite.
const AVATAR_COLORS: readonly [string, ...string[]] = [
  '#3498db',
  '#2ecc71',
  '#e74c3c',
  '#9b59b6',
  '#f39c12',
  '#1abc9c',
  '#d35400',
  '#c0392b',
  '#8e44ad',
  '#16a085',
  '#27ae60',
  '#2980b9',
  '#f1c40f',
  '#e67e22',
  '#34495e',
]

function colorFor(displayName: string): string {
  let sum = 0
  for (let index = 0; index < displayName.length; index += 1) {
    sum += displayName.charCodeAt(index)
  }
  // The modulo is always in range; the `??` satisfies noUncheckedIndexedAccess,
  // it is not a fallback for missing data.
  return AVATAR_COLORS[Math.abs(sum) % AVATAR_COLORS.length] ?? AVATAR_COLORS[0]
}

function initialsFor(displayName: string): string {
  const words = displayName.trim().split(/\s+/).filter(Boolean)
  const first = words[0]
  if (!first) return '??'
  const last = words.length > 1 ? words[words.length - 1] : undefined
  if (last) return (first.charAt(0) + last.charAt(0)).toUpperCase()
  return first.slice(0, 2).toUpperCase().padEnd(2, first.charAt(0).toUpperCase())
}

interface StaffAvatarProps {
  person: AvatarPerson
  size?: 'small' | 'normal'
  isActive?: boolean
}

export function StaffAvatar({ person, size = 'normal', isActive = false }: StaffAvatarProps) {
  const dimensions = size === 'small' ? 'h-5 w-5 text-[0.6rem]' : 'h-10 w-10 text-sm'
  const activeRing = isActive ? 'ring-2 ring-blue-300 ring-offset-1 border-2 border-blue-500' : ''

  return (
    <div
      data-staff-id={person.id}
      title={person.display_name}
      className={`relative flex shrink-0 items-center justify-center overflow-hidden rounded-full shadow-sm ${dimensions} ${activeRing}`}
    >
      {person.icon_url ? (
        <img
          src={person.icon_url}
          alt={person.display_name}
          className="h-full w-full object-cover"
        />
      ) : (
        <div
          className="flex h-full w-full items-center justify-center font-bold text-white"
          style={{ backgroundColor: colorFor(person.display_name) }}
        >
          {initialsFor(person.display_name)}
        </div>
      )}
    </div>
  )
}
