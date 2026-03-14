import type { Component } from 'vue'
import {
  Settings,
  FileText,
  Link2,
  BarChart3,
  Sparkles,
  Calendar,
  DollarSign,
  Hash,
  User,
  File,
  Key,
  Clock,
  Percent,
  TrendingUp,
  Folder,
  HelpCircle,
  Mail,
  Globe,
  MapPin,
  Building2,
} from 'lucide-vue-next'

// Map icon name strings to actual Lucide components
const iconMap: Record<string, Component> = {
  Settings,
  FileText,
  Link2,
  BarChart3,
  Sparkles,
  Calendar,
  DollarSign,
  Hash,
  User,
  File,
  Key,
  Clock,
  Percent,
  TrendingUp,
  Folder,
  HelpCircle,
  Mail,
  Globe,
  MapPin,
  Building2,
}

// Section key to icon mapping (used when backend doesn't provide icon)
const sectionIconMap: Record<string, Component> = {
  general: Settings,
  google: FileText,
  xero: Link2,
  kpi: BarChart3,
  ai: Sparkles,
  working_hours: Calendar,
  address: MapPin,
  contact: Mail,
}

// Field key patterns to icon mapping (used when backend doesn't provide icon)
const fieldIconPatterns: Array<{ pattern: RegExp; icon: Component }> = [
  { pattern: /^(company_name|shop_client_name|test_client_name)$/, icon: User },
  { pattern: /(rate|target|markup)/, icon: DollarSign },
  { pattern: /percent/, icon: Percent },
  { pattern: /(number|starting_)/, icon: Hash },
  { pattern: /(url|folder)/, icon: Folder },
  { pattern: /(id|key|tenant)/, icon: Key },
  { pattern: /(sync|date)/, icon: Calendar },
  { pattern: /threshold/, icon: TrendingUp },
  { pattern: /(start|end)$/, icon: Clock },
  { pattern: /prefix/, icon: Hash },
  { pattern: /template/, icon: File },
  { pattern: /email/, icon: Mail },
  { pattern: /(address|suburb|city|country|post_code)/, icon: MapPin },
]

/**
 * Resolve an icon name string to a Vue component.
 * Returns HelpCircle as fallback for unknown icons.
 */
export function resolveIcon(iconName: string | undefined | null): Component {
  if (!iconName) return HelpCircle
  return iconMap[iconName] || HelpCircle
}

/**
 * Get icon for a section by its key.
 */
export function getSectionIcon(sectionKey: string): Component {
  return sectionIconMap[sectionKey] || Settings
}

/**
 * Get icon for a field by its key.
 */
export function getFieldIcon(fieldKey: string): Component {
  for (const { pattern, icon } of fieldIconPatterns) {
    if (pattern.test(fieldKey)) {
      return icon
    }
  }
  return HelpCircle
}

/**
 * Check if an icon name is registered.
 */
export function hasIcon(iconName: string): boolean {
  return iconName in iconMap
}
