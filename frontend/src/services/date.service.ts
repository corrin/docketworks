type WeekRange = {
  startDate: string
  endDate: string
  weekDays: string[]
}

type DateRange = {
  startDate: string
  endDate: string
}

export { type WeekRange, type DateRange }

export class DateService {
  private static instance: DateService

  static getInstance(): DateService {
    if (!DateService.instance) {
      DateService.instance = new DateService()
    }
    return DateService.instance
  }

  createLocalDate(dateString: string): Date {
    const [year, month, day] = dateString.split('-').map(Number)
    return new Date(year, month - 1, day)
  }

  formatToLocalString(date: Date): string {
    const year = date.getFullYear()
    const month = String(date.getMonth() + 1).padStart(2, '0')
    const day = String(date.getDate()).padStart(2, '0')
    return `${year}-${month}-${day}`
  }

  today(): string {
    return this.formatToLocalString(new Date())
  }

  getCurrentWeekStart(): string {
    const today = new Date()
    const monday = this.getMondayOfWeek(today)
    return this.formatToLocalString(monday)
  }

  getMondayOfWeek(date: Date): Date {
    const day = date.getDay()
    const diff = day === 0 ? -6 : 1 - day
    const monday = new Date(date)
    monday.setDate(date.getDate() + diff)
    return monday
  }

  getFridayOfWeek(date: Date): Date {
    const monday = this.getMondayOfWeek(date)
    const friday = new Date(monday)
    friday.setDate(monday.getDate() + 4)
    return friday
  }

  getWeekRange(date: Date | string): WeekRange {
    const inputDate = typeof date === 'string' ? this.createLocalDate(date) : date

    const monday = this.getMondayOfWeek(inputDate)
    const friday = this.getFridayOfWeek(inputDate)

    const weekDays: string[] = []
    for (let i = 0; i < 5; i++) {
      const day = new Date(monday)
      day.setDate(monday.getDate() + i)
      weekDays.push(this.formatToLocalString(day))
    }

    return {
      startDate: this.formatToLocalString(monday),
      endDate: this.formatToLocalString(friday),
      weekDays,
    }
  }

  getCurrentWeekRange(): WeekRange {
    return this.getWeekRange(new Date())
  }

  navigateWeek(currentWeekStart: string, direction: number): string {
    const currentDate = this.createLocalDate(currentWeekStart)
    const newDate = new Date(currentDate)
    newDate.setDate(currentDate.getDate() + direction * 7)
    return this.formatToLocalString(this.getMondayOfWeek(newDate))
  }

  navigateDay(currentDate: string, direction: number): string {
    const date = this.createLocalDate(currentDate)
    const newDate = new Date(date)
    newDate.setDate(date.getDate() + direction)
    return this.formatToLocalString(newDate)
  }

  formatDisplayDate(
    dateString: string,
    options: {
      weekday?: boolean
      year?: boolean
      month?: 'short' | 'long'
      locale?: string
    } = {},
  ): string {
    const { weekday = true, year = true, month = 'long', locale = 'en-NZ' } = options

    const date = this.createLocalDate(dateString)

    const formatOptions: Intl.DateTimeFormatOptions = {
      day: 'numeric',
      month,
    }

    if (weekday) formatOptions.weekday = 'long'
    if (year) formatOptions.year = 'numeric'

    return date.toLocaleDateString(locale, formatOptions)
  }

  formatDateRange(startDate: string, endDate: string, locale = 'en-NZ'): string {
    const start = this.createLocalDate(startDate)
    const end = this.createLocalDate(endDate)

    const startFormatted = start.toLocaleDateString(locale, {
      day: 'numeric',
      month: 'short',
    })

    const endFormatted = end.toLocaleDateString(locale, {
      day: 'numeric',
      month: 'short',
      year: 'numeric',
    })

    return `${startFormatted} - ${endFormatted}`
  }

  getDayName(dateString: string, short = false): string {
    const date = this.createLocalDate(dateString)
    return date.toLocaleDateString('en-US', {
      weekday: short ? 'short' : 'long',
    })
  }

  getDayNumber(dateString: string): string {
    const date = this.createLocalDate(dateString)
    return date.toLocaleDateString('en-US', { day: 'numeric' })
  }

  isToday(dateString: string): boolean {
    return dateString === this.today()
  }

  isCurrentWeek(dateString: string): boolean {
    const currentWeek = this.getCurrentWeekRange()
    return dateString >= currentWeek.startDate && dateString <= currentWeek.endDate
  }

  isValidDateString(dateString: string): boolean {
    if (!/^\d{4}-\d{2}-\d{2}$/.test(dateString)) {
      return false
    }

    const date = this.createLocalDate(dateString)
    return !isNaN(date.getTime())
  }

  getWeekDisplayDays(weekStart: string): Array<{
    date: string
    name: string
    short: string
    number: string
    isToday: boolean
  }> {
    const weekRange = this.getWeekRange(weekStart)

    return weekRange.weekDays.map((date) => ({
      date,
      name: this.getDayName(date, false),
      short: this.getDayName(date, true),
      number: this.getDayNumber(date),
      isToday: this.isToday(date),
    }))
  }
}

export const dateService = DateService.getInstance()

export const today = () => dateService.today()
export const getCurrentWeekStart = () => dateService.getCurrentWeekStart()
export const getWeekRange = (date: Date | string) => dateService.getWeekRange(date)
export const getCurrentWeekRange = () => dateService.getCurrentWeekRange()
export const navigateWeek = (currentWeekStart: string, direction: number) =>
  dateService.navigateWeek(currentWeekStart, direction)
export const navigateDay = (currentDate: string, direction: number) =>
  dateService.navigateDay(currentDate, direction)
export const formatDisplayDate = (
  dateString: string,
  options?: {
    weekday?: boolean
    year?: boolean
    month?: 'short' | 'long'
    locale?: string
  },
) => dateService.formatDisplayDate(dateString, options)
export const formatDateRange = (startDate: string, endDate: string, locale?: string) =>
  dateService.formatDateRange(startDate, endDate, locale)
export const getDayName = (dateString: string, short?: boolean) =>
  dateService.getDayName(dateString, short)
export const getDayNumber = (dateString: string) => dateService.getDayNumber(dateString)
export const isToday = (dateString: string) => dateService.isToday(dateString)
export const isCurrentWeek = (dateString: string) => dateService.isCurrentWeek(dateString)
export const isValidDateString = (dateString: string) => dateService.isValidDateString(dateString)
export const getWeekDisplayDays = (weekStart: string) => dateService.getWeekDisplayDays(weekStart)
export const createLocalDate = (dateString: string) => dateService.createLocalDate(dateString)
export const formatToLocalString = (date: Date) => dateService.formatToLocalString(date)
